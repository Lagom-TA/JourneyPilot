"""Research worker prompt 的最小运行时合同。"""

from __future__ import annotations

import json

import pytest

from travel_agent.agents.research_packet_output import (
    ResearchWorkerKind,
    packet_candidate_limit,
)
from travel_agent.agents.research_packet_prompt import (
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
    assert f"本 Packet 最多输出 {candidate_limit} 个" in prompt
