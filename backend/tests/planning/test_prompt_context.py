"""Research worker prompt 的最小运行时合同。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from travel_agent.planning.research.output.policy import (
    ResearchWorkerKind,
    packet_candidate_limit,
)
from travel_agent.planning.research.prompts import (
    _packet_schema,
    build_research_packet_prompt,
)


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
    prompt = build_research_packet_prompt(
        worker_kind=worker_kind,
        run_id="run_prompt_test",
        task_id="task_prompt_test",
        fact_data_revision=1,
        current_time="2026-01-02 09:30",
        candidate_limit=candidate_limit,
        task_desc="自然研究设想",
        upstream_packet_context="[]",
        active_constraint_ids=(),
    )
    schema = _packet_schema()

    assert prompt.system.count(schema) == 1
    assert f'"candidate_limit":{candidate_limit}' in prompt.runtime


def test_packet_schema_only_offers_the_fields_the_model_writes() -> None:
    """服务端绑定的 packet 元数据不属于模型输出合同。"""

    schema = json.loads(_packet_schema())
    assert set(schema["properties"]) == {
        "candidates",
        "fact_assertions",
        "field_provenance",
        "source_records",
    }
    assert "metadata" not in json.dumps(schema["properties"]).lower()


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
        fact_data_revision=1,
        current_time="2026-10-05 10:00",
        candidate_limit=4,
        task_desc="自然研究设想",
        upstream_packet_context="upstream_a",
        active_constraint_ids=["constraint_a"],
        recommended_tools=["maps_text_search"],
        state=SimpleNamespace(current_requirements="北京"),
    )
    first = build_research_packet_prompt(**options)
    second = build_research_packet_prompt(
        **{
            **options,
            "run_id": "run_b",
            "task_id": "task_b",
            "candidate_limit": 12,
            "fact_data_revision": 9,
            "current_time": "2026-10-06 11:00",
            "upstream_packet_context": "upstream_b",
            "active_constraint_ids": ["constraint_b"],
            "recommended_tools": ["global_place_search"],
            "state": SimpleNamespace(current_requirements="上海"),
        }
    )
    assert first.system == second.system
    assert first.runtime != second.runtime
    for value in ("run_b", "task_b", "constraint_b", "upstream_b", "上海"):
        assert value not in second.system
        assert value in second.runtime
    messages = second.messages()
    assert [message["content"] for message in messages] == [
        second.system,
        second.runtime,
    ]


def test_research_prompt_uses_the_understanding_without_extra_context():
    state = SimpleNamespace(
        controlled_trip_identity={"origin": None, "destinations": []},
        current_requirements="完整旅行理解",
        user_query="原始旅行消息",
        session_anchor={"summary": "早期对话"},
        preset_context="额外背景",
        constraint_pack={"constraints": ["重复偏好"]},
    )
    prompt = build_research_packet_prompt(
        worker_kind="destination_researcher",
        run_id="run",
        task_id="task",
        fact_data_revision=1,
        current_time="now",
        candidate_limit=4,
        task_desc="自然研究设想",
        state=state,
    )
    assert prompt.runtime.count("完整旅行理解") == 1
    for value in ("原始旅行消息", "早期对话", "额外背景", "重复偏好"):
        assert value not in prompt.runtime
