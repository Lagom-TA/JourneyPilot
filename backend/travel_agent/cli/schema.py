from __future__ import annotations

import argparse
import json
import sys

from .environment import _settings, _target
from .output import EXIT_FAILED, EXIT_OK


def cmd_db_write_fingerprint(args: argparse.Namespace) -> int:

    from ..storage.maintenance.census import take_census
    from ..storage.maintenance.connection import connect
    from ..storage.maintenance.fingerprint import (
        fingerprint_digest,
        fingerprint_sync,
        normative_only,
    )
    from ..storage.maintenance.migrate import FINGERPRINTS_DIR, revision_line

    settings = _settings()
    target = _target(settings, database=args.database)
    revision = args.revision

    line = revision_line()
    if revision not in line:
        print(f"revision {revision} 不在迁移历史里：{line}", file=sys.stderr)
        return EXIT_FAILED

    with connect(target) as conn:
        census = take_census(conn)
        if census.alembic_revision != revision:
            print(
                f"拒绝生成存档：{target.describe()} 的 revision 是 "
                f"{census.alembic_revision!r}，不是 {revision!r}。"
                "存档必须来自一个刚刚迁到该 revision 的干净库。",
                file=sys.stderr,
            )
            return EXIT_FAILED
        fingerprint = fingerprint_sync(
            conn, embedding_dimensions=settings.embedding.dimensions
        )

    FINGERPRINTS_DIR.mkdir(parents=True, exist_ok=True)
    path = FINGERPRINTS_DIR / f"{revision}.json"
    archive = {
        "_note": (
            "由 `journeypilot db write-fingerprint` 生成。这是 revision "
            f"{revision} 的结构合同：adoption 判定与 API 只读校验都拿活库指纹与它比对。"
            "只包含进摘要的项 —— 装没装 zhparser、实际向量维度是环境事实，不在这里。"
            "手工编辑这个文件等于篡改校验基准。"
        ),
        **normative_only(fingerprint),
    }
    path.write_text(
        json.dumps(archive, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"已写入 {path}（摘要 {fingerprint_digest(fingerprint)}）")
    return EXIT_OK
