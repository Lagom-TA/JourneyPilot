from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .environment import _backup_root, _settings, _target
from .output import EXIT_FAILED, EXIT_OK, _emit


def cmd_backup(args: argparse.Namespace) -> int:
    from ..storage.maintenance.backup import (
        create_backup,
        list_backups,
        prune_automatic_backups,
        verify_backup,
    )
    from ..storage.maintenance.connection import connect

    settings = _settings()
    target = _target(settings)
    root = _backup_root(settings, args.backup_dir)

    if args.list:
        entries = list_backups(root)
        _emit(
            {"root": str(root), "entries": entries},
            as_json=args.json,
            lines=[f"备份目录 {root}（{len(entries)} 份）"]
            + [
                (
                    f"  {Path(e['path']).name}  {e.get('kind')}  "
                    f"revision={e.get('migration_revision')}  "
                    f"{(e.get('total_bytes') or 0) / 1e6:.1f} MB  {e.get('created_at')}"
                )
                if e.get("readable")
                else f"  {Path(e['path']).name}  ⚠ {e.get('problem')}"
                for e in entries
            ],
        )
        return EXIT_OK

    if args.verify:
        problems = verify_backup(Path(args.verify))
        _emit(
            {"path": args.verify, "ok": not problems, "problems": problems},
            as_json=args.json,
            lines=[f"校验 {args.verify}：{'通过' if not problems else '未通过'}"]
            + [f"  - {p}" for p in problems],
        )
        return EXIT_OK if not problems else EXIT_FAILED

    if args.prune:
        doomed = prune_automatic_backups(
            root, keep=settings.maintenance.keep_automatic_backups, dry_run=args.dry_run
        )
        _emit(
            {"pruned": doomed, "dry_run": args.dry_run},
            as_json=args.json,
            lines=[
                f"{'将删除' if args.dry_run else '已删除'} {len(doomed)} 份超出保留数"
                f"（{settings.maintenance.keep_automatic_backups}）的自动备份"
            ]
            + [f"  - {p}" for p in doomed]
            + ["手工备份不在清理范围内。"],
        )
        return EXIT_OK

    try:
        with connect(target) as conn:
            result = create_backup(
                conn,
                target,
                embedding_dimensions=settings.embedding.dimensions,
                output_root=root,
                kind=args.kind,
                label=args.label,
                preferred_container=settings.maintenance.postgres_container,
            )
    except Exception as exc:
        print(f"备份失败：{exc}", file=sys.stderr)
        return EXIT_FAILED

    _emit(
        {"directory": str(result.directory), "manifest": result.manifest},
        as_json=args.json,
        lines=[
            f"备份完成并校验通过：{result.directory}",
            f"  转储       {result.manifest['pg_dump']['bytes'] / 1e6:.1f} MB"
            f"（{result.manifest['pg_dump']['strategy']}，客户端 "
            f"PostgreSQL {result.manifest['pg_dump']['client_major']}）",
            f"  revision   {result.manifest['migration_revision']}",
            f"  业务行数   {result.manifest['total_business_rows']}",
            "  校验       文件非空 ✓  pg_restore --list 可解析 ✓  SHA-256 已记录 ✓",
        ],
    )
    return EXIT_OK
