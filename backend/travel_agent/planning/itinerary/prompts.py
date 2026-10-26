from __future__ import annotations

import json
from dataclasses import dataclass

from travel_agent.planning.state import TravelAgentState
from travel_agent.memory.agent_context import render_agent_context
from travel_agent.planning.assignments import resolve_agent_assignment
from travel_agent.planning.itinerary.model_schema import _composition_response_schema
from travel_agent.planning.itinerary.requirements import (
    controlled_day_dates,
    itinerary_day_count,
)
from travel_agent.planning.itinerary.supply import (
    authoring_domains,
)
from travel_agent.planning.nodes import NODE_ITINERARY
from travel_agent.planning.itinerary.selected_supply import (
    placement_capabilities,
    prompt_candidate_ids,
)
from travel_agent.planning.itinerary.day_capacity import daily_planning_windows
from travel_agent.planning.requirements.route_legs import (
    build_required_long_distance_legs,
    explicit_cross_day_return_required,
)
from travel_agent.planning.research.assignment_context import build_assignment_context


def _previous_attempt_failure_section(state: TravelAgentState) -> str:
    """上一次生成失败的原因，只用于一次带错误信息的重试。"""
    if not state.composition_failure_context:
        return ""
    return f"""

<previous_attempt_failure>
上一轮生成失败的原因：
- {state.composition_failure_context}
请修正这个问题后重新输出完整 JSON 对象，其余内容保持不变。
</previous_attempt_failure>"""


def _composition_schema_json(
    state: TravelAgentState, *, skeleton_only: bool, strict_wire: bool = True
) -> str:
    """提示词携带的响应结构，与请求里的 schema 一致。"""
    return json.dumps(
        _composition_response_schema(
            state.recommendation_catalog,
            skeleton_only=skeleton_only,
            strict_wire=strict_wire,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _composition_catalog_json(state: TravelAgentState, *, skeleton_only: bool) -> str:
    """候选事实；按每个领域的提示词容量截取。"""
    if state.recommendation_catalog is None:
        raise ValueError("itinerary composition requires the candidate catalog")
    candidate_index = state.recommendation_catalog.candidate_index()
    ids_by_kind = prompt_candidate_ids(
        state.recommendation_catalog,
        skeleton_only=skeleton_only,
    )
    return json.dumps(
        {
            "generation_id": state.recommendation_catalog.generation_id,
            "intent_spec_revision": state.recommendation_catalog.intent_spec_revision,
            "candidates": [
                candidate_index[candidate_id].model_dump(mode="json", exclude_none=True)
                for ids in ids_by_kind.values()
                for candidate_id in ids
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _composition_capabilities_json(
    state: TravelAgentState, *, skeleton_only: bool
) -> str:
    """候选的排程事实，按提示词容量截取。"""
    return json.dumps(
        placement_capabilities(
            state.recommendation_catalog,
            skeleton_only=skeleton_only,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _intent_item_payload(item) -> dict:
    """一条用户要求：可读摘要、作用对象与具体约束参数。"""
    payload = {
        "summary": item.public_summary,
        "target": item.target.value,
        "parameters": item.value.model_dump(mode="json", exclude={"value_type"}),
    }
    if item.source_text:
        payload["user_words"] = item.source_text
    return payload


def _user_requirements_json(state: TravelAgentState) -> str:
    """把 IntentSpec 中的用户要求按硬性、偏好与提醒分组交给模型。"""
    if state.intent_spec is None:
        raise ValueError("itinerary composition requires an IntentSpec")
    spec = state.intent_spec

    def items_for(strength: str) -> list[dict]:
        return [
            _intent_item_payload(item)
            for item in spec.active_items
            if item.strength.value == strength
        ]

    dates = controlled_day_dates(state)
    return json.dumps(
        {
            "objective": spec.objective_summary,
            "trip_window": {
                "start": dates[0].isoformat() if dates else None,
                "end": dates[-1].isoformat() if dates else None,
                "days": len(dates),
            },
            "hard_requirements": items_for("hard"),
            "preferences": items_for("soft"),
            "attention": items_for("informational"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _required_long_distance_legs_json(state: TravelAgentState) -> str:
    """受控身份要求的跨城移动，作为排期参数提供给模型。"""
    legs = build_required_long_distance_legs(
        state.controlled_trip_identity or {},
        cross_day_return_required=explicit_cross_day_return_required(
            state.user_query or ""
        ),
    )
    return json.dumps(
        [leg.model_dump(mode="json") for leg in legs],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _minimum_delivery_json(state: TravelAgentState) -> str:
    draft = state.minimum_delivery_draft
    if draft is None:
        raise ValueError("itinerary composition requires a Minimum Delivery Draft")
    return json.dumps(
        {
            "generation_id": draft.planning_generation_id,
            "intent_spec_revision": draft.intent_spec_revision,
            "constraint_pack_revision": draft.constraint_pack_revision,
            "day_shells": [item.model_dump(mode="json") for item in draft.day_shells],
            "preserved_hard_intent_ids": draft.preserved_hard_intent_ids,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _previous_mutations_json(state: TravelAgentState) -> str:
    return json.dumps(
        [
            mutation.model_dump(mode="json")
            for mutation in state.composition_mutations[-20:]
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class CompositionPrompt:
    system: str
    runtime: str


def _current_draft_context(state: TravelAgentState) -> str:
    context = {}
    if state.placement_skeleton is not None:
        context["placement_skeleton"] = state.placement_skeleton.model_dump(mode="json")
    if state.trip_workspace_v2 is not None:
        itinerary = state.trip_workspace_v2.itinerary
        entries = {
            entity.item_id: entity.model_dump(
                mode="json",
                include={
                    "item_id",
                    "day_id",
                    "place_id",
                    "name",
                    "meal_type",
                    "note",
                    "planned_start",
                    "planned_end",
                    "duration_minutes",
                    "selection_reason",
                },
            )
            for entity in [
                *itinerary.visit_stops,
                *itinerary.dining_stops,
                *itinerary.custom_blocks,
            ]
        }
        entries.update(
            {
                leg.transport_leg_id: leg.model_dump(
                    mode="json",
                    include={
                        "transport_leg_id",
                        "transport_class",
                        "selected_mode",
                        "from_endpoint",
                        "to_endpoint",
                        "departure_at",
                        "arrival_at",
                        "duration_minutes",
                    },
                )
                for leg in itinerary.transport_legs
            }
        )
        entries.update(
            {
                stay.stay_id: stay.model_dump(
                    mode="json",
                    include={
                        "stay_id",
                        "place_id",
                        "name",
                        "check_in_date",
                        "check_out_date",
                    },
                )
                for stay in itinerary.lodging_stays
            }
        )
        context["workspace_days"] = [
            {
                "day_id": day.day_id,
                "date": day.date.isoformat(),
                "destination_id": day.destination_id,
                "timeline": [
                    entries[ref.entity_id]
                    for ref in day.timeline
                    if ref.entity_id in entries
                ],
            }
            for day in itinerary.day_plans
        ]
    return json.dumps(context, ensure_ascii=False)


def _build_composition_prompt(
    state: TravelAgentState,
    task_desc: str,
    *,
    skeleton_only: bool = False,
    strict_wire_schema: bool = True,
) -> CompositionPrompt:
    if state.recommendation_catalog is None:
        raise ValueError("itinerary composition requires a candidate catalog")
    schema = _composition_schema_json(
        state,
        skeleton_only=skeleton_only,
        strict_wire=strict_wire_schema,
    )
    catalog = _composition_catalog_json(state, skeleton_only=skeleton_only)
    capabilities = _composition_capabilities_json(state, skeleton_only=skeleton_only)
    requirements = _user_requirements_json(state)
    required_legs = _required_long_distance_legs_json(state)
    minimum_delivery = _minimum_delivery_json(state)
    previous_mutations = _previous_mutations_json(state)
    _, assignment = resolve_agent_assignment(
        state.agent_assignments or {}, NODE_ITINERARY
    )
    brief = build_assignment_context(
        assignment=assignment,
        brief=state.research_brief,
        intent_spec=state.intent_spec,
        constraint_pack=state.constraint_pack,
    )
    transport_contract = (
        "- 这是行程骨架阶段：只确定 Visit/Dining 的日期、顺序、当地时间与停留时长，"
        "以及日期匹配的 long_distance 主方案；相邻实体之间暂时不写市内交通，"
        "后续会按你给出的顺序逐个补齐。"
        if skeleton_only
        else "- 同一 Day 内相邻两个 Visit/Dining 之间写一段市内交通：候选目录里有端点匹配的 "
        "public_transit / flexible 实测方案时优先引用它，实测的线路、时长与票价以 provider 为准；"
        "没有实测方案时，用 authored_route 写出行方式与门到门分钟数。"
        "authored_route 的端点由服务器按前后两个停留点自动填写，因此它只能出现在这一段相邻关系中，"
        "不要放在 Day 开头、Day 结尾或 long_distance 旁边。"
        "long_distance 只作为跨城锚点，不要用它代替市内连接。"
    )
    repair_section = _previous_attempt_failure_section(state)
    authoring_kinds = authoring_domains(
        state.recommendation_catalog,
        day_count=itinerary_day_count(state),
        skeleton_only=skeleton_only,
    )
    authoring_contract = ""
    if authoring_kinds:
        kind_labels = "、".join(sorted(authoring_kinds))
        authoring_contract = (
            f"\n- 下列领域的已选主方案数量较少，可以撰写具名条目补足真实体验：{kind_labels}。"
            "优先使用其中符合当天区域、兴趣与可用时间的已选主方案；除用户明确必去的地点外，"
            "不要求全部用上，也不要为了用完候选而牺牲节奏。"
            "撰写条目请写真实存在、可被地图检索到的具体地点，"
            "并同时给出 local_name、name、address（街道级地址）、city（所在城市），"
            "以及一句 selection_reason 说明为什么放在这一天这个时段。"
            "local_name 写这家店或这个景点门口招牌上的当地语言原名，逐字照写、不加译名不加拼音；"
            "name 写给旅行者看的常用名称。"
            "地点库按当地语言原名收录，local_name 的字形要与当地实际书写一致："
            "中国大陆写简体，日本写日文汉字与假名（按招牌上的假名写法），韩国写韩文，泰国写泰文。"
            "服务器会尝试为这些条目补充地图坐标；查不到坐标时仍保留你写的内容，"
            "所以只写你确信真实存在的具体地点，不要写泛指区域、连锁品牌统称或臆造门店。"
            "价格、营业时间、评分这类实时字段留空，不要编造。"
        )
    system = f"""<role>
你是 JourneyPilot 的旅行规划师。请先设计每一天的区域、核心体验、取舍与节奏，再决定已选方案的日期、顺序、当地时间与停留时长；事实不足的条目不要编造营业、预约或价格。
</role>

<daily_design>
- 每个Day填写day_design：focus用一行说当天主要区域和体验；rationale说明为什么这样走、怎样适合用户、取舍了什么。说明只能引用实际placements里的地点；不写候选ID、证据编号、内部字段或处理过程。
- 按已选候选坐标或区域把邻近体验放在同一天，餐馆顺路嵌入，住宿作为每日出入基地；优先安排有价值的核心体验，不按候选顺序或分数简单填满。用户明确文化专题时可以安排多个不同主题场馆；一般慢游不要因下雨就机械全部换成同类馆。
- 根据Daily Planning Windows的可用时段和固定交通安排首尾日；这些是默认规划假设，用户时段、真实路线和预约优先。为进出站或机场、行李、用餐、步行与休息留出时间，交通窗口要能容纳真实门到门路线。
- 长途抵达后，先预留下车出站时间（飞机45分钟，其他长途15分钟，均为规划假设），再加真实市内接驳时长；不要把到站时刻直接当成开始市内接驳的时刻。
- 主动休息填写day_design.free_time，给出带时区的起止时间；系统会把它放到当天相邻停留点之间。建议安排在已完成的Visit/Dining之后、离开该站的交通之前；返回酒店、取行李、跨区移动不算free_time，需要在实际路线中安排。rationale里的休息地点也建议与此一致。无主动留白时输出空数组。
- 非美食专题的可用游玩日应有符合兴趣的核心体验；不要只安排一顿饭就当作一整天已规划。较长空白应说明具体用途和时段，慢游留白不等于漏项，也不必为填时间强加景点。
- 不为迎合模板压缩核心游览时长。行程太满时删可选项或换近处候选，保留用户必去、固定订单和已知的开放条件。用餐时间要合理，并与店家营业事实一致。
- 除用户明确另有饮食作息外，先为午餐留出当地11:30–13:30之间的开始时间，再排其他可选活动；不要为了塞进第二个景点把午餐推到14点以后。
- rationale要逐项对照placements和真实路线：只有实际经过酒店的交通才写“回酒店取行李”。退房后默认随身携带行李，寄存条件未知时列为待确认，不要凭空插入取行李旅程。
- 每个Visit/Dining placement填写selection_reason，解释它在实际当天时段、顺序和区域中的作用。候选调研理由只是备选推荐，不要原样复制其中“第一站”“午后”等与最终排程冲突的说法；不要用“消磨时间”替代具体体验价值。
</daily_design>

<output_contract>
- 只输出一个可直接 json.loads 的 ItineraryCompositionDraft JSON 对象；不要 Markdown、解释、通用信封或 activities[]。
- 引用候选时只使用候选目录中、且由 JSON Schema 对当前 placement_kind 开放的 candidate_id：visit 对应 VisitCandidate，dining 对应 DiningCandidate，transport 对应 TransportCandidate，lodging_candidate_ids 对应 LodgingCandidate；不要跨类型引用，也不要复制或改写 candidate 的名称、价格、来源、交通 segments、营业事实或天气事实。
- 请按用户的这些要求规划行程：硬性要求优先安排；偏好用于取舍与排序，提醒类信息作为背景参考。Placement Capabilities 给出每个候选的排程事实（时长、营业窗口、交通端点与日期），请据此安排当天区域、节奏与天气。
- 主方案直接适应【规划前天气事实】里的逐日 data_kind、降水概率与风力：预报日的恶劣条件反映在排序、时间或交通选择上。
- 每个 Dining placement 选择具体门店并填写餐次；每个需要住宿的入住区间在 lodging_candidate_ids 选择具体 property。
- 每次游览或用餐是独立安排，不等于地点本身；不要重复同一次安排，已排期活动也不要时间重叠。同一地点可用于不同餐次或互不重叠的游览，包括跨日复用；同一个入住区间在 lodging_candidate_ids 只选一家 property。
- 每个 Day 的 placements 建议非空。除长途锚点构成的真实 travel-only day 外，建议每个 Day 都包含有实际体验意义的 Visit/Dining；不要求全程地点唯一，也不要仅因前一天用过就编造新地点。
- 带长途锚点的 Day 可以同时安排 Visit/Dining：建议抵达日的停留点排在锚点之后、出发日的停留点排在锚点之前，并让每个停留时间落在锚点同一侧，这样排程符合旅行者当天实际在城的时间。锚点与停留点之间留出符合路线时长的通行窗口及上下车缓冲。
- 同一段必需移动的备选主方案互斥；同一天可以既到达又离开（例如同日往返）。若同一天同时需要到达腿与离开腿，建议到达腿写在当天第一个 placement、离开腿写在最后一个，Visit/Dining 放在两腿之间。长途锚点放在 Placement Capabilities 给出的 departure_date 或 arrival_date 对应 Day。
{transport_contract}
- 不生成第二份晴雨行程；局部 Plan B 交给后续的天气调整机制处理。
- Visit/Dining 同时输出 planned_start 与 planned_end 两个键：有排期时两者都是带 IANA 对应 UTC offset、且落在 DayComposition.date 当地日期内的 ISO-8601 datetime；不排具体时间时两者都为 null，不要只输出一端。
- 同一 Day 内已排期的 Visit/Dining 按时间先后书写。不同地点之间预留符合路线实际时长的通行窗口，允许短而可行的转场，不要统一套用固定时长，也不要重叠。
- 正文与 day_design 说明里不要出现候选ID、证据编号、内部字段名，也不要解释服务器如何处理数据。
</output_contract>"""
    runtime = f"""<composition_runtime>
<task_contract>{authoring_contract}</task_contract>
<user_requirements>
{requirements}
</user_requirements>
<context>
任务：{task_desc}
每日规划窗口（默认假设，非实测交通）：{json.dumps(daily_planning_windows(state, state.recommendation_catalog), ensure_ascii=False)}
需要的跨城移动：{required_legs}
Minimum Delivery Day Shell：{minimum_delivery}
Previous Composition Mutations：{previous_mutations}
Current Daily Draft：{_current_draft_context(state)}
{brief}
Selected Candidate Facts：{catalog}
Selected Candidate Capabilities：{capabilities}
</context>{repair_section}

<json_schema>{schema}</json_schema>
{render_agent_context(state, NODE_ITINERARY)}
</composition_runtime>"""
    return CompositionPrompt(system, runtime)
