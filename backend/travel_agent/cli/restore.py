from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .environment import _settings, _target
from .output import EXIT_FAILED, EXIT_OK, _emit


def cmd_restore(args: argparse.Namespace) -> int:
    from ..storage.maintenance.restore import (
        RestoreError,
        drop_retained,
        list_retained,
        restore,
    )

    settings = _settings()
    target = _target(settings)

    if args.list_retained:
        retained = list_retained(target)
        _emit(
            {"retained": retained},
            as_json=args.json,
            lines=[f"恢复留档库（{len(retained)} 个）"]
            + [f"  - {name}" for name in retained],
        )
        return EXIT_OK

    if args.drop_retained:
        try:
            drop_retained(target, args.drop_retained)
        except RestoreError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_FAILED
        print(f"已删除 {args.drop_retained}")
        return EXIT_OK

    if not args.directory:
        print(
            "需要指定备份目录，或使用 --list-retained / --drop-retained",
            file=sys.stderr,
        )
        return EXIT_FAILED

    if not args.yes:
        print(
            f"即将把 {args.directory} 恢复成数据库 {target.describe()}。\n"
            "当前数据库会被改名留档（不会删除），恢复失败时当前数据库不受影响。\n"
            "确认请加 --yes。",
            file=sys.stderr,
        )
        return EXIT_FAILED

    try:
        result = restore(
            target,
            Path(args.directory),
            embedding_dimensions=settings.embedding.dimensions,
            terminate_active=args.terminate_active,
            preferred_container=settings.maintenance.postgres_container,
        )
    except Exception as exc:
        print(f"恢复失败：{exc}", file=sys.stderr)
        return EXIT_FAILED

    _emit(
        result.to_dict(),
        as_json=args.json,
        lines=[
            f"恢复完成：{result.restored_database}",
            f"  备份时间       {result.manifest.get('created_at')}",
            f"  revision       {result.manifest.get('migration_revision')}",
            f"  结构校验       {'通过' if result.checks.get('schema_matches_backup') else '跳过/未通过'}",
            f"  行数校验       {'通过' if result.checks.get('row_counts_match') else '未通过'}",
            f"  留档旧库       {result.retained_database}",
            "",
            f"确认无误后删除留档：journeypilot restore --drop-retained {result.retained_database}",
        ],
    )
    return EXIT_OK
