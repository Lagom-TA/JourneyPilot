"""把三个 research worker 的提示词渲染成可提交的快照。

为什么值得快照：``build_research_packet_system_prompt`` 那段文字是硬合同，不是
说明文档。主 worker 调用不带 ``response_format``，
``research_packet_output._closed_definitions`` 的 docstring 写明了后果——直连
DeepSeek 拒 ``response_format=json_schema``，``models/router.py`` 把它降级成
``json_object`` 并把 schema 复述成 prose，"The schema text is therefore the
entire contract the model reads"。一句散文改错，模型读到的合同就变了，而这个函数
今天零守卫：十个关键字参数，纯字符串拼接，改一个字没有任何东西会红。

快照的入参是固定的（``_FIXED``），只有 ``candidate_limit`` 例外：它取
``packet_candidate_limit(worker)``，不写死数字。4 改 5 的那天，三份快照该跟着变，
而这正是要在 diff 里看见的东西。

schema 段不进快照。``render_system_prompt`` 先断言 schema 文本确实逐字出现在
输出里，再把它换成占位符。那一行断言是这套东西的核心：它守住「schema 逐字符注入
这件事没断」，而 schema 的内容由 ``ResearchPacket`` 的类型定义管——改 entity 字段
不该让三份散文快照跟着 churn。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..agents.accommodation_researcher.node import build_accommodation_task_prompt
from ..agents.destination_researcher.node import build_destination_task_prompt
from ..agents.research_packet_output import (
    ResearchWorkerKind,
    packet_candidate_limit,
)
from ..agents.research_packet_prompt import build_research_packet_system_prompt
from ..agents.transport_researcher.node import build_transport_task_prompt
from ..entities.delivery_bundle import ResearchPacket

# 快照里代替 ``<json_schema>`` 正文的占位符。
SCHEMA_PLACEHOLDER = "<RESEARCH_PACKET_SCHEMA>"

WORKER_KINDS: tuple[ResearchWorkerKind, ...] = (
    "destination_researcher",
    "accommodation_researcher",
    "transport_researcher",
)

# 除 candidate_limit 以外的固定入参。值本身没有意义，稳定才有意义：同样的入参
# 每次必须渲染出同样的字节，否则快照测的是入参而不是提示词。
_FIXED: dict[str, Any] = {
    "run_id": "run_snapshot",
    "task_id": "task_snapshot",
    "constraint_pack_revision": 7,
    "fact_data_revision": 3,
    "current_time": "2026-01-02 09:30",
    "research_brief_context": "研究简报：快照固定入参。",
    "upstream_packet_context": "[]",
    "active_constraint_ids": ("constraint_budget", "constraint_accessibility"),
}


def _schema_text() -> str:
    """与 ``build_research_packet_system_prompt`` 里那一行完全同形的序列化。"""

    return json.dumps(
        ResearchPacket.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def render_system_prompt(worker_kind: ResearchWorkerKind) -> str:
    """渲染一个 worker 的 system prompt，schema 段换成占位符。"""

    prompt = build_research_packet_system_prompt(
        worker_kind=worker_kind,
        candidate_limit=packet_candidate_limit(worker_kind),
        **_FIXED,
    )
    schema_text = _schema_text()
    # 这一行是整套快照里最重要的断言：schema 必须逐字符出现在提示词里。它一旦不再
    # 成立（换成摘要、截断、改了序列化参数），模型读到的合同就变了，而下面的替换会
    # 静默什么都不做，把这件事藏进一份看起来只是"变长了"的快照里。
    assert schema_text in prompt, (
        f"{worker_kind} 的 system prompt 里找不到逐字注入的 ResearchPacket schema："
        "schema 文本是模型读到的全部合同，不能被摘要或改写"
    )
    return prompt.replace(schema_text, SCHEMA_PLACEHOLDER)


# 三个 task prompt 的分支不是一个：destination 与 accommodation 各两条，transport
# 四条。每条都渲染一份——只钉一条分支等于给另外几条发免检通行证。
_TASK_PROMPTS: dict[str, Callable[[], str]] = {
    "destination.initial": lambda: build_destination_task_prompt(
        task_desc="研究东京的当代建筑与本地餐饮",
        user_query="想看当代建筑，顺路吃点本地的",
        rag_context_section="参考知识库片段：引用标识 chunk_tokyo_01。",
        require_current_candidate=False,
        offered_dining_place_ids=["ChIJ_snapshot_dining_a", "ChIJ_snapshot_dining_b"],
        destination_boundaries=[
            {"destination_id": "destination_tokyo", "country_code": "JP"}
        ],
    ),
    "destination.repair": lambda: build_destination_task_prompt(
        task_desc="补齐东京 Visit/Dining 候选的身份字段",
        user_query="想看当代建筑，顺路吃点本地的",
        rag_context_section="参考知识库片段：引用标识 chunk_tokyo_01。",
        require_current_candidate=True,
        offered_dining_place_ids=["ChIJ_snapshot_dining_a"],
        destination_boundaries=[
            {"destination_id": "destination_tokyo", "country_code": "JP"}
        ],
    ),
    "accommodation.initial": lambda: build_accommodation_task_prompt(
        task_desc="研究东京两段入住区间的具体酒店",
        user_query="想住得离地铁近一点",
        require_current_candidate=False,
    ),
    "accommodation.repair": lambda: build_accommodation_task_prompt(
        task_desc="补齐东京酒店候选的地址与 place_id",
        user_query="想住得离地铁近一点",
        require_current_candidate=True,
    ),
    "transport.initial": lambda: build_transport_task_prompt(
        task_desc="研究上海到东京的城际交通与市内连接",
        user_query="想省点转车时间",
        required_transport_classes=None,
        connector_gaps=None,
        require_current_candidate=False,
        required_route_scopes=[],
    ),
    "transport.repair": lambda: build_transport_task_prompt(
        task_desc="补齐交通候选缺失的事实",
        user_query="想省点转车时间",
        required_transport_classes=None,
        connector_gaps=None,
        require_current_candidate=True,
        required_route_scopes=[],
    ),
    "transport.scoped_local": lambda: build_transport_task_prompt(
        task_desc="补齐两个景点之间的市内连接",
        user_query="想省点转车时间",
        required_transport_classes=["public_transit"],
        connector_gaps=[
            {
                "from_candidate_id": "candidate_visit_a",
                "to_candidate_id": "candidate_visit_b",
            }
        ],
        require_current_candidate=True,
        required_route_scopes=[],
    ),
    "transport.scoped_long_distance": lambda: build_transport_task_prompt(
        task_desc="补齐上海到东京的长途 Leg",
        user_query="想省点转车时间",
        required_transport_classes=["long_distance"],
        connector_gaps=None,
        require_current_candidate=True,
        required_route_scopes=[],
    ),
}


def snapshot_artifacts() -> dict[str, str]:
    """相对 ``tests/fixtures/prompts`` 的文件名 → 应有的正文。"""

    artifacts = {
        f"research_packet_system.{worker}.txt": render_system_prompt(worker)
        for worker in WORKER_KINDS
    }
    artifacts.update(
        {f"task_prompt.{name}.txt": build() for name, build in _TASK_PROMPTS.items()}
    )
    return artifacts


def fixture_dir(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures" / "prompts"
