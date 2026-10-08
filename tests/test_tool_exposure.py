"""Stable tool definitions, invocation isolation and complete ReAct transcripts."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import pytest

from travel_agent.agents import utils
from travel_agent.config import ToolExposureConfig
from travel_agent.infrastructure.tool_audit_store import InMemoryToolAuditStore
from travel_agent.tools.exposure import (
    ToolExposureSession,
    apply_tool_exposure,
    attach_tool_catalog,
)
from travel_agent.tools.exposure_ledger import ToolExposureLedger
from travel_agent.tools.gateway import ToolGateway
from travel_agent.tools.registry import ToolRegistry


def _tool(name, description=""):
    return {
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "source": "local",
    }


def _names(schemas):
    return [schema["function"]["name"] for schema in schemas]


@pytest.mark.parametrize("mode", ["full", "deferred"])
def test_catalog_input_order_does_not_change_initial_request_definitions(mode):
    tools = [
        _tool("maps_z", "地图路线"),
        _tool("flight_a", "航班"),
        _tool("maps_a", "地图地点"),
    ]
    config = ToolExposureConfig(mode=mode, min_tools_threshold=1)
    first = apply_tool_exposure(tools, "destination_researcher", config=config)
    second = apply_tool_exposure(
        list(reversed(tools)), "destination_researcher_r3", config=config
    )
    assert first == second
    assert _names(first.tool_schemas) == (
        ["search_tools"] if mode == "deferred" else ["flight_a", "maps_a", "maps_z"]
    )
    before = deepcopy(tools)
    messages = [
        {"role": "system", "content": "stable contract"},
        {"role": "user", "content": "runtime"},
    ]
    assembled = attach_tool_catalog(messages, first)
    assert messages[0]["content"] == "stable contract"
    assert attach_tool_catalog(assembled, first) == assembled
    assert assembled[-1]["content"] == "runtime"
    assert tools == before


def test_activation_is_append_only_deduplicated_and_private_to_invocation():
    tools = [_tool("maps_z"), _tool("flight_a"), _tool("maps_a")]
    plan = apply_tool_exposure(
        tools,
        "destination_researcher",
        config=ToolExposureConfig(min_tools_threshold=1),
    )
    session = ToolExposureSession(tools, plan)
    initial = session.tool_schemas
    assert session.activate("flight")["activated"] == ["flight_a"]
    with_flight = session.tool_schemas
    assert with_flight[: len(initial)] == initial
    assert session.activate("maps")["activated"] == ["maps_a", "maps_z"]
    assert session.tool_schemas[: len(with_flight)] == with_flight
    assert session.activate("maps")["activated"] == []
    assert session.activate("not_allowed")["activated"] == []
    assert _names(session.tool_schemas) == [
        "search_tools",
        "flight_a",
        "maps_a",
        "maps_z",
    ]
    assert session.was_activated("flight_a")
    assert not session.was_activated("not_allowed")
    returned = session.tool_schemas
    returned[0]["function"]["name"] = "mutated"
    tools.append(_tool("not_allowed"))
    assert session.activate("not_allowed")["activated"] == []
    assert session.tool_schemas[0] == initial[0]
    assert ToolExposureSession(tools[:3], plan).tool_schemas == initial


def test_full_mode_search_does_not_expand_schemas():
    tools = [_tool("maps_a")]
    plan = apply_tool_exposure(
        tools, "destination_researcher", config=ToolExposureConfig(mode="full")
    )
    session = ToolExposureSession(tools, plan)
    assert session.activate("maps")["activated"] == []
    assert session.tool_schemas == list(plan.tool_schemas)


class _ScriptedLLM:
    def __init__(self, finishes):
        self.finishes = iter(finishes)
        self.requests = []

    async def astream_with_tools(self, messages, schemas):
        self.requests.append((deepcopy(messages), deepcopy(schemas)))
        yield {"type": "finish", **next(self.finishes)}


async def test_search_execution_and_replay_preserve_worker_transcript_and_gateway_audit(
    monkeypatch,
):
    registry = ToolRegistry()
    calls = []

    async def lookup():
        calls.append("lookup")
        return {
            "success": True,
            "results": [{"name": "Tokyo Museum", "place_id": "place_1"}],
        }

    registry.register(
        "fixture_lookup", "fixture lookup", {"type": "object", "properties": {}}, lookup
    )
    monkeypatch.setattr(utils, "get_tool_registry", lambda: registry)
    config = ToolExposureConfig(min_tools_threshold=1)
    monkeypatch.setattr(
        utils,
        "apply_tool_exposure",
        lambda tools, name: apply_tool_exposure(tools, name, config=config),
    )
    ledger = ToolExposureLedger()
    monkeypatch.setattr(utils, "get_tool_exposure_ledger", lambda: ledger)
    llm = _ScriptedLLM(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "search_1",
                        "name": "search_tools",
                        "arguments": {"query": "fixture"},
                    }
                ],
                "assistant_replay": {"reasoning_content": "search replay"},
            },
            {
                "content": "",
                "tool_calls": [
                    {"id": "lookup_1", "name": "fixture_lookup", "arguments": {}}
                ],
                "assistant_replay": {"reasoning_content": "lookup replay"},
            },
            {"content": "finished", "tool_calls": []},
        ]
    )
    messages = [
        {"role": "system", "content": "stable contract"},
        {"role": "user", "content": "runtime"},
    ]
    original_message = messages[0]
    queue = asyncio.Queue()
    audit_store = InMemoryToolAuditStore()
    result = await utils.streaming_react_loop(
        llm,
        messages,
        registry.get_tools_as_schemas(),
        queue,
        "destination_researcher",
        max_iterations=2,
        tool_context={
            "run_id": "run_exposure",
            "tool_audit_store": audit_store,
            "tool_gateway": ToolGateway(),
        },
    )
    content, summaries, pending, authoritative = result
    assert content == "finished" and pending is None
    assert calls == ["lookup"]
    assert len(summaries) == len(authoritative) == 1
    assert _names(llm.requests[0][1]) == ["search_tools"]
    assert (
        _names(llm.requests[1][1])
        == _names(llm.requests[2][1])
        == ["search_tools", "fixture_lookup"]
    )
    assert original_message == {"role": "system", "content": "stable contract"}
    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]
    assert messages[2]["assistant_replay"] == {"reasoning_content": "search replay"}
    assert messages[4]["assistant_replay"] == {"reasoning_content": "lookup replay"}
    assert json.loads(messages[3]["content"])["activated"] == ["fixture_lookup"]
    assert "Tokyo Museum" in messages[5]["content"]
    assert llm.requests[-1][0] == messages
    envelope = authoritative[0]
    assert envelope["metadata"]["activation_source"] == "searched"
    records = await audit_store.list_by_run("run_exposure")
    assert len(records) == 1 and records[0].audit_id == envelope["audit_id"]
    events = [queue.get_nowait() for _ in range(queue.qsize())]
    assert [event[0] for event in events] == [
        "tool_start",
        "tool_done",
        "tool_start",
        "tool_done",
    ]
    assert events[-1][2]["audit_id"] == envelope["audit_id"]
    # A later invocation starts with its own exposure, even on the same working transcript.
    later = _ScriptedLLM([{"content": "next", "tool_calls": []}])
    await utils.streaming_react_loop(
        later, messages, registry.get_tools_as_schemas(), None, "destination_researcher"
    )
    assert _names(later.requests[0][1]) == ["search_tools"]
    assert messages[0]["content"].count("【可用工具（按需激活）】") == 1
