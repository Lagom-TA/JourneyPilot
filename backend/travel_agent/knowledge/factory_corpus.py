"""内置出厂语料的确定性装载路径。

语料是 ``backend/data/corpus/factory/`` 下的 Markdown 文件，文件名以
``<集合名>__`` 开头，装载时按前缀分派到对应的出厂集合。同一集合内，同一来源
重复装载会替换正文与分块，因此可以反复执行。

服务启动路径不会调用这里。需要时先启动后端，再另开终端运行
``python backend/scripts/load_factory_corpus.py``。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config.loader import get_settings
from ..paths import BACKEND_DIR
from .collections import FACTORY_KNOWLEDGE_COLLECTIONS
from .indexer import KnowledgeIndexer

DEFAULT_CORPUS_DIR = BACKEND_DIR / "data" / "corpus" / "factory"
COLLECTION_SEPARATOR = "__"
README_NAME = "README.md"


class FactoryCorpusError(RuntimeError):
    """语料目录、文件命名或装载前提不满足要求。"""


@dataclass(frozen=True)
class FactoryCorpusDocument:
    """一篇待装载的语料，以及它要写入的集合。"""

    path: Path
    collection: str
    source: str
    title: str
    text: str


def _title_from_markdown(text: str, fallback: str) -> str:
    """取正文第一个一级标题作为标题，没有标题时用文件名。"""

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or fallback
    return fallback


def discover_factory_corpus(
    corpus_dir: Path = DEFAULT_CORPUS_DIR,
) -> list[FactoryCorpusDocument]:
    """读取目录下的 Markdown，按文件名前缀确定目标集合。

    文件名格式为 ``<集合名>__<名称>.md``；``README.md`` 与子目录不参与装载。
    目录不存在、文件名为空、前缀不是出厂集合名或正文为空时抛出
    ``FactoryCorpusError``，不做静默跳过。
    """

    if not corpus_dir.is_dir():
        raise FactoryCorpusError(f"出厂语料目录不存在：{corpus_dir}")

    documents: list[FactoryCorpusDocument] = []
    for path in sorted(corpus_dir.glob("*.md")):
        if path.name == README_NAME or not path.is_file():
            continue

        prefix, separator, _ = path.stem.partition(COLLECTION_SEPARATOR)
        if not separator or prefix not in FACTORY_KNOWLEDGE_COLLECTIONS:
            raise FactoryCorpusError(
                f"语料文件名必须为 <集合名>{COLLECTION_SEPARATOR}<名称>.md：{path.name}；"
                f"可用集合：{', '.join(FACTORY_KNOWLEDGE_COLLECTIONS)}"
            )

        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise FactoryCorpusError(f"语料正文为空：{path.name}")

        documents.append(
            FactoryCorpusDocument(
                path=path,
                collection=prefix,
                # 来源名只由文件名决定，正文改动不影响替换语义。
                source=f"factory/{path.name}",
                title=_title_from_markdown(text, path.stem),
                text=text,
            )
        )

    if not documents:
        raise FactoryCorpusError(f"出厂语料目录里没有可装载的 Markdown：{corpus_dir}")
    return documents


async def load_factory_corpus(
    collection: Optional[str] = None,
    corpus_dir: Path = DEFAULT_CORPUS_DIR,
) -> dict[str, int]:
    """把语料逐篇索引到出厂集合，返回每个集合写入的分块数。

    ``collection`` 非空时忽略文件名前缀，把全部语料写入该集合；它必须是
    ``FACTORY_KNOWLEDGE_COLLECTIONS`` 中的一个。写入使用
    ``KnowledgeIndexer.index_text``：同一 ``(集合, 来源)`` 再进来一次是替换。
    """

    settings = get_settings()
    if not settings.embedding.enabled:
        raise FactoryCorpusError(
            "embedding.enabled=false，无法建立向量索引；"
            "请在 config.yaml 中启用 embedding 后重试"
        )

    target_collection = (collection or "").strip() or None
    if (
        target_collection is not None
        and target_collection not in FACTORY_KNOWLEDGE_COLLECTIONS
    ):
        raise FactoryCorpusError(
            f"未知的出厂集合：{target_collection}；"
            f"可用集合：{', '.join(FACTORY_KNOWLEDGE_COLLECTIONS)}"
        )

    documents = discover_factory_corpus(corpus_dir)

    from ..storage.maintenance.report import require_database_contract

    await require_database_contract()

    indexer = KnowledgeIndexer()
    counts: dict[str, int] = {}
    for document in documents:
        target = target_collection or document.collection
        count = await indexer.index_text(
            document.text,
            source=document.source,
            collection=target,
            metadata={
                "title": document.title,
                "corpus": "factory",
                "path": document.path.relative_to(corpus_dir).as_posix(),
            },
        )
        if count == 0:
            raise FactoryCorpusError(f"没有为 {document.source} 生成任何分块")
        counts[target] = counts.get(target, 0) + count
    return counts
