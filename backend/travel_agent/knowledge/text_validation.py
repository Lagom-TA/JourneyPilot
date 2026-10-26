"""知识入库前的正文可用性检查。"""

from travel_agent.knowledge.sources.document_parse import MIN_INDEXABLE_CHARS
from travel_agent.utils.user_text import content_length


class TextNotIndexable(ValueError):
    code = "no_indexable_text"
    message = "没有可索引的正文（可能是空文件或扫描版 PDF）"


def require_indexable_text(text: str) -> str:
    if content_length(text) < MIN_INDEXABLE_CHARS:
        raise TextNotIndexable(TextNotIndexable.message)
    return text
