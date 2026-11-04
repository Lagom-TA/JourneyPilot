"""真实规划图里的多轮理解回合。

覆盖：强模型先查后问、回答进入后续轮次与需求文字、错误凭据不消费状态、
到达提问上限显式失败、身份补写 Run 行，以及方案门读到含问答的需求。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from travel_agent.planning.graph import build_travel_workflow
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.journal import current_execution_lease
from travel_agent.tools.exposure import ToolExposurePlan
from travel_agent.tools.gateway_contracts import ToolManifest
from travel_agent.tools.registry import ToolRegistry


def place(name, place_id):
    return {"place_id": place_id, "provider": "osm", "kind": "city", "name": name, "display_name": name, "country_code": "CN", "latitude": 36.07, "longitude": 120.38, "admin_path": []}


IDENTITY = {
    "origin": {**place("上海", "city_shanghai"), "latitude": 31.23, "longitude": 121.47},
    "destinations": [place("青岛", "city_qingdao")],
    "start_date": "2026-11-05", "end_date": "2026-11-07",
    "party": {"adults": 2, "children": 0, "elderly_companions": False, "accessibility_required": False},
    "style": {"primary": "休闲", "secondary_interests": [], "source": "current"},
}


class UnderstandingModel:
    """脚本化的强模型：先查一次，再问；回答后再查一次，然后给出身份。"""

    capabilities = SimpleNamespace(supports_json_schema=False)

    def __init__(self):
        self.calls = 0
        self.messages_log = []

    async def ainvoke_with_tools_events(self, messages, tools):
        self.calls += 1
        self.messages_log.append([dict(message) for message in messages])
        has_tool_result = any(message.get("role") == "tool" for message in messages)
        has_answer = any(
            message.get("role") == "user"
            and str(message.get("content") or "").startswith("用户回答：")
            for message in messages
        )
        if not has_tool_result and not has_answer:
            # 第一轮：先查后问。
            yield {"type": "finish", "content": "", "tool_calls": [
                {"id": "search-1", "name": "free_web_search", "arguments": {"query": "青岛 11 月 海边"}},
            ]}
            return
        if not has_answer:
            # 查询结果已回到同一模型：提出第一轮问题。
            yield {"type": "finish", "content": json.dumps({
                "action": "ask",
                "trip_identity": IDENTITY,
                "requirements": "从上海去青岛放松几天",
                "questions": [{"id": "pace", "question": "想慢慢逛还是排满？", "kind": "single",
                               "options": [{"id": "slow", "label": "慢慢逛"}, {"id": "full", "label": "排满"}]}],
            }, ensure_ascii=False), "tool_calls": []}
            return
        if self.calls >= 4:
            # 回答后的第二次查询已完成：给出身份。
            yield {"type": "finish", "content": json.dumps({
                "action": "ready",
                "trip_identity": IDENTITY,
                "requirements": "从上海去青岛放松几天；想慢慢逛还是排满？：慢慢逛",
            }, ensure_ascii=False), "tool_calls": []}
            return
        # 回答后再查一次。
        yield {"type": "finish", "content": "", "tool_calls": [
            {"id": "search-2", "name": "free_web_search", "arguments": {"query": "青岛 慢节奏 景点"}},
        ]}

    async def ainvoke(self, messages, **kwargs):
        system = str(messages[0].get("content", ""))
        if "研究协调员" in system:
            payload = json.loads(messages[-1]["content"])
            self.plan_request = payload
            return json.dumps({"summary": "围绕海边与慢节奏安排青岛。"}, ensure_ascii=False)
        raise AssertionError("多轮理解测试不应调用其他模型路径")


class LeaseStore:
    async def get(self, run_id):
        return SimpleNamespace(lease_token="lease", lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))


@pytest.fixture
async def offline_graph(monkeypatch):
    from travel_agent.planning.requirements.understanding import agent as understanding_agent
    from travel_agent.planning.research import research_plan_node
    from travel_agent.tools import execution, react
    from tests.support.memory_stores import InMemoryTripRunStore, InMemoryWorkerJournalStore

    model = UnderstandingModel()
    for module in (understanding_agent, research_plan_node):
        monkeypatch.setattr(module, "get_model_router", lambda: object())
        monkeypatch.setattr(module, "llm_for_task", lambda *args, **kwargs: model)

    registry = ToolRegistry()
    searches = []

    async def search(query):
        searches.append(query)
        return {"success": True, "query": query, "provider": "fixture",
                "results": [{"title": "青岛海边", "snippet": "11 月适合散步"}]}

    registry.register(
        "free_web_search", "联网检索", {"type": "object", "properties": {"query": {"type": "string"}}},
        search, manifest=ToolManifest(tool_name="free_web_search"),
    )
    monkeypatch.setattr(execution, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(react, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(react, "apply_tool_exposure", lambda tools, name: ToolExposurePlan(False, name, tuple(item["schema"] for item in tools), "", 0, 0, len(tools), len(tools)))

    async def available():
        return registry.get_tools_as_schemas()

    monkeypatch.setattr(understanding_agent, "get_available_tools", available)

    runs = InMemoryTripRunStore()
    from travel_agent.runtime.run_contracts import TripRunStatus

    await runs.create_run(
        run_id="understanding-flow", session_id="understanding-flow",
        user_id="local", mode="deep",
    )
    await runs.transition_status("understanding-flow", TripRunStatus.RUNNING)
    graph = build_travel_workflow().compile(checkpointer=InMemorySaver())
    journal = InMemoryWorkerJournalStore()
    config = {
        "configurable": {
            "thread_id": "understanding-flow",
            "plan_gate_enabled": True,
            "run_execution_store": LeaseStore(),
            "trip_run_store": runs,
            "worker_journal_store": journal,
        }
    }
    yield SimpleNamespace(model=model, searches=searches, graph=graph, config=config, runs=runs, journal=journal)


def _initial_state():
    return TravelAgentState(
        run_id="understanding-flow",
        session_id="understanding-flow",
        user_query="从上海去青岛放松几天",
        controlled_trip_identity=IDENTITY,
    )


async def test_understanding_rounds_reach_the_plan_gate_with_answers_in_requirements(offline_graph):
    graph, config = offline_graph.graph, offline_graph.config
    token = current_execution_lease.set("lease")
    try:
        first = await graph.ainvoke(_initial_state(), config)
        gate = first["__interrupt__"][0].value
        assert gate["gate"] == "understanding"
        assert gate["questions"][0]["id"] == "pace"
        assert offline_graph.searches == ["青岛 11 月 海边"]

        # 错误凭据与缺答不会消费状态，问题原样保留。
        stale = await graph.ainvoke(
            Command(resume={"action": "answer", "approval_token": "wrong",
                            "answers": [{"question_id": "pace", "text": "慢慢逛"}]}),
            config,
        )
        assert stale["__interrupt__"][0].value["approval_token"] == gate["approval_token"]
        partial = await graph.ainvoke(
            Command(resume={"action": "answer", "approval_token": gate["approval_token"], "answers": []}),
            config,
        )
        assert partial["__interrupt__"][0].value["approval_token"] == gate["approval_token"]
        assert offline_graph.model.calls == 2  # 先查后问两步，坏答案不重跑模型

        answer = await graph.ainvoke(
            Command(resume={"action": "answer", "approval_token": gate["approval_token"],
                            "answers": [{"question_id": "pace", "text": "慢慢逛"}]}),
            config,
        )
        plan_gate = answer["__interrupt__"][0].value
    finally:
        current_execution_lease.reset(token)

    assert plan_gate["gate"] == "plan"
    assert "海边" in plan_gate["plan_text"]
    # 回答后再查：第二轮模型调用先发起了一次新检索。
    assert offline_graph.searches == ["青岛 11 月 海边", "青岛 慢节奏 景点"]
    understanding_scopes = [
        scope for run_id, scope in offline_graph.journal.rows
        if run_id == "understanding-flow" and scope.startswith("understanding_agent:")
    ]
    assert len(understanding_scopes) == 2
    _, budget = await offline_graph.journal.load("understanding-flow", "__tool_budget__")
    assert budget["calls"] == 2
    # 模型确实收到了用户的回答，不会重复询问已解决的问题。
    answered_context = offline_graph.model.messages_log[-2]
    assert any(
        message.get("role") == "user"
        and str(message.get("content") or "").startswith("用户回答：")
        and "慢慢逛" in str(message.get("content"))
        for message in answered_context
    )
    # 身份由理解产出并写回 Run 行，工作台刷新可直接读取。
    run = await offline_graph.runs.get_run("understanding-flow")
    assert run.controlled_trip_identity["destinations"][0]["name"] == "青岛"
    # 方案请求读到含问答的需求文字。
    assert "想慢慢逛还是排满？：慢慢逛" in offline_graph.model.plan_request["整理后的旅行要求"]
    assert "从上海去青岛放松几天" in offline_graph.model.plan_request["整理后的旅行要求"]


async def test_invalid_identity_is_repaired_with_worker_journal(offline_graph, monkeypatch):
    from copy import deepcopy

    from travel_agent.planning.requirements.understanding import agent as understanding_agent

    class RepairModel(UnderstandingModel):
        async def ainvoke_with_tools_events(self, messages, tools):
            self.calls += 1
            self.messages_log.append(deepcopy(messages))
            identity = deepcopy(IDENTITY)
            if self.calls == 1:
                identity["party"]["adults"] = -1
            yield {
                "type": "finish",
                "content": json.dumps({"action": "ready", "trip_identity": identity, "requirements": "从上海去青岛放松几天"}, ensure_ascii=False),
                "tool_calls": [],
            }

    model = RepairModel()
    monkeypatch.setattr(understanding_agent, "llm_for_task", lambda *args, **kwargs: model)
    token = current_execution_lease.set("lease")
    try:
        result = await offline_graph.graph.ainvoke(_initial_state(), offline_graph.config)
    finally:
        current_execution_lease.reset(token)

    assert result["__interrupt__"][0].value["gate"] == "plan"
    assert model.calls == 2
    assert any("请修正本轮输出格式" in str(message.get("content")) for message in model.messages_log[1])
    payload = next(iter(offline_graph.journal.rows.values()))[1]
    assert payload["understanding_react_0"]["done"]
    assert payload["understanding_react_1"]["done"]


async def test_understanding_repairs_invalid_output_and_recovers_each_attempt(offline_graph, monkeypatch):
    from travel_agent.planning.nodes import NODE_UNDERSTANDING_AGENT
    from travel_agent.planning.recovery import invocation_scope, with_worker_recovery
    from travel_agent.planning.requirements.understanding import agent as understanding_agent

    class RepairModel:
        def __init__(self):
            self.requests = []
            self.interrupted = False

        async def ainvoke_with_tools_events(self, messages, tools):
            self.requests.append([dict(message) for message in messages])
            if len(self.requests) == 1:
                yield {"type": "finish", "content": "不是 JSON", "tool_calls": []}
            elif not self.interrupted:
                self.interrupted = True
                raise asyncio.CancelledError()
            else:
                yield {"type": "finish", "content": json.dumps({
                    "action": "ready", "trip_identity": IDENTITY,
                    "requirements": "从上海去青岛放松几天",
                }, ensure_ascii=False), "tool_calls": []}

    model = RepairModel()
    monkeypatch.setattr(understanding_agent, "llm_for_task", lambda *args, **kwargs: model)
    state = _initial_state()
    config = offline_graph.config
    recovered = with_worker_recovery(NODE_UNDERSTANDING_AGENT, understanding_agent.understanding_agent_node)
    with pytest.raises(asyncio.CancelledError):
        await recovered(state, config)

    store = config["configurable"]["worker_journal_store"]
    _, payload = await store.load(state.run_id, invocation_scope(state, NODE_UNDERSTANDING_AGENT, config))
    assert payload["understanding_react_0"]["done"] is True
    assert payload["understanding_react_1"]["phase"] == "request_started"

    result = await recovered(state, config)
    assert result["controlled_trip_identity"]["destinations"][0]["name"] == "青岛"
    assert len(model.requests) == 3
    assert "请修正本轮输出格式" in model.requests[-1][-1]["content"]
    assert await recovered(state, config) == result
    assert len(model.requests) == 3


async def test_understanding_repair_recovers_tool_without_repeating_it(offline_graph, monkeypatch):
    from travel_agent.planning.nodes import NODE_UNDERSTANDING_AGENT
    from travel_agent.planning.recovery import invocation_scope, with_worker_recovery
    from travel_agent.planning.requirements.understanding import agent as understanding_agent
    from travel_agent.tools import react

    class RepairModel:
        def __init__(self):
            self.calls = 0

        async def ainvoke_with_tools_events(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                yield {"type": "finish", "content": "不是 JSON", "tool_calls": []}
            elif self.calls == 2:
                yield {"type": "finish", "content": "", "tool_calls": [
                    {"id": "repair-search", "name": "free_web_search", "arguments": {"query": "青岛 海边"}},
                ]}
            else:
                yield {"type": "finish", "content": json.dumps({
                    "action": "ready", "trip_identity": IDENTITY,
                    "requirements": "从上海去青岛放松几天",
                }, ensure_ascii=False), "tool_calls": []}

    model = RepairModel()
    monkeypatch.setattr(understanding_agent, "llm_for_task", lambda *args, **kwargs: model)
    original_check = react.check_cancel_requested

    def interrupt_after_tool(node):
        if offline_graph.searches:
            raise asyncio.CancelledError()
        original_check(node)

    monkeypatch.setattr(react, "check_cancel_requested", interrupt_after_tool)
    state = _initial_state()
    config = offline_graph.config
    recovered = with_worker_recovery(NODE_UNDERSTANDING_AGENT, understanding_agent.understanding_agent_node)
    with pytest.raises(asyncio.CancelledError):
        await recovered(state, config)
    assert offline_graph.searches == ["青岛 海边"]

    store = config["configurable"]["worker_journal_store"]
    _, payload = await store.load(state.run_id, invocation_scope(state, NODE_UNDERSTANDING_AGENT, config))
    assert payload["understanding_react_1"]["next_tool"] == 1
    monkeypatch.setattr(react, "check_cancel_requested", original_check)
    result = await recovered(state, config)
    assert result["controlled_trip_identity"]["destinations"][0]["name"] == "青岛"
    assert offline_graph.searches == ["青岛 海边"]
    assert model.calls == 3


async def test_always_asking_model_fails_visibly_at_the_round_cap(offline_graph, monkeypatch):
    from travel_agent.planning.requirements.understanding import agent as understanding_agent

    class EndlessQuestions(UnderstandingModel):
        async def ainvoke_with_tools_events(self, messages, tools):
            yield {"type": "finish", "content": json.dumps({
                "action": "ask",
                "trip_identity": IDENTITY,
                "requirements": "从上海去青岛放松几天",
                "questions": [{"id": f"q{self.calls}", "question": "还有吗？", "kind": "single",
                               "options": [{"id": "a", "label": "A"}]}],
            }, ensure_ascii=False), "tool_calls": []}
            self.calls += 1

    monkeypatch.setattr(understanding_agent, "llm_for_task", lambda *args, **kwargs: EndlessQuestions())
    graph, config = offline_graph.graph, offline_graph.config
    token = current_execution_lease.set("lease")
    try:
        state = _initial_state()
        for _ in range(understanding_agent.UNDERSTANDING_MAX_ROUNDS):
            result = await graph.ainvoke(state, config)
            gate = result["__interrupt__"][0].value
            assert gate["gate"] == "understanding"
            state = Command(resume={
                "action": "answer",
                "approval_token": gate["approval_token"],
                "answers": [{"question_id": gate["questions"][0]["id"], "text": "都可以"}],
            })
        with pytest.raises(understanding_agent.UnderstandingFailed, match="提问上限"):
            await graph.ainvoke(state, config)
    finally:
        current_execution_lease.reset(token)


@pytest.mark.parametrize("missing", ["dates", "destination"])
async def test_automatic_questions_and_place_retries_respect_the_round_cap(
    offline_graph, monkeypatch, missing
):
    from travel_agent.planning.requirements.understanding import agent as understanding_agent

    class IncompleteModel(UnderstandingModel):
        async def ainvoke_with_tools_events(self, messages, tools):
            identity = dict(IDENTITY)
            if missing == "dates":
                identity.update(start_date=None, end_date=None)
            else:
                identity["destinations"] = []
            yield {"type": "finish", "content": json.dumps({
                "action": "ready",
                "trip_identity": identity,
                "requirements": "从上海去青岛放松几天",
            }, ensure_ascii=False), "tool_calls": []}

    monkeypatch.setattr(understanding_agent, "llm_for_task", lambda *args, **kwargs: IncompleteModel())
    graph, config = offline_graph.graph, offline_graph.config
    token = current_execution_lease.set("lease")
    try:
        state = _initial_state()
        for _ in range(understanding_agent.UNDERSTANDING_MAX_ROUNDS):
            result = await graph.ainvoke(state, config)
            gate = result["__interrupt__"][0].value
            assert gate["gate"] == "understanding"
            decision = {"approval_token": gate["approval_token"]}
            if missing == "dates":
                decision.update(action="answer", answers=[
                    {"question_id": "travel_dates", "text": "玩三天"}
                ])
            else:
                decision["action"] = "retry"
            state = Command(resume=decision)
        with pytest.raises(understanding_agent.UnderstandingFailed, match="上限"):
            await graph.ainvoke(state, config)
    finally:
        current_execution_lease.reset(token)
