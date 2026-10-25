from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest

from travel_agent.tools import access, content, execution, react
from travel_agent.config import Settings
from travel_agent.tools.knowledge_results import knowledge_tool_documents
from travel_agent.knowledge.source_records import rag_chunk_source_records
from travel_agent.tools import builtin_tools
from travel_agent.tools.governance import build_tool_execution_envelope
from travel_agent.tools.registry import ToolRegistry


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def astream_with_tools(self, messages, schemas):
        self.requests.append(deepcopy(messages))
        yield {"type": "finish", **next(self.responses)}


@pytest.fixture
def knowledge(monkeypatch):
    from travel_agent.config import loader
    from travel_agent.knowledge import retriever

    monkeypatch.setattr(loader, "_effective", type("Effective", (), {
        "settings": Settings(embedding={"enabled": True}, rerank={"enabled": False}),
    })())
    search = AsyncMock(return_value=[{
        "content": "园林参观资料" * 100, "source": "https://example.org/guide",
    }])
    monkeypatch.setattr(retriever.HybridRetriever, "retrieve", search)
    from travel_agent.memory import compaction
    compactor = Mock()
    compactor.compact = AsyncMock(return_value=None)
    monkeypatch.setattr(compaction, "get_compaction_service", lambda: compactor)
    registry = ToolRegistry()
    monkeypatch.setattr(builtin_tools, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(execution, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(react, "get_tool_registry", lambda: registry)
    builtin_tools.register_builtin_tools()
    tools = [tool for tool in registry.get_tools_as_schemas()
             if tool["schema"]["function"]["name"] == "knowledge_search"]
    return search, tools


def call(query, **arguments):
    return {"content": "", "tool_calls": [{
        "id": query, "name": "knowledge_search",
        "arguments": {"query": query, "collection": "travel_knowledge", **arguments},
    }]}


async def run(responses, tools):
    llm = ScriptedLLM(responses)
    result = await react.streaming_react_loop(
        llm, [{"role": "user", "content": "苏州建议"}], tools, None,
        "destination_researcher", max_iterations=4,
    )
    return llm, result


async def test_agent_decides_whether_and_what_to_search(knowledge):
    search, tools = knowledge
    await run([{"content": "一般建议", "tool_calls": []}], tools)
    search.assert_not_called()
    llm, result = await run([
        call("园林"), call("老街"), {"content": "合理建议", "tool_calls": []},
    ], tools)
    assert [item.args[0] for item in search.await_args_list] == ["园林", "老街"]
    assert all(item.kwargs["collection"] == "u_local__travel_knowledge"
               for item in search.await_args_list)
    docs = knowledge_tool_documents(result.tool_results)
    assert docs and len(docs[0]["content"]) > 400
    assert docs[0]["content"] in str(llm.requests[-1])
    sources = rag_chunk_source_records(docs)
    assert docs[0]["source_record_id"] in sources
    restored = knowledge_tool_documents(deepcopy(result.tool_results))
    assert restored == docs
    assert rag_chunk_source_records(restored).keys() == sources.keys()
    quarantined = deepcopy(result.tool_results)
    for envelope in quarantined:
        envelope["metadata"]["quarantine_result"] = True
    assert knowledge_tool_documents(quarantined) == []


@pytest.mark.parametrize("failure", [False, True])
async def test_empty_or_failed_search_does_not_end_agent_loop(knowledge, failure):
    search, tools = knowledge
    search.return_value = []
    if failure:
        search.side_effect = RuntimeError("private database detail")
    llm, result = await run([call("园林"), {"content": "仍可给一般建议", "tool_calls": []}], tools)
    assert result.content == "仍可给一般建议"
    assert len(llm.requests) == 2
    assert "private database detail" not in str(llm.requests[-1])
    assert "不得详细回答" not in str(llm.requests[-1])


async def test_extra_identity_and_physical_collection_rejected(knowledge):
    search, tools = knowledge
    for arguments in ({"user_id": "other"}, {"collection": "u_other__travel_knowledge"}):
        _, result = await run([call("园林", **arguments), {"content": "建议", "tool_calls": []}], tools)
        assert result.tool_results[0]["status"] in {"blocked", "failed"}
    search.assert_not_called()


async def test_disabled_tool_not_exposed_and_direct_call_denied(knowledge, monkeypatch):
    from travel_agent.config import loader

    search, tools = knowledge
    monkeypatch.setattr(loader, "_effective", type("Effective", (), {
        "settings": Settings(embedding={"enabled": False}),
    })())
    assert not access.filter_tools_for_agent(tools, "destination_researcher")
    result = await execution.execute_tool("knowledge_search", {"query": "园林"}, tools)
    assert result["status"] in {"blocked", "failed"}
    with pytest.raises(RuntimeError, match="关闭"):
        await builtin_tools.knowledge_search("园林")
    search.assert_not_called()


async def test_checkpoint_replay_keeps_fragments_and_rechecks_authorization(knowledge, monkeypatch):
    from travel_agent.config import loader
    from travel_agent.storage.worker_journal_store import InMemoryWorkerJournalStore
    from travel_agent.runtime.journal import WorkerJournal, current_worker_journal

    search, tools = knowledge
    journal = WorkerJournal(InMemoryWorkerJournalStore(), "run", "scope", 0, {}, None)
    token = current_worker_journal.set(journal)
    try:
        _, original = await run([call("园林"), {"content": "建议", "tool_calls": []}], tools)
        llm, restored = await run([], tools)
        assert llm.requests == []
        assert knowledge_tool_documents(restored.tool_results) == knowledge_tool_documents(original.tool_results)
        assert search.await_count == 1
        monkeypatch.setattr(loader, "_effective", type("Effective", (), {
            "settings": Settings(embedding={"enabled": False}),
        })())
        with pytest.raises(RuntimeError, match="not authorized"):
            await run([], tools)
        journal.tool_cursor = 0
        denied = await execution.execute_tool("knowledge_search", {"query": "园林", "collection": "travel_knowledge"}, tools)
        assert denied["status"] == "blocked"
        assert search.await_count == 1
    finally:
        current_worker_journal.reset(token)


async def test_fast_answer_uses_real_loop_and_passes_tool_evidence(knowledge, monkeypatch):
    import asyncio
    from travel_agent.agents.fast_answer import node
    from travel_agent.planning.state import TravelAgentState
    from travel_agent.conversation.answer_presentation import OutputGuard

    _, tools = knowledge
    llm = ScriptedLLM([call("园林"), {"content": "建议分两天参观园林。", "tool_calls": []}])
    monkeypatch.setattr(node, "get_model_router", Mock())
    monkeypatch.setattr(node, "llm_for_task", Mock(return_value=llm))
    monkeypatch.setattr(node, "build_run_constraint_pack", AsyncMock(return_value={}))
    monkeypatch.setattr(node, "_build_realtime_tool_context", AsyncMock(return_value={}))
    monkeypatch.setattr(node, "get_available_tools", AsyncMock(return_value=tools))
    guard = Mock(wraps=OutputGuard())
    monkeypatch.setattr(node, "OutputGuard", lambda: guard)
    queue = asyncio.Queue()
    result = await node.fast_answer_node(
        TravelAgentState(user_query="苏州适合游览几天？"),
        {"configurable": {"stream_queue": queue}},
    )
    assert result["is_completed"]
    assert "建议分两天" in result["messages"][0].content
    kwargs = guard.check.call_args.kwargs
    assert kwargs["retrieved_docs"]
    assert kwargs["evidence_records"][0]["source_type"] != "official"
    assert len(llm.requests) == 2
    assert "sanitized_result" not in result["messages"][0].content


@pytest.mark.parametrize("scenario", ["exception", "partial", "tool_failure", "limit"])
async def test_fast_answer_never_completes_a_nonfinal_real_loop(knowledge, monkeypatch, scenario):
    import asyncio
    from travel_agent.agents.fast_answer import node
    from travel_agent.planning.state import TravelAgentState

    search, tools = knowledge

    class Model:
        calls = 0

        async def astream_with_tools(self, messages, schemas):
            self.calls += 1
            if scenario == "partial":
                yield {"type": "text_delta", "content": "我再查一下"}
                return
            if scenario == "exception" or scenario == "tool_failure" and self.calls > 1:
                raise RuntimeError("fixture-provider-failure")
            yield {"type": "finish", **call("园林"), "content": "我再查一下"}

    model = Model()
    monkeypatch.setattr(node, "get_model_router", Mock())
    monkeypatch.setattr(node, "llm_for_task", Mock(return_value=model))
    monkeypatch.setattr(node, "build_run_constraint_pack", AsyncMock(return_value={}))
    monkeypatch.setattr(node, "_build_realtime_tool_context", AsyncMock(return_value={}))
    monkeypatch.setattr(node, "get_available_tools", AsyncMock(return_value=tools))
    queue = asyncio.Queue()
    outcome = "incomplete_stream" if scenario == "partial" else "iteration_limit" if scenario == "limit" else "model_failed"
    with pytest.raises(RuntimeError, match=outcome):
        await node.fast_answer_node(
            TravelAgentState(user_query="苏州适合游览几天？"),
            {"configurable": {"stream_queue": queue}},
        )
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert not [event for event in events if event[0] == "token"]
    assert model.calls == (3 if scenario == "limit" else 2 if scenario == "tool_failure" else 1)
    assert search.await_count == (3 if scenario == "limit" else 1 if scenario == "tool_failure" else 0)


async def test_hybrid_failure_is_distinct_from_empty_and_does_not_leak(knowledge, monkeypatch):
    from travel_agent.knowledge.retriever import HybridRetriever

    _, tools = knowledge
    vector = AsyncMock(side_effect=RuntimeError("u_private__secret credential"))
    lexical = AsyncMock(return_value=[])
    monkeypatch.setattr(HybridRetriever, "_vector_retrieve", vector)
    monkeypatch.setattr(HybridRetriever, "_lexical_retrieve", lexical)
    retriever = HybridRetriever()
    partial = await retriever._hybrid_retrieve("园林", "private", 3, None)
    assert partial == [] and partial.failures == [{"scope": "vector", "error": "RuntimeError"}]
    lexical.side_effect = RuntimeError("private credential")
    with pytest.raises(RuntimeError, match="均失败"):
        await retriever._hybrid_retrieve("园林", "private", 3, None)
    assert vector.await_count == lexical.await_count == 2
    assert tools


async def test_single_query_and_one_rerank_across_collections(knowledge, monkeypatch):
    from travel_agent.knowledge import retrieval_pipeline
    from travel_agent.knowledge.retriever import RetrievalDocuments

    _, _tools = knowledge
    retrieve = AsyncMock(side_effect=[
        RetrievalDocuments([{"content": "资料", "source": "fixture"}],
                           failures=[{"scope": "vector", "error": "RuntimeError"}]),
        RuntimeError("u_private__secret password"),
    ])
    reranker = Mock()
    reranker.rerank = AsyncMock(return_value=[{"content": "精排资料"}])
    monkeypatch.setattr(retrieval_pipeline, "get_reranker", lambda: reranker)
    outcome = await retrieval_pipeline.retrieve_for_query(
        "原始查询", retriever=type("Retriever", (), {"retrieve": retrieve})(),
        collections=["destinations", "travel_tips"], top_k=2, use_rerank=True,
    )
    assert retrieve.await_count == 2
    assert all(item.args == ("原始查询",) for item in retrieve.await_args_list)
    assert all(item.kwargs["rerank"] is False for item in retrieve.await_args_list)
    reranker.rerank.assert_awaited_once()
    assert outcome.reranked and len(outcome.failures) == 2
    assert "password" not in str(outcome.failures)


async def test_packet_citations_use_only_whole_visible_fragments(knowledge, monkeypatch):
    import json
    from travel_agent.planning.research.output.sources import _ground_rag_chunk_sources

    _, tools = knowledge
    _, result = await run([call("园林"), {"content": "建议", "tool_calls": []}], tools)
    envelope = result.tool_results[0]
    doc = envelope["sanitized_result"]["documents"][0]
    envelope["sanitized_result"]["documents"] = [
        {**doc, "content": (str(index) + "园林资料") * 150} for index in range(5)
    ]
    monkeypatch.setattr(content, "_TOOL_CONTENT_CHAR_LIMIT", 4000)
    shown = content.compact_tool_content_for_model(envelope)
    assert len(shown) <= 4000
    docs = knowledge_tool_documents([envelope])
    assert 0 < len(docs) < 5
    assert docs == json.loads(shown)["sanitized_result"]["documents"]
    sources = rag_chunk_source_records(docs)
    source_id = next(iter(sources))
    payload = {"source_records": [{"source_record_id": source_id, "source_kind": "rag_chunk"}],
               "fact_assertions": [{"source_links": [{"source_record_id": source_id}]}]}
    _ground_rag_chunk_sources(payload, sources, expected_worker="destination_researcher")
    assert payload["source_records"][0]["snapshot"]["content"] == docs[0]["content"]
    assert docs[0]["content"] in shown
    _ground_rag_chunk_sources(payload, {}, expected_worker="destination_researcher")
    assert payload["source_records"] == []


def test_compact_generic_results_keep_web_and_train_fields():
    envelope = build_tool_execution_envelope(
        tool_name="fixture", arguments={}, status="success", source="builtin",
        result={"results": [{
            "title": "园林开放信息", "url": "https://example.org/timetable",
            "snippet": "园林参观正文" * 40, "train_code": "G123",
            "departure_time": "09:30", "api_key": "do-not-leak",
        }]},
    )
    text = content.compact_tool_content_for_model(envelope)
    assert "园林参观正文" in text
    assert "https://example.org/timetable" in text
    assert "G123" in text and "09:30" in text
    assert "do-not-leak" not in text
