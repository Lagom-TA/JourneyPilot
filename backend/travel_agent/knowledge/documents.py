"""Read original source text without reconstructing it from derived chunks."""

from travel_agent.knowledge.indexer import KnowledgeIndexer


class SourceDocumentUnavailable(LookupError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


async def require_source_document(
    indexer: KnowledgeIndexer, collection: str, source: str
) -> dict:
    document = await indexer.get_document(collection, source)
    if document is not None:
        return document
    if await indexer.count_source_chunks(collection, source) > 0:
        raise SourceDocumentUnavailable(
            "document_text_unavailable", "这篇资料入库时没有留存正文"
        )
    raise SourceDocumentUnavailable("unknown_source", "资料库里没有这一篇")
