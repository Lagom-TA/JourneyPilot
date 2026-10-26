#!/usr/bin/env python3
"""把内置出厂语料装载进知识库。

用法：

    python backend/scripts/load_factory_corpus.py
    python backend/scripts/load_factory_corpus.py --collection travel_tips

默认读取 ``backend/data/corpus/factory/`` 下的 Markdown，按文件名前缀
（``destinations__`` / ``local_culture__`` / ``travel_tips__``）分派到对应集合；
``--collection`` 会把整批语料写入指定集合。脚本使用 ``config.yaml`` 的数据库与
embedding 配置，要求 ``embedding.enabled=true``，并会先校验数据库结构。

同一集合内，同名来源重复装载是替换，因此可以直接重复执行。服务启动路径不会
自动装载；先用 ``backend/main.py`` 启动后端，再另开终端运行本脚本。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from travel_agent.knowledge.collections import FACTORY_KNOWLEDGE_COLLECTIONS  # noqa: E402
from travel_agent.knowledge.factory_corpus import (  # noqa: E402
    FactoryCorpusError,
    load_factory_corpus,
)


async def run(collection: str | None) -> int:
    try:
        counts = await load_factory_corpus(collection=collection)
    except FactoryCorpusError as exc:
        print(f"装载失败：{exc}", file=sys.stderr)
        return 1

    for name, count in sorted(counts.items()):
        print(f"{name:<16} {count:>6} 段")
    print(f"完成：共 {sum(counts.values())} 段")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--collection",
        choices=FACTORY_KNOWLEDGE_COLLECTIONS,
        default=None,
        metavar="COLLECTION",
        help=(
            "把整批语料写入指定出厂集合（"
            + " / ".join(FACTORY_KNOWLEDGE_COLLECTIONS)
            + "）；不指定时按文件名前缀分派"
        ),
    )
    args = parser.parse_args()
    return asyncio.run(run(args.collection))


if __name__ == "__main__":
    raise SystemExit(main())
