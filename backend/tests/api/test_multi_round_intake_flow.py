"""真实规划图里的多轮理解回合。

覆盖：强模型先查后问、回答进入后续轮次与需求文字、错误凭据不消费状态、
到达提问上限显式失败、身份补写 Run 行，以及方案门读到含问答的需求。
"""

from __future__ import annotations

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
                "questions": [{"id": "pace", "question": "想慢慢逛还是排满？", "kind": "single",
                               "options": [{"id": "slow", "label": "慢慢逛"}, {"id": "full", "label": "排满"}]}],
            }, ensure_ascii=False), "tool_calls": []}
            return
        if self.calls >= 4:
            # 回答后的第二次查询已完成：给出身份。
            yield {"type": "finish", "content": json.dumps({
                "action": "ready",
                "trip_identity": IDENTITY,
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
            return json.dumps({
                "summary": "围绕海边与慢节奏安排青岛。",
                "destination_task": "调查青岛适合慢游的海边候选。",
                "transport_task": "安排上海到青岛的往返交通。",
                "accommodation_task": "研究靠近海边的住宿。",
                "itinerary_task": "把海边与休息安排进两天。",
            }, ensure_ascii=False)
        raise AssertionError("多轮理解测试不应调用其他模型路径")


class LeaseStore:
    async def get(self, run_id):
        return SimpleNamespace(lease_token="lease", lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))


@pytest.fixture
async def offline_graph(monkeypatch):
    from travel_agent.planning.requirements.understanding import agent as understanding_agent
    from travel_agent.planning.research import research_plan_node
    from travel_agent.tools import execution, react
    from tests.support.memory_stores import InMemoryTripRunStore

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

    async def available(_selected):
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
    config = {
        "configurable": {
            "thread_id": "understanding-flow",
            "plan_gate_enabled": True,
            "run_execution_store": LeaseStore(),
            "trip_run_store": runs,
        }
    }
    yield SimpleNamespace(model=model, searches=searches, graph=graph, config=config, runs=runs)


def _initial_state():
    return TravelAgentState(
        run_id="understanding-flow",
        session_id="understanding-flow",
        user_query="从上海去青岛放松几天",
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
    assert "想慢慢逛还是排满？：慢慢逛" in offline_graph.model.plan_request["用户需求与回答"]
    assert "从上海去青岛放松几天" in offline_graph.model.plan_request["用户需求与回答"]


async def test_always_asking_model_fails_visibly_at_the_round_cap(offline_graph, monkeypatch):
    from travel_agent.planning.requirements.understanding import agent as understanding_agent

    class EndlessQuestions(UnderstandingModel):
        async def ainvoke_with_tools_events(self, messages, tools):
            yield {"type": "finish", "content": json.dumps({
                "action": "ask",
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
