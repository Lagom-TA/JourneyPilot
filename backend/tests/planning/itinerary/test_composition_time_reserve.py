"""行程组合保留成稿时间，补查超时不冒充完整结果。"""

import asyncio
import json

import pytest

from tests.fixtures.itinerary import itinerary_draft, visit_entry
from tests.fixtures.planning_state import make_planning_state
from tests.fixtures.research_catalog import make_local_transport_packet
from travel_agent.planning.itinerary import composition
from travel_agent.planning.research.transport import followup
from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.storage.worker_journal_store import JournalConflict
from travel_agent.tools import react
from travel_agent.tools.governance import build_tool_execution_envelope
from travel_agent.tools.result import ReactOutcome


def _draft():
    return json.dumps(itinerary_draft([visit_entry()]), ensure_ascii=False)


class _SlowExploration:
    def __init__(self):
        self.cancelled = False
        self.final_messages = None

    async def ainvoke_with_tools_events(self, messages, schemas):
        try:
            yield {"type": "text_delta", "content": '{"days":['}
            await asyncio.sleep(5)
        finally:
            self.cancelled = True

    async def astream(self, messages):
        self.final_messages = list(messages)
        yield _draft()


@pytest.mark.asyncio
async def test_slow_composition_stream_leaves_a_no_tool_final_answer(monkeypatch):
    model = _SlowExploration()
    monkeypatch.setattr(composition, "_remaining_exploration_seconds", lambda: 0.02)
    result = await composition._compose_draft(
        make_planning_state(), "安排行程", model, available_tools=[], tool_context={}
    )
    assert model.cancelled
    assert result.days[0].placements[0].candidate_id == "candidate_visit"
    assert not any(message.get("content") == '{"days":[' for message in model.final_messages)
    assert "不要再调用工具或请求返研" in model.final_messages[-1]["content"]


@pytest.mark.asyncio
async def test_timed_out_tool_preserves_previous_results_and_pairs_tool_messages():
    messages = [{"role": "user", "content": "安排行程"}]
    first = build_tool_execution_envelope(
        tool_name="first", arguments={}, status="success", result={"summary": "已有资料"}
    )
    calls = []

    class Model:
        async def ainvoke_with_tools_events(self, messages, schemas):
            yield {"type": "finish", "content": "", "tool_calls": [
                {"id": "one", "name": "first", "arguments": {}},
                {"id": "two", "name": "slow", "arguments": {}},
                {"id": "three", "name": "never", "arguments": {}},
            ]}

        async def astream(self, messages):
            calls.append(list(messages))
            yield _draft()

    async def good(arguments, call_id):
        return first

    async def slow(arguments, call_id):
        await asyncio.sleep(5)

    def tool(name):
        return {"schema": {"type": "function", "function": {
            "name": name, "description": name, "parameters": {"type": "object", "properties": {}}
        }}, "source": "local", "server_name": None}

    result = await react.streaming_react_loop(
        Model(), messages, [tool("first"), tool("slow"), tool("never")], None,
        "itinerary_planner", local_tool_handlers={"first": good, "slow": slow},
        exploration_remaining=lambda: 0.02,
        final_round_notice="请输出草稿，不要调用工具。",
    )
    assert result.outcome is ReactOutcome.FINAL_ANSWER
    assert result.tool_results[0] == first
    assert result.tool_results[1]["status"] == "failed"
    tool_messages = [item for item in calls[0] if item.get("role") == "tool"]
    assert [item["tool_call_id"] for item in tool_messages] == ["one", "two", "three"]
    assert "not_executed" in tool_messages[-1]["content"]


@pytest.mark.asyncio
async def test_followup_budget_retains_already_verified_routes(monkeypatch):
    packet = make_local_transport_packet(
        "route", origin_place_id="origin", destination_place_id="destination"
    ).model_copy(update={"query_context": {"activation_source": "transport_followup"}})
    state = make_planning_state()
    envelope = build_tool_execution_envelope(
        tool_name="fixture_route", arguments={}, status="success", result={"routes": []}
    )
    calls = []

    async def available():
        return []

    async def fake_react(**kwargs):
        return await react.streaming_react_loop(**kwargs)

    class Model:
        async def ainvoke_with_tools_events(self, messages, schemas):
            if not calls:
                calls.append(1)
                yield {"type": "finish", "content": "", "tool_calls": [
                    {"id": "route", "name": "fixture_route", "arguments": {}}
                ]}
            else:
                await asyncio.sleep(5)
                yield {"type": "finish", "content": "late", "tool_calls": []}

    async def execute(*args, **kwargs):
        return envelope

    monkeypatch.setattr(followup, "get_available_tools", available)
    monkeypatch.setattr(followup, "filter_tools_for_agent", lambda tools, agent: tools)
    monkeypatch.setattr(followup, "get_model_router", lambda: None)
    monkeypatch.setattr(followup, "llm_for_task", lambda *args, **kwargs: Model())
    monkeypatch.setattr(followup, "streaming_react_loop", fake_react)
    monkeypatch.setattr(react, "execute_tool", execute)
    monkeypatch.setattr(
        "travel_agent.planning.research.output.transcript._successful_route_records",
        lambda messages: {"route": (envelope, {}, 0)},
    )
    monkeypatch.setattr(followup, "_route_packet", lambda **kwargs: packet)
    monkeypatch.setattr(followup, "compile_rail_followup_packet", lambda **kwargs: None)

    response, catalog = await followup.research_transport_followup(
        state, question="如何接驳？", arrangement="", max_duration_seconds=0.02,
    )
    assert response["status"] == "failed"
    assert "未完成" in response["sanitized_result"]["summary"]
    assert "route" in catalog.candidate_index()
    assert response["followup_packets"][0]["research_packet_id"] == packet.research_packet_id


@pytest.mark.asyncio
async def test_closing_answer_cannot_accept_an_unfinished_stream(monkeypatch):
    class Model:
        async def astream(self, messages):
            yield _draft()[:20]
            raise RuntimeError("provider stream ended early")

    monkeypatch.setattr(composition, "_remaining_exploration_seconds", lambda: 0.0)
    with pytest.raises(ValueError, match="model_failed"):
        await composition._compose_draft(
            make_planning_state(), "安排行程", Model(), available_tools=[], tool_context={}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RunCancelled("run_test"), JournalConflict("conflict")])
async def test_closing_answer_does_not_hide_control_exceptions(monkeypatch, error):
    class Model:
        async def astream(self, messages):
            raise error
            yield ""

    monkeypatch.setattr(composition, "_remaining_exploration_seconds", lambda: 0.0)
    with pytest.raises(type(error)):
        await composition._compose_draft(
            make_planning_state(), "安排行程", Model(), available_tools=[], tool_context={}
        )
