from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from travel_agent.planning.requirements.composition_contracts import COMPOSITION_PROMPT_VERSION, CompositionRule
from travel_agent.planning.state import TravelAgentState
from travel_agent.memory.agent_context import render_agent_context
from travel_agent.planning.assignments import resolve_agent_assignment
from travel_agent.planning.itinerary.model_schema import _composition_response_schema
from travel_agent.planning.itinerary.requirements import itinerary_day_count
from travel_agent.planning.itinerary.supply import (
    authoring_domains,
)
from travel_agent.planning.nodes import NODE_ITINERARY
from travel_agent.planning.itinerary.selected_supply import (
    placement_capabilities,
    prompt_candidate_ids,
)
from travel_agent.planning.requirements.composition_compiler import compile_composition_rules
from travel_agent.planning.itinerary.day_capacity import daily_planning_windows
from travel_agent.planning.research.assignment_context import build_assignment_context


def _previous_attempt_failure_section(state: TravelAgentState) -> str:
    """上一轮失败原因注入：这是修复轮唯一的新增输入。"""
    if not state.composition_failure_context:
        return ""
    return f"""

<previous_attempt_failure>
上一轮组合失败的确切原因如下，这一轮必须修正它：
- {state.composition_failure_context}
只针对上面点出的问题做最小改动：其余已经合法的候选选择、日期、顺序与当地时间保持原样，不要连带改写。
</previous_attempt_failure>"""


def _composition_schema_json(
    state: TravelAgentState, *, skeleton_only: bool, strict_wire: bool = True
) -> str:
    """The response schema exactly as the prompt carries it."""
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
    """候选事实，与提示词携带内容逐字一致（按每域容量上限截取）。"""
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
    """Placement Capabilities exactly as the prompt carries them."""
    return json.dumps(
        placement_capabilities(
            state.recommendation_catalog,
            skeleton_only=skeleton_only,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _composition_rules(state: TravelAgentState) -> list[CompositionRule]:
    if state.intent_spec is None:
        raise ValueError("itinerary composition requires an IntentSpec")
    return compile_composition_rules(state.intent_spec)


def _composition_rules_json(state: TravelAgentState) -> str:
    return json.dumps(
        [rule.model_dump(mode="json") for rule in _composition_rules(state)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _intent_contract_json(state: TravelAgentState) -> str:
    if state.intent_spec is None:
        raise ValueError("itinerary composition requires an IntentSpec")
    return json.dumps(
        {
            "schema_version": state.intent_spec.schema_version,
            "intent_spec_id": state.intent_spec.intent_spec_id,
            "revision": state.intent_spec.revision,
            "generation_id": state.intent_spec.generation_id,
            "content_hash": state.intent_spec.content_hash,
            "objective_summary": state.intent_spec.objective_summary,
            "active_items": [
                item.model_dump(
                    mode="json",
                    exclude={"source_text", "source_span_start", "source_span_end"},
                )
                for item in state.intent_spec.active_items
            ],
        },
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
    required_candidate_kinds: Optional[set[str]] = None,
    required_long_distance_legs: Optional[list] = None,
    strict_wire_schema: bool = True,
) -> CompositionPrompt:
    if state.recommendation_catalog is None:
        raise ValueError(
            "itinerary composition requires an admitted Recommendation Catalog"
        )
    schema = _composition_schema_json(
        state,
        skeleton_only=skeleton_only,
        strict_wire=strict_wire_schema,
    )
    catalog = _composition_catalog_json(state, skeleton_only=skeleton_only)
    capabilities = _composition_capabilities_json(state, skeleton_only=skeleton_only)
    rules = _composition_rules_json(state)
    intent_contract = _intent_contract_json(state)
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
        "- 这是 placement skeleton 阶段：禁止引用任何 public_transit 或 flexible candidate，"
        "只确定 Visit/Dining 的 Day、顺序、当地时间以及日期匹配的 long_distance 主方案。"
        "相邻实体之间暂时不插入路线，后续只从这个顺序确定性提取 connector gaps。"
        if skeleton_only
        else "- 同一 Day 内相邻两个 Visit/Dining placement 之间必须插入一个 Transport placement："
        "这一对端点上只要候选目录里有 public_transit / flexible 候选，就**必须**引用那个候选——"
        "它是 Provider 实测的线路、时长与票价，你写的是估计值，估计值不得顶替实测值。"
        "只有这一对端点上没有任何已选主方案时，才用 authored_route 写出出行方式与门到门分钟数"
        "（端点由服务器按前后两个停留点自动填写）。候选只给时长不给时刻表是正常的——"
        "中国大陆的公交地铁按时长作答，时长本身就是这段路的事实。"
        "authored_route 的端点来自它前后紧邻的两个停留点，所以它只能作为这一段相邻关系里"
        "的唯一一条路线：同一段相邻关系内不得再放第二条 Transport placement，也不得把 "
        "authored_route 放在 Day 开头、Day 结尾或 long_distance 旁边这类没有前后两个停留点的位置。"
        "long_distance 只能作为远距离锚点，不能冒充市内连接，也不得输出没有连接段的路线。"
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
            f"\n- 下列领域的已选主方案数量较少，允许你撰写具名条目补足真实体验缺口：{kind_labels}。"
            "优先使用其中符合当天区域、兴趣与可用时间的已选主方案；除用户必去义务外，"
            "不要求全部用上，不得为了用完候选而牺牲节奏。撰写条目仅补真实体验缺口，不得仅为避免合理复用而另造地点。"
            "撰写条目必须是真实存在、可被地图检索到的地点，"
            "并同时给出 local_name、name、address（街道级地址）、city（所在城市），"
            "以及一句 selection_reason 说明为什么放在这一天这个时段。"
            "local_name 写这家店/这个景点门口招牌上的当地语言原名，逐字照写、不加译名不加拼音；"
            "name 写给旅行者看的常用名称。"
            "地点库是按当地语言原名收录的，local_name 写对与否直接决定这个条目能不能落地，"
            "所以字形必须与当地实际书写一致：中国大陆写简体，不写繁体或异体；"
            "日本写日文汉字与假名，按招牌上的假名写法，不改写成中文汉字也不换用别的假名拼法；"
            "韩国写韩文，泰国写泰文。"
            "服务器会逐个核对坐标，查不到的地点会被退回要求你换一个；"
            "所以只写你确信真实存在的地点，不要写泛指区域、连锁品牌统称或臆造门店。"
            "价格、营业时间、评分这类实时字段一律留空，不要编造。"
        )
    required_kinds_contract = ""
    if required_candidate_kinds:
        kind_labels = "、".join(sorted(required_candidate_kinds))
        required_kinds_contract = (
            f"\n- 整份行程必须为下列每一种物理类型各放置至少一个已选主方案：{kind_labels}。"
            "“每个 Day 至少含一个 Visit/Dining”指的是“非空”，绝不等于可以整份省略某一类型；"
            "只要 required 类型含 dining，就必须至少出现一个 DiningCandidate（用户明确要求美食），"
            "同理 visit 也必须至少出现一个。宁可减少同日停留点，也不得整类缺席。"
        )
    system = f"""<role>
你是 JourneyPilot 的旅行规划师。先设计每一天的区域、核心体验、取舍与节奏，再决定已选主方案的日期、顺序、当地时间与停留时长；事实不足的条目不能编造营业、预约或价格。
</role>

<daily_design>
- 每个Day填写day_design：focus用一行说当天主要区域和体验；rationale说明为什么这样走、怎样适合用户、取舍了什么。说明只能引用实际placements里的地点；不写候选ID、责任锚点、准入、合同等内部词。
- 按已选候选坐标/区域把邻近体验放在同一天，餐馆顺路嵌入，住宿作为每日出入基地；优先有价值的核心体验，不按候选顺序或分数简单填满。用户明确文化专题时允许多个不同主题场馆；一般慢游不能因下雨就机械全部变为同类馆。
- 根据Daily Planning Windows的可用时段和固定交通安排首尾日；这些是默认规划假设，用户时段、真实路线和预约优先。预留进出站/机场、行李、用餐、步行与休息，交通窗口必须足够容纳真实门到门路线。
- 长途抵达后，先预留下车出站时间（飞机45分钟，其他长途15分钟，均为规划假设），再加真实市内接驳时长；不能把到站时刻直接当成开始市内接驳的时刻。
- 主动休息填写day_design.free_time，仅给出带时区的起止时间；系统将其明确定位在上一站所在区域。必须在已完成的Visit/Dining之后、离开该站的交通之前，不能与活动或交通重叠。返回酒店、取行李、跨区移动不能算作free_time；需在实际路线中安排。rationale里的休息地点也必须与此一致，不能假定可在店内长坐或退房后使用客房。无主动留白时输出空数组。
- 非美食专题的可用游玩日应有符合兴趣的核心体验；不能只安排一顿饭便视为一整天已规划。较长空白应说明具体用途和时段，慢游留白不等于漏项，也不必为填时间强加景点。
- 不为迎合模板压缩核心游览时长。行程太满时删可选项或换近处候选，保留用户必去、固定订单和已核验开放条件。用餐时间应合理且与店家营业事实一致。
- 除用户明确另有饮食作息外，先为午餐留出当地11:30–13:30之间的开始时间，再排其他可选活动。不要为了塞进第二个景点把午餐推到14点以后；必要时把景点移到午餐后或删去。
- rationale必须逐项对照placements和真实路线：只有实际经过酒店的交通才可写“回酒店取行李”。退房后默认随身携带行李，寄存条件未知时列为待确认，不能凭空插入取行李旅程。当天无酒店中途停靠的路线，不得在说明中暗示已安排。
- 每个Visit/Dining placement填写selection_reason，解释它在实际当天时段、顺序和区域中的作用。候选调研理由只是备选推荐，不要原样复制其中“第一站”“午后”等与最终排程冲突的说法；不要用“消磨时间”替代具体体验价值。
</daily_design>

<hard_contract>
- 只输出一个可直接 json.loads 的 ItineraryCompositionDraft JSON 对象；禁止 Markdown、解释、旧通用信封或 activities[]。
- 引用候选时只能引用候选目录中、且由 JSON Schema 对当前 placement_kind 开放的 candidate_id：visit 只能选 VisitCandidate，dining 只能选 DiningCandidate，transport 只能选 TransportCandidate，lodging_candidate_ids 只能选 LodgingCandidate；禁止跨类型引用，也禁止复制或改写 candidate 的名称、价格、来源、交通 segments、营业事实或天气事实。
- Composition Rules 是本轮可执行意图合同。never_violate 规则不得违反；repair_then_deviate 规则无法落实时按原意给出最接近的可行安排；nonblocking_preference 只参与选择和排程，不得伪装成硬事实。
- Placement Capabilities 给出每个候选的调度事实（时长、营业窗口、交通端点与日期）。按当天区域、节奏与天气安排候选：户外项排到天气更好的一天，与预算档位不符的项让位给更合适的同类。
- 主方案直接适应【规划前天气事实】里的逐日 data_kind、降水概率与风力：forecast 日的恶劣条件必须反映在排序、时间或交通选择上。
- 本轮必须覆盖的领域、允许撰写的不足领域与精确 candidate_id 合同见最新 composition_runtime；禁止扩大授权领域。
- 每个 Dining placement 必须选择具体门店并填写餐次；每个需要住宿的入住区间必须在 lodging_candidate_ids 选择具体 property。
- 每次游览或用餐是独立安排，不等于地点本身；不得重复同一次安排，已排期活动也不得时间重叠。同一地点可用于不同餐次或互不重叠的游览，包括跨日复用，前提是符合用户偏好、位置或体验价值；同一个入住区间在 lodging_candidate_ids 只选一家 property。
- 每个 Day 的 placements 必须非空。除长途锚点构成的真实 travel-only day 外，每个 Day 必须包含有实际体验意义的 Visit/Dining，不得重复凑数；不要求全程地点唯一，也不得仅因前一天用过就编造新地点。
- **带长途锚点的 Day 允许同时安排 Visit/Dining**，条件是这些停留点必须给出 planned_start 与 planned_end，并且**全部落在锚点的同一侧**。长途锚点不是一段「忙碌时间」，它把旅行者从一座城市搬到另一座：出发前他在出发城市，抵达后他才在这个 Day 的目的地。所以只有一侧可能安排本地停留，另一侧他根本不在这座城市——
  - **抵达日**（锚点把旅行者送到这个 Day 的目的地，含跨夜锚点落在其 arrival 日期的那一天）：锚点必须写成这个 Day 的**第一个** placement，所有停留点排在它后面，且每个 planned_start 都不早于锚点的 arrival_at。
  - **离开日**（锚点把旅行者带离这个 Day 的目的地，含跨夜锚点落在其 departure 日期的那一天）：锚点必须写成这个 Day 的**最后一个** placement，所有停留点排在它前面，且每个 planned_end 都不晚于锚点的 departure_at。
  - placements 的书写顺序就是服务器读取锚点方向的依据，写反了会被当成反方向的锚点，并据此向反方向的端点索取一段市内接驳（例如把抵达高铁写在停留点之后，服务器就会去要一段「深圳的餐厅 → 上海虹桥」的市内路线）。顺序与方向必须一致。
  **锚点与停留点之间要留出符合路线时长的通行窗口及上下车缓冲**——从站台到景点、从餐厅回车站都是真实路程，需要这段时间才能排出接驳。当整份行程的每一天都被长途锚点占据（最典型的是两天往返）时，**必须**用这个办法把 required kinds 安排进去——此时不存在没有锚点的空闲 Day，把所有天都做成 travel-only 会导致 required kinds 无处安放、整份组合被拒。
- Catalog 中存在 long_distance 候选时，每一段**必需移动**（出发、逐对 inter_destination、返程）各选择一个主方案即可；"每个 service window 只选一个主方案" 指的是**同一段必需移动的同方向备选互斥**，不禁止同一天既到达又离开（例如 1 天同日往返，或末日既要交接又要返程）。若是后者那种同一天同时欠「到达腿」与「离开腿」的日子：**必须把到达腿放这一天第一个 placement、离开腿放这一天最后一个 placement**，所有 Visit/Dining 停留在两腿**之间**（planned_start 不早于到达腿 arrival_at、planned_end 不晚于离开腿 departure_at，且留足符合路线时长的通行窗口及上下车缓冲），不得只放一段而漏另一段。长途锚点只能放在 Placement Capabilities 给出的 departure_date 或 arrival_date 对应 Day；行程还有不带锚点的 Day 时它可以单独构成 travel-only Day。禁止把同日备选航班分配到其它日期凑行程，也禁止为了同日追加停留点而把端点不一致的市内路线硬接到长距离锚点。
{transport_contract}
- 不生成第二份晴雨行程；局部 Plan B 由后续 typed contingency 合同处理。
- Visit/Dining 必须同时输出 planned_start 与 planned_end 两个键：有排期时两者都是带 IANA 对应 UTC offset、且落在 DayComposition.date 当地日期内的 ISO-8601 datetime；不排具体时间时两者都为 null，禁止只输出一端。
- 同一 Day 内已排期的 Visit/Dining 必须按时间先后书写。不同地点之间预留符合路线实际时长的通行窗口；允许短而可行的转场，不统一套用固定时长，不得重叠或由服务器平移日程。
</hard_contract>"""
    runtime = f"""<composition_runtime>
<task_contract>{authoring_contract}{required_kinds_contract}</task_contract>
<context>
组合提示版本：{COMPOSITION_PROMPT_VERSION}
任务：{task_desc}
Intent Contract Snapshot：{intent_contract}
Composition Rules：{rules}
Minimum Delivery Day Shell：{minimum_delivery}
Daily Planning Windows（默认假设，非实测交通）：{json.dumps(daily_planning_windows(state, state.recommendation_catalog), ensure_ascii=False)}
Previous Composition Mutations：{previous_mutations}
Current Daily Draft：{_current_draft_context(state)}
Required Long-distance Legs：{json.dumps([leg.model_dump(mode="json") for leg in required_long_distance_legs or []], ensure_ascii=False)}
{brief}
Selected Candidate Facts：{catalog}
Selected Candidate Capabilities：{capabilities}
</context>{repair_section}

<json_schema>{schema}</json_schema>
{render_agent_context(state, NODE_ITINERARY)}
</composition_runtime>"""
    return CompositionPrompt(system, runtime)
