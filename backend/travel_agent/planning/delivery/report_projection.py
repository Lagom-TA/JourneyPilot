"""交付报告的投影。"""

from __future__ import annotations

from datetime import date
from datetime import datetime
from travel_agent.planning.costs.presentation import cost_coverage_statement
from travel_agent.planning.delivery.candidate_presentation import candidate_display_name
from travel_agent.planning.delivery.citation_projection import _citation_lookup
from travel_agent.planning.delivery.citation_projection import project_public_citations
from travel_agent.planning.delivery.presentation import block_presentation
from travel_agent.planning.delivery.projection_errors import DeliveryProjectionError
from travel_agent.planning.delivery.projections import ReportDaySection
from travel_agent.planning.delivery.projections import ReportDestination
from travel_agent.planning.delivery.projections import ReportEntityBlock
from travel_agent.planning.delivery.projections import ReportSelectionOption
from travel_agent.planning.delivery.projections import ReportSelectionSection
from travel_agent.planning.delivery.projections import ReportWeatherDay
from travel_agent.planning.delivery.projections import TripReportDocument
from travel_agent.planning.delivery.projections import TripReportProjection
from travel_agent.planning.delivery.travel_content import candidate_reason_fallback
from travel_agent.planning.delivery.travel_content import preparation_actions
from travel_agent.planning.delivery.travel_content import public_selection_text
from travel_agent.planning.delivery.travel_content import selection_reason
from travel_agent.planning.itinerary.models import CustomBlock
from travel_agent.planning.itinerary.models import DiningStop
from travel_agent.planning.itinerary.models import LodgingStay
from travel_agent.planning.itinerary.models import StructuredItineraryV2
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.itinerary.models import VisitStop
from travel_agent.planning.itinerary.options import SelectionOption
from travel_agent.planning.itinerary.options import SelectionSlot
from travel_agent.planning.references import EntityRef
from travel_agent.planning.references import EntityType
from travel_agent.planning.requirements.place_names import (
    CONTROLLED_DESTINATION_ANCHOR_PREFIX,
)
from travel_agent.planning.requirements.place_names import controlled_public_place_name
from travel_agent.planning.requirements.route_legs import (
    build_required_long_distance_legs,
)
from travel_agent.planning.requirements.route_legs import (
    missing_long_distance_leg_roles,
)
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.planning.research.evidence import FactStoreSnapshot
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.planning.weather.models import WeatherDayContext
from travel_agent.planning.workspace import TripWorkspaceV2
from travel_agent.tools.temporal import RAIL_LIVE_INVENTORY_DAYS
from typing import Mapping
from typing import Sequence


def _reportable_selection_options(
    slots: Sequence[SelectionSlot],
) -> list[list[SelectionOption]]:
    """保留每个待决策项，但同一未选候选只发布一次。

    Workspace 的 selection slot 与上下文相关，同一候选可以合法出现在多个位置；
    报告中的「其它合格选择」是平铺列表，重复出现即为重复内容。已在行程中选中的
    候选同样不算「其它」。该过滤只作用于投影层。
    """

    selected_candidate_ids = {
        option.candidate_id
        for slot in slots
        for option in slot.options
        if option.option_id == slot.selected_option_id
    }
    projected_alternative_candidate_ids: set[str] = set()
    result: list[list[SelectionOption]] = []
    for slot in slots:
        reportable: list[SelectionOption] = []
        for option in slot.options:
            is_selected = option.option_id == slot.selected_option_id
            if not is_selected and (
                option.candidate_id in selected_candidate_ids
                or option.candidate_id in projected_alternative_candidate_ids
            ):
                continue
            reportable.append(option)
            if not is_selected:
                projected_alternative_candidate_ids.add(option.candidate_id)
        result.append(reportable)
    return result


_PUBLIC_COMPARISON_LABELS = {
    "branch_name": "具体餐厅",
    "property_name": "具体住宿",
    "place_id": "实体身份已核验",
    "provider_place_type": "实体类型已核验",
    "provider_country_code": "所在国家或地区已核验",
    "address": "地址",
    "average_spend_cny": "人均消费",
    "nightly_price_cny": "每晚价格",
    "total_price_cny": "总价",
    "facilities": "设施",
    "opening_window": "营业时间",
    "reservation_required": "预约要求",
}


_BOOKING_CONFIRMATION_TITLE_MARKERS = (
    "预订确认",
    "预订确认单",
    "确认单",
    "booking confirmation",
    "reservation confirmation",
)


def _public_selection_text(value: str) -> str:
    """保留模型的选点理由，同时隐藏编排用词。"""
    return public_selection_text(value)


def _public_comparison_facts(field_paths: Sequence[str]) -> list[str]:
    labels: list[str] = []
    for field_path in field_paths:
        label = _PUBLIC_COMPARISON_LABELS.get(field_path)
        if label and label not in labels:
            labels.append(label)
    return labels or ["实体与来源已核验"]


def _trip_level_requirements(workspace: TripWorkspaceV2) -> list[str]:
    categories = {
        "budget_cap",
        "elderly_mobility",
        "health_condition",
        "pace_preference",
    }
    requirements: list[str] = []
    for anchor in workspace.user_input_anchors:
        if anchor.input_kind != "hard_constraint" or not isinstance(
            anchor.value, Mapping
        ):
            continue
        if str(anchor.value.get("category") or "") not in categories:
            continue
        if anchor.public_summary and anchor.public_summary not in requirements:
            requirements.append(anchor.public_summary)
    return requirements


_LONG_DISTANCE_GAP_NOTES = {
    ("outbound", "return"): "本方案不含往返出发地的长途交通。",
    ("outbound",): "本方案不含前往目的地的长途交通。",
    ("return",): "本方案不含返回出发地的长途交通。",
}


_UNBOUND_LONG_DISTANCE_NOTE = "长途交通路径未绑定具体班次，仅作可行性参考。"


def _controlled_trip_identity(
    workspace: TripWorkspaceV2,
) -> Mapping[str, object] | None:
    """返回每个已组合 Workspace 携带的 Draft 行程身份。"""

    for anchor in workspace.user_input_anchors:
        if (
            anchor.input_kind == "controlled_identity"
            and anchor.field_path == "controlled_trip_identity"
            and isinstance(anchor.value, Mapping)
        ):
            return anchor.value
    return None


def _long_distance_legs_by_date(
    itinerary: StructuredItineraryV2,
) -> dict[date, list[TransportLeg]]:
    """按投影所在 Day 索引已交付的长途交通段。

    ``StructuredItineraryV2.validate_references`` 已要求每个长途段落在承载其
    服务日期的 Day 上，因此从 Day 时间线读取服务日期即可。
    """

    legs = {
        leg.transport_leg_id: leg
        for leg in itinerary.transport_legs
        if leg.transport_class == "long_distance"
    }
    by_date: dict[date, list[TransportLeg]] = {}
    for day in itinerary.day_plans:
        for ref in day.timeline:
            if ref.entity_type != EntityType.TRANSPORT_LEG:
                continue
            leg = legs.get(ref.entity_id)
            if leg is not None:
                by_date.setdefault(day.date, []).append(leg)
    return by_date


def _long_distance_path_notes(
    workspace: TripWorkspaceV2, generated_at: datetime
) -> list[str]:
    """在往返缺少可用路径或路径未绑定班次时给出提示。

    必需的交通段由 ``build_required_long_distance_legs`` 判定，报告不会增加该
    Run 未承担的责任；这里只读取每段的 ``leg_role``/``service_date``，不参考与
    具体交通段无关的 ``cross_day_return_required``。哪些段未交付由
    ``missing_long_distance_leg_roles`` 统一判定。
    """

    identity = _controlled_trip_identity(workspace)
    if identity is None:
        return []
    required = build_required_long_distance_legs(
        identity, cross_day_return_required=False
    )
    itinerary = workspace.itinerary
    delivered = _long_distance_legs_by_date(itinerary)
    missing = missing_long_distance_leg_roles(
        required,
        day_dates={day.date for day in itinerary.day_plans},
        dates_with_long_distance=set(delivered),
    )
    if missing is None:
        return []

    unbound = False
    for leg in required:
        on_date = delivered.get(leg.service_date, [])
        if on_date and all(
            item.lineage.lineage_kind != "candidate_entity" for item in on_date
        ):
            unbound = True

    notes: list[str] = []
    gap_note = _LONG_DISTANCE_GAP_NOTES.get(tuple(missing))
    if gap_note is not None:
        notes.append(gap_note)
    lead_days = (itinerary.day_plans[0].date - generated_at.date()).days
    if unbound and lead_days >= RAIL_LIVE_INVENTORY_DAYS:
        notes.append(_UNBOUND_LONG_DISTANCE_NOTE)
    return notes


def _report_destinations(workspace: TripWorkspaceV2) -> list[ReportDestination]:
    """把每个内部目的地 id 解析为受控的公开地名。

    公开地名取 anchor 的 ``name`` 而非 provider 的 ``display_name``：后者是
    ``深圳市, 广东省, 中国`` 这样的完整行政路径，不适合作为报告封面、每日标题
    和天气行的主语。需要消歧时可继续读取 anchor 上的 ``admin_path``。
    """

    names: dict[str, str] = {}
    for anchor in workspace.user_input_anchors:
        if (
            anchor.input_kind != "controlled_identity"
            or not anchor.field_path.startswith(CONTROLLED_DESTINATION_ANCHOR_PREFIX)
            or not isinstance(anchor.value, Mapping)
        ):
            continue
        destination_id = str(anchor.value.get("place_id") or "").strip()
        public_name = controlled_public_place_name(anchor.value)
        if not destination_id or not public_name:
            raise DeliveryProjectionError(
                "controlled destination anchor requires place_id and name"
            )
        existing = names.get(destination_id)
        if existing is not None and existing != public_name:
            raise DeliveryProjectionError(
                f"conflicting public destination identity: {destination_id}"
            )
        names[destination_id] = public_name

    missing = [
        item for item in workspace.itinerary.destination_ids if item not in names
    ]
    if missing:
        raise DeliveryProjectionError(
            f"report destinations are missing controlled public identities: {missing}"
        )
    return [
        ReportDestination(destination_id=item, display_name=names[item])
        for item in workspace.itinerary.destination_ids
    ]


def _destination_name(
    destination_names: Mapping[str, str], destination_id: str | None
) -> str:
    if destination_id is None or destination_id not in destination_names:
        raise DeliveryProjectionError(
            f"public report references an unknown destination: {destination_id}"
        )
    return destination_names[destination_id]


def _weather_observed_at(
    day: WeatherDayContext,
    fact_index: Mapping[str, FactAssertion],
    snapshot_retrieved_at: datetime,
) -> datetime | None:
    """该 Day 天气的实际观测时间。

    优先取逐字段断言携带的 provider 检索时间；断言不在本快照中时退回快照的检索
    时间。没有天气数据的 Day 返回 ``None``。
    """

    if day.data_kind == "unavailable":
        return None
    observations = [
        fact.observed_at
        for assertion_id in day.fact_assertion_ids
        if (fact := fact_index.get(assertion_id)) is not None
        and fact.observed_at is not None
    ]
    return max(observations) if observations else snapshot_retrieved_at


def _weather_data_state(
    day: WeatherDayContext, historical_days: frozenset[tuple[str, date]]
) -> str:
    """判断 Day 展示当前天气还是历史数据，只在此处判定一次。

    三种情况都表示数据并非本次刷新所得：月度气候基线不是出行日期的预报；
    provider 不可用的 Day 保留上一快照的值；本次刷新未重新评估的天气影响保留
    上一快照的结论。后两种情况只在产生快照的那次调用内由 refresh 传入，不写入
    状态。三个渲染方共用此判定，避免 workspace 徽标、报告和 PDF 对同一 Day
    给出不同结论。
    """

    if day.data_kind == "seasonal_baseline":
        return "historical"
    return (
        "historical" if (day.destination_id, day.date) in historical_days else "current"
    )


def _public_report_title(title: str) -> str:
    """避免正式交付文档的标题被读作预订记录。"""

    if any(
        marker in title.casefold() for marker in _BOOKING_CONFIRMATION_TITLE_MARKERS
    ):
        return "旅行计划"
    return title


def _entity_block(
    entity: object,
    citation_ids: Sequence[str],
    entry_id: str,
    projection_role: str,
) -> ReportEntityBlock:
    if isinstance(entity, VisitStop):
        ref = EntityRef(entity_type=EntityType.VISIT_STOP, entity_id=entity.item_id)
        kind = "visit"
        summary = selection_reason(entity)
        day_id = entity.day_id
    elif isinstance(entity, DiningStop):
        ref = EntityRef(entity_type=EntityType.DINING_STOP, entity_id=entity.item_id)
        kind = "dining"
        summary = selection_reason(entity)
        day_id = entity.day_id
    elif isinstance(entity, LodgingStay):
        ref = EntityRef(entity_type=EntityType.LODGING_STAY, entity_id=entity.stay_id)
        kind = "lodging"
        summary = selection_reason(entity)
        day_id = None
    elif isinstance(entity, TransportLeg):
        ref = EntityRef(
            entity_type=EntityType.TRANSPORT_LEG, entity_id=entity.transport_leg_id
        )
        kind = "transport"
        summary = f"{entity.from_endpoint.name} → {entity.to_endpoint.name}"
        day_id = None
    elif isinstance(entity, CustomBlock):
        ref = EntityRef(entity_type=EntityType.CUSTOM_BLOCK, entity_id=entity.item_id)
        kind = "custom"
        summary = entity.note or entity.title
        day_id = entity.day_id
    else:
        raise DeliveryProjectionError(
            f"unsupported report entity: {type(entity).__name__}"
        )
    payload = entity.model_dump(mode="json", exclude={"lineage", "type"})
    if "selection_reason" in payload:
        payload["selection_reason"] = selection_reason(entity)
    if "intent_explanations" in payload:
        payload["intent_explanations"] = [
            {
                "label": item.label,
                "explanation": item.explanation,
                "evidence_basis": item.evidence_basis,
            }
            for item in getattr(entity, "intent_explanations", [])
        ]
    for field in ("item_id", "stay_id", "transport_leg_id", "day_id", "name"):
        payload.pop(field, None)
    if isinstance(entity, LodgingStay) and projection_role == "check_out":
        summary = f"从 {entity.name} 办理退房"
        payload = {key: payload[key] for key in ("check_out_date", "check_out_time")}
    elif isinstance(entity, LodgingStay) and projection_role == "check_in":
        summary = f"入住 {entity.name}，覆盖 {entity.nights} 晚"
    elif isinstance(entity, TransportLeg) and projection_role == "departure":
        summary = f"从 {entity.from_endpoint.name} 出发"
    elif isinstance(entity, TransportLeg) and projection_role == "arrival":
        summary = f"抵达 {entity.to_endpoint.name}"
        payload = {key: payload[key] for key in ("selected_mode", "arrival_at")}

    rendered = block_presentation(
        entity, entry_id=entry_id, projection_role=projection_role
    )
    payload.update(rendered)
    lineage = getattr(entity, "lineage", None)
    return ReportEntityBlock(
        entity_ref=ref,
        day_id=day_id,
        projection_role=projection_role,
        title=rendered["display_title"],
        entity_kind=kind,
        summary=summary,
        details=payload,
        citation_ids=list(citation_ids),
        weather_impact_ids=(
            getattr(lineage, "weather_impact_ids", []) if lineage is not None else []
        ),
        personalization_influence_ids=(
            getattr(lineage, "personalization_influence_ids", [])
            if lineage is not None
            else []
        ),
    )


def _preparation_notes(itinerary: StructuredItineraryV2) -> list[str]:
    """补充时间线与实体块没有呈现的行程级信息。"""
    notes: list[str] = []
    for entity in [
        *itinerary.visit_stops,
        *itinerary.dining_stops,
        *itinerary.lodging_stays,
        *itinerary.transport_legs,
    ]:
        name = (
            f"{entity.from_endpoint.name} → {entity.to_endpoint.name}"
            if isinstance(entity, TransportLeg)
            else entity.name
        )
        notes.extend(f"{name}：{action}" for action in preparation_actions(entity))
    missing = [
        *(
            stop.name
            for stop in itinerary.visit_stops
            if stop.estimated_cost_cny is None
        ),
        *(
            stop.name
            for stop in itinerary.dining_stops
            if stop.estimated_cost_cny is None
        ),
        *(
            stay.name
            for stay in itinerary.lodging_stays
            if stay.total_price_cny is None
        ),
        *(
            f"{leg.from_endpoint.name} → {leg.to_endpoint.name}"
            for leg in itinerary.transport_legs
            if leg.total_cost_cny is None
        ),
    ]
    if missing:
        notes.append(
            "以下费用暂未核实或纳入预算，请向相关商家核对确认："
            f"{'、'.join(dict.fromkeys(missing))}。"
        )
    if any(
        stay.price_kind == "reference_estimate" and stay.total_price_cny is not None
        for stay in itinerary.lodging_stays
    ):
        notes.append("费用小计中的住宿为参考估价。")
    return notes


def project_report(
    workspace: TripWorkspaceV2,
    facts: FactStoreSnapshot,
    weather: WeatherContextSnapshot,
    *,
    generated_at: datetime,
    historical_weather_days: frozenset[tuple[str, date]] = frozenset(),
) -> TripReportProjection:
    citations = project_public_citations(workspace, facts, weather)
    citation_by_fact, citations_by_entity = _citation_lookup(citations)
    fact_index = {item.fact_assertion_id: item for item in facts.fact_assertions}
    itinerary = workspace.itinerary
    destinations = _report_destinations(workspace)
    destination_names = {
        item.destination_id: item.display_name for item in destinations
    }
    entities: dict[tuple[EntityType, str], object] = {}
    for item in itinerary.visit_stops:
        entities[(EntityType.VISIT_STOP, item.item_id)] = item
    for item in itinerary.dining_stops:
        entities[(EntityType.DINING_STOP, item.item_id)] = item
    for item in itinerary.lodging_stays:
        entities[(EntityType.LODGING_STAY, item.stay_id)] = item
    for item in itinerary.transport_legs:
        entities[(EntityType.TRANSPORT_LEG, item.transport_leg_id)] = item
    for item in itinerary.custom_blocks:
        entities[(EntityType.CUSTOM_BLOCK, item.item_id)] = item
    days: list[ReportDaySection] = []
    for day in itinerary.day_plans:
        blocks: list[ReportEntityBlock] = []
        for ref in day.timeline:
            entity = entities.get((ref.entity_type, ref.entity_id))
            if entity is None:
                raise DeliveryProjectionError(
                    f"report timeline reference is missing: {ref.entity_id}"
                )
            blocks.append(
                _entity_block(
                    entity,
                    citations_by_entity.get(ref.entity_id, []),
                    ref.entry_id,
                    ref.projection_role,
                )
            )
        days.append(
            ReportDaySection(
                day_id=day.day_id,
                day=day.day,
                date=day.date,
                destination_id=day.destination_id,
                destination_name=_destination_name(
                    destination_names, day.destination_id
                ),
                theme=day.theme,
                blocks=blocks,
            )
        )

    candidates = workspace.recommendation_catalog.candidate_index()
    selections: list[ReportSelectionSection] = []
    reportable_options = _reportable_selection_options(workspace.selection_slots)
    for slot, slot_options in zip(workspace.selection_slots, reportable_options):
        options: list[ReportSelectionOption] = []
        for option in slot_options:
            is_selected = option.option_id == slot.selected_option_id
            citation_entity_id = (
                slot.target_entity_id if is_selected else option.candidate_id
            )
            option_citations = [
                citation_by_fact[f"{citation_entity_id}:{fact_id}"]
                for fact_id in option.fact_assertion_ids
            ]
            options.append(
                ReportSelectionOption(
                    option_id=option.option_id,
                    candidate_id=option.candidate_id,
                    name=candidate_display_name(candidates[option.candidate_id]),
                    rank=option.rank,
                    selected=is_selected,
                    recommended=option.option_id == slot.recommended_option_id,
                    selection_reasons=[
                        public_selection_text(
                            reason,
                            fallback=candidate_reason_fallback(
                                candidates[option.candidate_id], index
                            ),
                        )
                        for index, reason in enumerate(option.selection_reasons)
                    ],
                    tradeoff=(
                        _public_selection_text(option.tradeoff)
                        if option.tradeoff
                        else None
                    ),
                    comparison_facts=_public_comparison_facts(option.comparison_facts),
                    availability_status=option.availability_status,
                    citation_ids=option_citations,
                )
            )
        selections.append(
            ReportSelectionSection(
                selection_slot_id=slot.selection_slot_id,
                slot_type=slot.slot_type,
                context=slot.context,
                status="needs_user_decision"
                if slot.status == "needs_user_decision"
                else "ready",
                options=options,
            )
        )

    weather_days = [
        ReportWeatherDay(
            destination_id=day.destination_id,
            destination_name=_destination_name(destination_names, day.destination_id),
            date=day.date,
            data_kind=day.data_kind,
            observed_at=_weather_observed_at(day, fact_index, weather.retrieved_at),
            weather_data_state=_weather_data_state(day, historical_weather_days),
            condition_label=day.condition_label,
            high_c=day.high_c,
            low_c=day.low_c,
            precipitation_probability_pct=day.precipitation_probability_pct,
            wind_speed_kph=day.wind_speed_kph,
            citation_ids=[
                citation_by_fact[
                    f"weather:{day.destination_id}:{day.date.isoformat()}:{fact_id}"
                ]
                for fact_id in day.fact_assertion_ids
            ],
        )
        for day in weather.days
    ]
    start = itinerary.day_plans[0].date
    end = itinerary.day_plans[-1].date
    date_text = (
        f"{start.isoformat()} 至 {end.isoformat()}"
        if start and end
        else f"{itinerary.duration_days} 天"
    )
    destination_text = "、".join(item.display_name for item in destinations)
    document = TripReportDocument(
        title=_public_report_title(
            f"{destination_text} {itinerary.duration_days} 日旅行计划"
        ),
        overview=f"{date_text}，前往{destination_text}的旅行计划。",
        destinations=destinations,
        duration_days=itinerary.duration_days,
        cost_summary=itinerary.cost_summary.model_copy(
            update={"llm_estimated_total_cny": None}
        ),
        cost_coverage_statement=cost_coverage_statement(itinerary.cost_summary),
        days=days,
        selections=selections,
        weather=weather_days,
        highlights=itinerary.highlights,
        important_notes=list(
            dict.fromkeys(
                [
                    *_trip_level_requirements(workspace),
                    *_long_distance_path_notes(workspace, generated_at),
                    *_preparation_notes(itinerary),
                    *itinerary.important_notes,
                ]
            )
        ),
    )
    return TripReportProjection(
        source_workspace_revision=workspace.workspace_revision,
        source_fact_data_revision=facts.fact_data_revision,
        source_weather_data_revision=weather.weather_data_revision,
        status="ready",
        document=document,
        citations=citations,
        generated_at=generated_at,
    )
