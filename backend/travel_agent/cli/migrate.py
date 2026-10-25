from __future__ import annotations

import argparse
import sys
from typing import Any

from .environment import _backup_root, _settings, _target
from .output import EXIT_FAILED, EXIT_OK, _plan_lines


def cmd_migrate(args: argparse.Namespace) -> int:
    from ..storage.maintenance.checkpoint_schema import create_checkpoint_schema
    from ..storage.maintenance.connection import connect
    from ..storage.maintenance.migrate import Decision, plan, upgrade_sql

    settings = _settings()
    target = _target(settings)

    if args.sql:
        print(
            "# 离线预览：以下 SQL 未经任何数据库探测生成，也没有经过 census、"
            "备份和破坏性授权这几道闸门。\n"
            "# 它用来回答「迁移要做什么」，不是用来手工执行的部署脚本 —— "
            "真正的升级请用 `journeypilot migrate`。",
            file=sys.stderr,
        )
        upgrade_sql(target)
        return EXIT_OK

    try:
        with connect(target) as conn:
            migration_plan = plan(
                conn,
                target,
                embedding_dimensions=settings.embedding.dimensions,
                allow_destructive=args.allow_destructive,
            )
    except Exception as exc:
        print(f"数据库不可达：{exc}", file=sys.stderr)
        return EXIT_FAILED

    for line in _plan_lines(migration_plan):
        print(line)

    if migration_plan.refused:
        print("", file=sys.stderr)
        print("拒绝执行迁移。上面的「问题」和「下一步」说明了原因。", file=sys.stderr)
        return EXIT_FAILED

    if args.dry_run:
        print("\n--dry-run：以上是将要执行的动作，未改动数据库。")
        return EXIT_OK

    if migration_plan.decision is not Decision.UP_TO_DATE:
        code = _run_migration(args, settings, target, migration_plan)
        if code != EXIT_OK:
            return code

    try:
        created = create_checkpoint_schema(target)
    except Exception as exc:
        print(
            f"\nLangGraph checkpoint 表建立失败：{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "没有它们，plan_gate 与崩溃恢复不可用（API 会报 checkpointer 不可用）。",
            file=sys.stderr,
        )
        return EXIT_FAILED
    if created:
        print(f"\n已建立 LangGraph checkpoint 表：{'、'.join(created)}")

    with connect(target) as conn:
        after = plan(conn, target, embedding_dimensions=settings.embedding.dimensions)
    print("")
    print(
        f"迁移完成：revision {after.current_revision}，指纹 {after.fingerprint_digest[:16]}…"
    )
    return EXIT_OK


def _run_migration(
    args: argparse.Namespace, settings: Any, target: Any, migration_plan: Any
) -> int:

    from ..storage.maintenance.backup import create_backup
    from ..storage.maintenance.connection import connect
    from ..storage.maintenance.lock import MigrationLockTimeout, migration_lock
    from ..storage.maintenance.migrate import Decision, plan, stamp, upgrade

    if migration_plan.backup_required and not args.skip_backup:
        print("")
        print("非空数据库：迁移前自动备份…")
        try:
            with connect(target) as conn:
                result = create_backup(
                    conn,
                    target,
                    embedding_dimensions=settings.embedding.dimensions,
                    output_root=_backup_root(settings, args.backup_dir),
                    kind="automatic",
                    label="preupgrade",
                    preferred_container=settings.maintenance.postgres_container,
                )
        except Exception as exc:
            print(f"\n备份失败，因此不执行迁移：{exc}", file=sys.stderr)
            return EXIT_FAILED
        print(
            f"备份完成并校验通过：{result.directory}（{result.bytes_written / 1e6:.1f} MB）"
        )
    elif migration_plan.backup_required:
        print("")
        print("⚠ --skip-backup：跳过升级前备份。迁移失败时没有可恢复的快照。")

    try:
        with connect(target) as conn:
            with migration_lock(
                conn,
                timeout_seconds=settings.maintenance.migration_lock_timeout_seconds,
            ):
                fresh = plan(
                    conn,
                    target,
                    embedding_dimensions=settings.embedding.dimensions,
                    allow_destructive=args.allow_destructive,
                )
                if fresh.refused:
                    print(
                        "\n拿到迁移锁后重新判定为拒绝：" + "；".join(fresh.problems),
                        file=sys.stderr,
                    )
                    return EXIT_FAILED
                if fresh.decision is Decision.UP_TO_DATE:
                    print("\n另一个进程已经把数据库迁到最新，无需重复执行。")
                    return EXIT_OK
                if fresh.decision is Decision.ADOPT_BASELINE:
                    stamp(target, _baseline_revision())
                    print(
                        f"\n已纳管：{target.database} → {_baseline_revision()}（未执行 DDL）"
                    )
                    after_adopt = plan(
                        conn,
                        target,
                        embedding_dimensions=settings.embedding.dimensions,
                        allow_destructive=args.allow_destructive,
                    )
                    if after_adopt.decision is Decision.UP_TO_DATE:
                        print("数据库已是最新。")
                        return EXIT_OK
                    if after_adopt.refused:
                        print("", file=sys.stderr)
                        for problem in after_adopt.problems:
                            print(f"问题            {problem}", file=sys.stderr)
                        print(
                            f"下一步          {after_adopt.next_action}",
                            file=sys.stderr,
                        )
                        return EXIT_FAILED
                upgrade(target)
    except MigrationLockTimeout as exc:
        print(f"\n{exc}", file=sys.stderr)
        return EXIT_FAILED
    except Exception as exc:
        print(f"\n迁移失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            "数据库已回滚到这一条迁移执行前的状态（PostgreSQL 事务性 DDL）。",
            file=sys.stderr,
        )
        return EXIT_FAILED

    return EXIT_OK


def _baseline_revision() -> str:
    from ..storage.maintenance.schema_contract import BASELINE_REVISION

    return BASELINE_REVISION
