"""
知识库数据导入 CLI 工具

使用方式：
  # 从 Wikipedia 批量导入目的地摘要（一篇一个块）
  python backend/scripts/index_knowledge.py --wikipedia 日本 京都 东京 泰国 --collection destinations

  # 从 Wikipedia 导入所有预定义热门目的地（约 80 个）
  python backend/scripts/index_knowledge.py --wikipedia-popular --collection destinations

  # 从 Wikitravel 爬取旅行攻略
  python backend/scripts/index_knowledge.py --url https://wikitravel.org/zh/日本 --collection travel_tips

  # 从本地文件目录批量索引
  python backend/scripts/index_knowledge.py --dir ./knowledge_base --collection destinations

  # 从单个本地文件索引
  python backend/scripts/index_knowledge.py --file ./data/japan_guide.md --collection destinations

  # 查看所有集合的统计信息
  python backend/scripts/index_knowledge.py --stats

集合说明：
  destinations  - 目的地基础信息（来源：Wikipedia）
  visa_policies - 签证要求、入境政策（来源：Wikitravel）
  travel_tips   - 实用攻略、预算参考（来源：Wikitravel）
  local_culture - 文化习俗、注意事项（来源：Wikipedia/Wikitravel）
"""

import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from travel_agent.knowledge.collections import FACTORY_KNOWLEDGE_COLLECTIONS  # noqa: E402

# 出厂集合名只有一处定义，这里直接复用。
# 注意这里用的是**全部**出厂集合名，不是 `seeded_factory_collections()`：
# `--stats` 要的正是「每个出厂集合各有几段」，一个 0 段的集合印成「(空)」是它的答案。
COLLECTIONS = FACTORY_KNOWLEDGE_COLLECTIONS


async def index_wikipedia(titles: list, collection: str) -> None:
    from travel_agent.storage.maintenance.report import require_database_contract
    from travel_agent.knowledge.sources.wikipedia_fetcher import WikipediaFetcher

    await require_database_contract()

    fetcher = WikipediaFetcher(lang="zh")
    print(f"开始从中文 Wikipedia 抓取 {len(titles)} 个条目...")
    result = await fetcher.fetch_and_index(
        titles,
        collection=collection,
        content_type="destination",
    )
    await fetcher.close()
    print(f"完成：索引 {result['indexed']} 个文本块，失败 {result['failed']} 个")


async def index_wikipedia_popular(collection: str) -> None:
    from travel_agent.storage.maintenance.report import require_database_contract
    from travel_agent.knowledge.sources.wikipedia_fetcher import (
        WikipediaFetcher,
        POPULAR_DESTINATIONS_ZH,
    )

    await require_database_contract()

    fetcher = WikipediaFetcher(lang="zh")
    print(f"开始从中文 Wikipedia 抓取 {len(POPULAR_DESTINATIONS_ZH)} 个热门目的地...")
    result = await fetcher.fetch_and_index(
        POPULAR_DESTINATIONS_ZH,
        collection=collection,
        content_type="destination",
    )
    await fetcher.close()
    print(
        f"完成：处理 {len(POPULAR_DESTINATIONS_ZH)} 个目的地，"
        f"索引 {result['indexed']} 个文本块，失败 {result['failed']} 个"
    )


async def index_urls(urls: list, collection: str) -> None:
    from travel_agent.storage.maintenance.report import require_database_contract
    from travel_agent.knowledge.sources.web_crawler import WebCrawler

    await require_database_contract()

    crawler = WebCrawler()
    print(f"开始爬取 {len(urls)} 个 URL...")
    result = await crawler.crawl_and_index(urls, collection=collection)
    await crawler.close()
    print(f"完成：索引 {result['indexed']} 个文本块，失败 {result['failed']} 个")


async def index_directory(directory: str, collection: str) -> None:
    from travel_agent.storage.maintenance.report import require_database_contract
    from travel_agent.knowledge.sources.document_loader import DocumentLoader

    await require_database_contract()

    loader = DocumentLoader()
    print(f"开始索引目录：{directory}")
    result = await loader.load_directory(directory, collection=collection)
    print(f"完成：处理 {result['files']} 个文件，索引 {result['indexed']} 个文本块，失败 {result['failed']} 个")


async def index_file(file_path: str, collection: str) -> None:
    from travel_agent.storage.maintenance.report import require_database_contract
    from travel_agent.knowledge.sources.document_loader import DocumentLoader

    await require_database_contract()

    loader = DocumentLoader()
    print(f"开始索引文件：{file_path}")
    count = await loader.load_file(file_path, collection=collection)
    print(f"完成：索引 {count} 个文本块")


async def show_stats() -> None:
    from travel_agent.storage.maintenance.report import require_database_contract
    from travel_agent.knowledge.indexer import KnowledgeIndexer

    await require_database_contract()
    indexer = KnowledgeIndexer()

    print("\n知识库统计：")
    print(f"{'集合名':<20} {'块数':>8} {'来源数':>8} {'最早':>20} {'最新':>20}")
    print("-" * 80)
    for col in COLLECTIONS:
        stats = await indexer.get_collection_stats(col)
        if stats.get("total"):
            print(
                f"{col:<20} {stats['total']:>8} {stats['sources']:>8} "
                f"{str(stats.get('oldest', ''))[:19]:>20} "
                f"{str(stats.get('newest', ''))[:19]:>20}"
            )
        else:
            print(f"{col:<20} {'(空)':>8}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="JourneyPilot 知识库数据导入工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--wikipedia", "-w",
        nargs="+",
        metavar="TITLE",
        help="从中文 Wikipedia 批量抓取指定目的地（例：日本 京都 泰国）",
    )
    group.add_argument(
        "--wikipedia-popular",
        action="store_true",
        help="从中文 Wikipedia 抓取所有预定义热门目的地（约 80 个）",
    )
    group.add_argument(
        "--url",
        nargs="+",
        help="从指定 URL 爬取并索引（可多个）",
    )
    group.add_argument(
        "--dir",
        metavar="DIRECTORY",
        help="批量索引本地目录中的文档",
    )
    group.add_argument(
        "--file",
        metavar="FILE",
        help="索引单个本地文件",
    )
    group.add_argument(
        "--stats",
        action="store_true",
        help="显示所有知识库集合的统计信息",
    )

    parser.add_argument(
        "--collection", "-c",
        default="destinations",
        help="目标知识库集合（默认: destinations）",
    )
    args = parser.parse_args()

    if args.stats:
        asyncio.run(show_stats())
    elif args.wikipedia:
        asyncio.run(index_wikipedia(args.wikipedia, args.collection))
    elif args.wikipedia_popular:
        asyncio.run(index_wikipedia_popular(args.collection))
    elif args.url:
        asyncio.run(index_urls(args.url, args.collection))
    elif args.dir:
        asyncio.run(index_directory(args.dir, args.collection))
    elif args.file:
        asyncio.run(index_file(args.file, args.collection))


if __name__ == "__main__":
    main()
