#!/usr/bin/env python3
"""查看或显式发布由发布流程管理的 JourneyPilot 产品数据。

用法：
    uv run --project backend python backend/scripts/publish_product_configuration.py
    uv run --project backend python backend/scripts/publish_product_configuration.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from travel_agent.config.publication import build_publication_summary, publish_seed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="校验或显式发布 JourneyPilot 系统产品配置。"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="把 Python 种子写入 product_configurations 与系统 travel_presets",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = asyncio.run(publish_seed()) if args.apply else build_publication_summary()
    result = {
        "mode": "apply" if args.apply else "dry_run",
        "publication": summary,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
