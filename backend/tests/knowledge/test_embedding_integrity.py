from types import SimpleNamespace

import pytest

from travel_agent.knowledge import indexer
from travel_agent.llm.embedder import OpenAICompatibleEmbedder


def _embedder():
    embedder = OpenAICompatibleEmbedder.__new__(OpenAICompatibleEmbedder)
    embedder._dimensions = 2
    return embedder


def test_compatible_embeddings_follow_input_indexes():
    data = [
        SimpleNamespace(index=1, embedding=[3, 4]),
        SimpleNamespace(index=0, embedding=[1, 2]),
    ]
    assert _embedder()._ordered_vectors(data, 2) == [[1, 2], [3, 4]]


@pytest.mark.parametrize("indexes", [[0], [0, 0], [0, 2]])
def test_compatible_embeddings_reject_missing_or_duplicate_indexes(indexes):
    data = [SimpleNamespace(index=index, embedding=[1, 2]) for index in indexes]
    with pytest.raises(RuntimeError):
        _embedder()._ordered_vectors(data, 2)


async def test_incomplete_embeddings_never_replace_an_existing_document(monkeypatch):
    class IncompleteEmbedder:
        async def embed_batch(self, texts):
            return [[1, 2]]

    def forbidden_database():
        raise AssertionError("向量不完整时不能进入写库事务")

    monkeypatch.setattr(indexer, "get_db_session", forbidden_database)
    service = indexer.KnowledgeIndexer(embedder=IncompleteEmbedder())
    documents = [{"content": "正文", "source": "来源", "chunks": [
        {"content": "第一段"}, {"content": "第二段"},
    ]}]
    with pytest.raises(RuntimeError, match="数量"):
        await service._write_documents(documents, "collection")
