"""Research worker prompt 的最小运行时合同。"""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from travel_agent.agents.research_packet_output import (
    ResearchWorkerKind,
    packet_candidate_limit,
)
from travel_agent.agents.research_packet_prompt import (
    build_research_packet_prompt,
    build_research_packet_system_prompt,
)
from travel_agent.entities.delivery_bundle import ResearchPacket


@pytest.mark.parametrize(
    "worker_kind",
    [
        "destination_researcher",
        "accommodation_researcher",
        "transport_researcher",
    ],
)
def test_prompt_injects_the_packet_schema_and_matching_candidate_limit(
    worker_kind: ResearchWorkerKind,
) -> None:
    """模型实际读取的 schema 与候选上限必须来自同一次真实渲染。"""

    candidate_limit = packet_candidate_limit(worker_kind)
    prompt = build_research_packet_system_prompt(
        worker_kind=worker_kind,
        run_id="run_prompt_test",
        task_id="task_prompt_test",
        constraint_pack_revision=1,
        fact_data_revision=1,
        current_time="2026-01-02 09:30",
        research_brief_context="",
        candidate_limit=candidate_limit,
        upstream_packet_context="[]",
        active_constraint_ids=(),
    )
    schema = json.dumps(
        ResearchPacket.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    assert prompt.count(schema) == 1
    assert f'"candidate_limit":{candidate_limit}' in prompt
    assert "本 Packet 最多输出本轮 candidate_limit 个" in prompt
    assert prompt.index(schema) < prompt.index("run_prompt_test")


def test_new_research_run_preserves_the_complete_schema_prefix() -> None:
    options = dict(
        worker_kind="destination_researcher",
        task_id="task_a",
        constraint_pack_revision=1,
        fact_data_revision=1,
        current_time="2026-10-05 10:00",
        research_brief_context="北京",
        candidate_limit=3,
    )
    first = build_research_packet_system_prompt(run_id="run_a", **options)
    second = build_research_packet_system_prompt(
        run_id="run_b",
        **{
            **options,
            "task_id": "task_b",
            "current_time": "2026-10-06 11:00",
            "research_brief_context": "上海",
            "candidate_limit": 2,
        },
    )
    assert first.split("</json_schema>")[0] == second.split("</json_schema>")[0]


@pytest.mark.parametrize(
    "worker_kind",
    [
        "destination_researcher",
        "accommodation_researcher",
        "transport_researcher",
    ],
)
def test_dynamic_inputs_change_only_runtime_and_preserve_message_boundaries(
    worker_kind,
):
    options = dict(
        worker_kind=worker_kind,
        run_id="run_a",
        task_id="task_a",
        constraint_pack_revision=1,
        fact_data_revision=1,
        current_time="2026-10-05 10:00",
        research_brief_context="北京",
        candidate_limit=4,
        upstream_packet_context="upstream_a",
        active_constraint_ids=["constraint_a"],
        recommended_tools=["maps_text_search"],
        state=SimpleNamespace(session_anchor={"summary": "anchor_a"}),
    )
    first = build_research_packet_prompt(**options)
    second = build_research_packet_prompt(
        **{
            **options,
            "run_id": "run_b",
            "task_id": "task_b",
            "candidate_limit": 12,
            "constraint_pack_revision": 3,
            "fact_data_revision": 9,
            "current_time": "2026-10-06 11:00",
            "research_brief_context": "上海",
            "upstream_packet_context": "upstream_b",
            "active_constraint_ids": ["constraint_b"],
            "recommended_tools": ["global_place_search"],
            "state": SimpleNamespace(session_anchor={"summary": "anchor_b"}),
        }
    )
    assert first.system == second.system
    assert first.runtime != second.runtime
    for value in ("run_b", "task_b", "anchor_b", "constraint_b", "upstream_b", "上海"):
        assert value not in second.system
        assert value in second.runtime
    history = [
        {"role": "user", "content": "old task"},
        {"role": "assistant", "content": "old answer"},
    ]
    before = deepcopy(history)
    messages = second.messages(history)
    messages.append({"role": "user", "content": "current task"})
    assert [message["content"] for message in messages] == [
        second.system,
        "old task",
        "old answer",
        second.runtime,
        "current task",
    ]
    assert history == before
    messages[1]["content"] = "changed working transcript"
    assert history == before


def test_context_sections_have_one_owner_and_are_injected_once(monkeypatch):
    from travel_agent.memory.agent_context import agent_context_sections
    from travel_agent.panels import constraint
    from travel_agent.preset.injector import PresetInjector
    from travel_agent.workflows import weather_context

    monkeypatch.setattr(
        PresetInjector, "format_for_agent", lambda value: f"preset:{value}"
    )
    monkeypatch.setattr(
        constraint,
        "format_constraint_pack_for_prompt",
        lambda value: f"constraints:{value}",
    )
    monkeypatch.setattr(
        weather_context,
        "format_weather_context_for_planning",
        lambda state: f"weather:{state.weather_context}",
    )
    state = SimpleNamespace(
        session_anchor={"summary": "unique_anchor"},
        preset_context="A",
        constraint_pack="B",
        weather_context="C",
    )
    sections = agent_context_sections(state, "destination_researcher")
    assert [section.name for section in sections] == [
        "session_anchor",
        "preset",
        "constraints",
        "weather",
    ]
    prompt = build_research_packet_prompt(
        worker_kind="destination_researcher",
        run_id="run",
        task_id="task",
        constraint_pack_revision=1,
        fact_data_revision=1,
        current_time="now",
        research_brief_context="brief",
        candidate_limit=4,
        state=state,
    )
    for section in sections:
        assert section.text not in prompt.system
        assert prompt.runtime.count(section.text) == 1
