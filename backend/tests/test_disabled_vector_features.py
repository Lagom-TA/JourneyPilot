from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from travel_agent.config import Settings


@pytest.fixture
def disabled_vectors(monkeypatch):
    from travel_agent.config import loader

    settings = Settings(embedding={"enabled": False})
    monkeypatch.setattr(loader, "_effective", SimpleNamespace(settings=settings))
    return settings


async def test_disabled_memory_search_does_not_compute_embeddings(disabled_vectors, monkeypatch):
    from travel_agent.memory.memory_store import MemoryStore

    embedding = AsyncMock()
    monkeypatch.setattr(MemoryStore, "_compute_embedding", embedding)

    assert await MemoryStore().search_facts("local", "饮食偏好") == []
    embedding.assert_not_called()


async def test_manual_preferences_and_profile_still_load(disabled_vectors, monkeypatch):
    from travel_agent.agents.scope import constraint_normalizer as normalizer
    from travel_agent.entities.state import TravelAgentState

    manual = [{"fact_id": "42", "content": "不要海鲜"}]
    profile = object()
    profile_read = AsyncMock(return_value=profile)
    manual_read = AsyncMock(return_value=manual)
    search = AsyncMock()
    monkeypatch.setattr(normalizer.UserProfileMemory, "get_user_profile", profile_read)
    monkeypatch.setattr(normalizer.MemoryStore, "list_manual_facts", manual_read)
    monkeypatch.setattr(normalizer.MemoryStore, "search_facts", search)
    loaded = await normalizer.load_constraint_sources(TravelAgentState(user_id="local"))
    assert loaded.user_profile is profile
    assert loaded.manual_memory_facts == manual
    assert loaded.memory_facts == []
    assert loaded.missing_layers == loaded.partial_reasons == []
    profile_read.assert_awaited_once_with("local")
    manual_read.assert_awaited_once()
    search.assert_not_called()


async def test_indexing_stops_before_chunking_or_writes(disabled_vectors, monkeypatch):
    from travel_agent.knowledge.indexer import KnowledgeIndexer

    indexer = KnowledgeIndexer()
    split = AsyncMock()
    write = AsyncMock()
    monkeypatch.setattr(indexer, "_split_chunks", split)
    monkeypatch.setattr(indexer, "_write_documents", write)
    monkeypatch.setattr(indexer, "_write_document", write)
    for operation in (
        indexer.index_text("文档正文", "test"),
        indexer.index_documents([{"content": "文档正文", "source": "test"}]),
    ):
        with pytest.raises(RuntimeError, match="embedding.enabled=false"):
            await operation
    split.assert_not_called()
    write.assert_not_called()


async def test_retrieval_stops_before_models_and_database(disabled_vectors, monkeypatch):
    from travel_agent.knowledge import retriever

    search = AsyncMock()
    reranker = Mock()
    monkeypatch.setattr(retriever.HybridRetriever, "_hybrid_retrieve", search)
    monkeypatch.setattr(retriever.HybridRetriever, "_vector_retrieve", search)
    monkeypatch.setattr(retriever, "get_reranker", reranker)
    for use_hybrid in (True, False):
        with pytest.raises(RuntimeError, match="embedding.enabled=false"):
            await retriever.HybridRetriever().retrieve("目的地", use_hybrid=use_hybrid)
    search.assert_not_called()
    reranker.assert_not_called()


def test_disabled_embedding_rejects_a_previously_cached_model(disabled_vectors, monkeypatch):
    from travel_agent.llm import embedder

    cached = Mock()
    build = Mock()
    monkeypatch.setattr(embedder, "_embedder", cached)
    monkeypatch.setattr(embedder, "_build_embedder", build)
    with pytest.raises(RuntimeError, match="embedding.enabled=false"):
        embedder.get_embedder()
    build.assert_not_called()
    assert not cached.mock_calls


async def test_bootstrap_and_health_do_not_read_corpus(disabled_vectors, monkeypatch):
    from travel_agent.api.app import _bootstrap_factory_corpus
    from travel_agent.api.routes.system import _probe_knowledge_corpus
    from travel_agent.knowledge import factory_seed

    seed = AsyncMock()
    count = AsyncMock()
    manifest = Mock()
    monkeypatch.setattr(factory_seed, "ensure_factory_corpus", seed)
    monkeypatch.setattr(factory_seed, "factory_collection_counts", count)
    monkeypatch.setattr(factory_seed, "read_manifest", manifest)
    assert await _bootstrap_factory_corpus() == []
    probe = await _probe_knowledge_corpus()
    assert probe["enabled"] is False
    assert probe["ready"] is False
    assert "配置关闭" in probe["message"]
    seed.assert_not_called()
    count.assert_not_called()
    manifest.assert_not_called()


async def test_fast_answer_continues_without_retrieval(disabled_vectors, monkeypatch):
    from travel_agent.agents.fast_answer import node
    from travel_agent.entities.state import TravelAgentState

    class FakeLLM:
        calls = 0

        async def astream_with_tools(self, messages, schemas):
            self.calls += 1
            assert all(item["function"]["name"] != "knowledge_search" for item in schemas)
            yield {"type": "finish", "content": "建议用两天游览苏州，园林与老街分开安排。", "tool_calls": []}

    llm = FakeLLM()
    monkeypatch.setattr(node, "get_model_router", Mock())
    monkeypatch.setattr(node, "llm_for_task", Mock(return_value=llm))
    monkeypatch.setattr(node, "build_run_constraint_pack", AsyncMock(return_value={}))
    monkeypatch.setattr(node, "_build_realtime_tool_context", AsyncMock(return_value={}))
    from travel_agent.knowledge.retriever import HybridRetriever

    retrieve = AsyncMock(side_effect=AssertionError("retrieval must not run"))
    monkeypatch.setattr(HybridRetriever, "retrieve", retrieve)
    monkeypatch.setattr(node, "get_available_tools", AsyncMock(return_value=[]))

    result = await node.fast_answer_node(TravelAgentState(user_query="苏州适合游览几天？"), {})

    assert result["is_completed"] is True
    assert "建议用两天" in result["messages"][0].content
    assert result["retrieval_summaries"] == []
    assert llm.calls == 1
    retrieve.assert_not_called()


async def test_knowledge_api_rejects_vector_operations_before_io(disabled_vectors, monkeypatch):
    from travel_agent.api.routes import knowledge
    from travel_agent.api.schemas import (
        KnowledgeQueryRequest,
        KnowledgeSourceUpdateRequest,
        KnowledgeUploadRequest,
    )

    components = Mock()
    parse = AsyncMock()
    upload = SimpleNamespace(read=AsyncMock())
    monkeypatch.setattr(knowledge, "get_components", components)
    monkeypatch.setattr(knowledge, "parse_upload", parse)
    for operation in (
        knowledge.index_text(KnowledgeUploadRequest(content="文档正文", source="test")),
        knowledge.query_knowledge(KnowledgeQueryRequest(query="目的地")),
        knowledge.upload_file(upload),
        knowledge.update_source_document(
            "default", KnowledgeSourceUpdateRequest(content="新的文档正文"), source="test"
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await operation
        assert exc.value.status_code == 503
        assert exc.value.detail["code"] == "knowledge_disabled"
    components.assert_not_called()
    parse.assert_not_called()
    upload.read.assert_not_called()
