from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .environment import _backup_root, _settings, _target
from .output import EXIT_FAILED, EXIT_OK, _emit, _plan_lines


def _background_job_backlog(conn: Any) -> dict[str, Any]:

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status, count(*) FROM background_jobs GROUP BY status")
            counts = {str(status): int(total) for status, total in cur.fetchall()}
    except Exception as exc:
        conn.rollback()
        first_line = str(exc).splitlines()[0] if str(exc) else ""
        return {"readable": False, "problem": f"{type(exc).__name__}: {first_line}"}
    return {
        "readable": True,
        "pending": counts.get("pending", 0),
        "retry_wait": counts.get("retry_wait", 0),
        "running": counts.get("running", 0),
        "dead": counts.get("dead", 0),
        "completed": counts.get("completed", 0),
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    from ..storage.maintenance.backup import list_backups
    from ..storage.maintenance.checkpoint_schema import missing_checkpoint_tables
    from ..storage.maintenance.connection import connect
    from ..storage.maintenance.lock import release, try_acquire
    from ..storage.maintenance.migrate import plan

    settings = _settings()
    target = _target(settings)
    payload: dict[str, Any] = {"endpoint": target.describe()}
    lines: list[str] = [f"连接            {target.describe()}"]

    try:
        with connect(target) as conn:
            migration_plan = plan(
                conn,
                target,
                embedding_dimensions=settings.embedding.dimensions,
                allow_destructive=False,
            )
            missing_checkpoints = missing_checkpoint_tables(conn)
            job_backlog = _background_job_backlog(conn)
            lock_free = try_acquire(conn)
            if lock_free:
                release(conn)
    except Exception as exc:
        payload["database"] = {
            "reachable": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        _emit(
            payload,
            as_json=args.json,
            lines=lines
            + [
                f"数据库          不可达：{exc}",
                "",
                "下一步          确认 PostgreSQL 已启动、config.yaml 里的地址与口令正确",
            ],
        )
        return EXIT_FAILED

    census = migration_plan.census
    payload["database"] = {
        "reachable": True,
        "postgres_version": census.postgres_version,
        "postgres_major": census.postgres_major,
        "migration_revision": migration_plan.current_revision,
        "head_revision": migration_plan.head_revision,
        "schema_compatible": not migration_plan.refused,
        "backup_recommended": migration_plan.backup_required,
        "migration_lock_free": lock_free,
    }
    payload["extensions"] = {
        name: name in census.installed_extensions
        for name in (*census.installed_extensions, *census.missing_required_extensions)
    }
    payload["optional_capabilities"] = census.optional_capabilities
    payload["migration"] = migration_plan.to_dict()
    payload["census"] = census.to_dict()
    payload["checkpoint_schema"] = {
        "ready": not missing_checkpoints,
        "missing_tables": list(missing_checkpoints),
        "next_action": "journeypilot migrate" if missing_checkpoints else "",
    }

    payload["background_jobs"] = job_backlog

    backup_root = _backup_root(settings, args.backup_dir)
    backups = list_backups(backup_root)
    payload["backups"] = {
        "root": str(backup_root),
        "count": len(backups),
        "entries": backups[:5],
    }

    payload["embedding"] = {
        "configured": {
            "provider": settings.embedding.provider,
            "model": settings.embedding.model_name,
            "dimensions": settings.embedding.dimensions,
        },
        "columns": migration_plan.fingerprint.get("embedding_columns", {}),
        "stored": None,
        "note": "provider/model 尚未持久化，维度一致不等于向量空间兼容（P0-D 补齐）",
    }

    if not args.json:
        lines.extend(_plan_lines(migration_plan))
        lines.append("")
        lines.append(
            "checkpoint 表   "
            + (
                "就绪"
                if not missing_checkpoints
                else f"缺 {'、'.join(missing_checkpoints)} —— journeypilot migrate"
            )
        )
        lines.append(
            "后台任务        "
            + (
                f"待处理 {job_backlog['pending']}、重试等待 {job_backlog['retry_wait']}、"
                f"死信 {job_backlog['dead']}"
                if job_backlog.get("readable")
                else f"读不到：{job_backlog.get('problem')}"
            )
        )
        lines.append(
            f"迁移锁          {'空闲' if lock_free else '被占用（另一个 migrate 在跑）'}"
        )
        lines.append(f"备份目录        {backup_root}（{len(backups)} 份）")
        for entry in backups[:5]:
            if entry.get("readable"):
                lines.append(
                    f"  - {Path(entry['path']).name}  {entry.get('kind')}  "
                    f"revision={entry.get('migration_revision')}  "
                    f"{(entry.get('total_bytes') or 0) / 1e6:.1f} MB"
                )
            else:
                lines.append(
                    f"  - {Path(entry['path']).name}  ⚠ {entry.get('problem')}"
                )

    _emit(payload, as_json=args.json, lines=lines)
    return EXIT_FAILED if migration_plan.refused else EXIT_OK
