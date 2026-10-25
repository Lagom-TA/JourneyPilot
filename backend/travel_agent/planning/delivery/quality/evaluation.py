"""Planning delivery quality evaluation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, Mapping

from travel_agent.planning.itinerary.lodging_bases import day_lodging_bases
from travel_agent.planning.itinerary.models import TimelineEntryRef
from travel_agent.planning.itinerary.options import SelectionSlot
from travel_agent.planning.outcomes import (
    DeliveryQualityGap,
    GateClass,
    GateDisposition,
    GateFailureAttribution,
    RecommendationQualityState,
)
from travel_agent.planning.references import EntityType
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.state import TravelAgentState


def _gap_id(reason: str, field_path: str, entity_id: str | None) -> str:
    digest = hashlib.sha256(
        f"{reason}|{field_path}|{entity_id or ''}".encode()
    ).hexdigest()[:18]
    return f"delivery_gap_{digest}"


def _gap(
    *,
    gate: str,
    reason: str,
    field_path: str,
    retry_target: str,
    entity_id: str | None = None,
    candidate_id: str | None = None,
    worker_kind: str | None = None,
    repair_context: dict[str, Any] | None = None,
    blocking: bool = True,
    gate_class: GateClass | None = None,
    research_domain: ResearchDomain | None = None,
) -> DeliveryQualityGap:
    inferred = gate_class or GateClass.COMPOSITION
    return DeliveryQualityGap(
        gap_id=_gap_id(reason, field_path, entity_id),
        gate=gate,
        reason=reason,
        field_path=field_path,
        retry_target=retry_target,
        entity_id=entity_id,
        candidate_id=candidate_id,
        worker_kind=worker_kind,
        repair_context=repair_context or {},
        gate_class=inferred,
        research_domain=research_domain,
        blocking=blocking,
    )


def _attribution(
    state: TravelAgentState,
    *,
    gate_class: GateClass,
    disposition: GateDisposition,
    reason_code: str,
    gaps: list[DeliveryQualityGap],
) -> Dict[str, GateFailureAttribution]:
    records = dict(state.gate_failure_attributions or {})
    draft_id = (
        state.minimum_delivery_draft.draft_id if state.minimum_delivery_draft else None
    )
    grouped: dict[ResearchDomain | None, list[DeliveryQualityGap]] = {}
    for gap in gaps:
        grouped.setdefault(gap.research_domain, []).append(gap)
    for domain, scoped_gaps in grouped.items():
        gap_ids = sorted({gap.gap_id for gap in scoped_gaps})
        material = "|".join(
            [
                draft_id or "",
                gate_class.value,
                disposition.value,
                reason_code,
                domain.value if domain else "",
                *gap_ids,
            ]
        )
        attribution_id = (
            f"gate_failure_{hashlib.sha256(material.encode()).hexdigest()[:24]}"
        )
        records[attribution_id] = GateFailureAttribution(
            attribution_id=attribution_id,
            draft_id=draft_id,
            gate_class=gate_class,
            disposition=disposition,
            reason_code=reason_code,
            research_domain=domain,
            gap_ids=gap_ids,
            recorded_at=datetime.now(timezone.utc),
        )
    return records


def _slot_research_domain(
    slot: SelectionSlot, leg_classes: Mapping[str, str]
) -> ResearchDomain:
    """Name the research domain a slot's gap actually came from."""

    if slot.slot_type != "transport":
        return ResearchDomain(slot.slot_type)
    return (
        ResearchDomain.LONG_DISTANCE_TRANSPORT
        if leg_classes.get(slot.target_entity_id) == "long_distance"
        else ResearchDomain.LOCAL_TRANSPORT
    )


def _slot_gaps(state: TravelAgentState) -> list[DeliveryQualityGap]:
    """Record selection-slot shape. A slot projects whatever options it holds."""

    workspace = state.trip_workspace_v2
    if workspace is None:
        return []
    gaps: list[DeliveryQualityGap] = []
    leg_classes = {
        leg.transport_leg_id: leg.transport_class
        for leg in workspace.itinerary.transport_legs
    }
    for slot in workspace.selection_slots:
        domain = _slot_research_domain(slot, leg_classes)
        if not 1 <= len(slot.options) <= 3:
            gaps.append(
                _gap(
                    gate="slot",
                    reason="slot_option_count",
                    field_path=f"selection_slots.{slot.selection_slot_id}.options",
                    retry_target="composition_repair",
                    entity_id=slot.selection_slot_id,
                    blocking=False,
                    gate_class=GateClass.COMPOSITION,
                    research_domain=domain,
                )
            )
            continue
        comparison_sets = {
            tuple(sorted(option.comparison_facts)) for option in slot.options
        }
        if len(comparison_sets) != 1:
            gaps.append(
                _gap(
                    gate="slot",
                    reason="slot_comparison_mismatch",
                    field_path=f"selection_slots.{slot.selection_slot_id}.options.comparison_facts",
                    retry_target="composition_repair",
                    entity_id=slot.selection_slot_id,
                    blocking=False,
                    gate_class=GateClass.COMPOSITION,
                    research_domain=domain,
                )
            )
    return gaps


def _itinerary_gaps(state: TravelAgentState) -> list[DeliveryQualityGap]:
    """Classify itinerary composition."""

    workspace = state.trip_workspace_v2
    if workspace is None:
        return []
    itinerary = workspace.itinerary
    gaps: list[DeliveryQualityGap] = []
    dates = [day.date for day in itinerary.day_plans]
    for day in itinerary.day_plans:
        if not day.timeline:
            gaps.append(
                _gap(
                    gate="itinerary",
                    reason="day_timeline_missing",
                    field_path=f"itinerary.day_plans.{day.day_id}.timeline",
                    retry_target="composition_repair",
                    entity_id=day.day_id,
                    blocking=False,
                    gate_class=GateClass.COMPOSITION,
                )
            )
    for index in range(1, len(dates)):
        if dates[index] != dates[index - 1] + timedelta(days=1):
            gaps.append(
                _gap(
                    gate="itinerary",
                    reason="day_date_discontinuity",
                    field_path=f"itinerary.day_plans.{index}.date",
                    retry_target="composition_repair",
                    entity_id=itinerary.day_plans[index].day_id,
                    gate_class=GateClass.COMPOSITION,
                )
            )

    if len(dates) > 1:
        covered_nights = {
            stay.check_in_date + timedelta(days=offset)
            for stay in itinerary.lodging_stays
            for offset in range(stay.nights)
        }
        for night in dates[:-1]:
            if night not in covered_nights:
                gaps.append(
                    _gap(
                        gate="itinerary",
                        reason="missing_lodging_night",
                        field_path=f"itinerary.lodging_stays[{night.isoformat()}]",
                        retry_target="composition_repair",
                        entity_id=night.isoformat(),
                        blocking=False,
                        gate_class=GateClass.COMPOSITION,
                        research_domain=ResearchDomain.LODGING,
                    )
                )

    dining_day_ids = {stop.day_id for stop in itinerary.dining_stops}
    for day in itinerary.day_plans:
        if day.day_id not in dining_day_ids:
            gaps.append(
                _gap(
                    gate="itinerary",
                    reason="missing_dining_day",
                    field_path=f"itinerary.dining_stops[{day.day_id}]",
                    retry_target="composition_repair",
                    entity_id=day.day_id,
                    blocking=False,
                    gate_class=GateClass.COMPOSITION,
                    research_domain=ResearchDomain.DINING,
                )
            )

    physical_entities = {
        **{
            (EntityType.VISIT_STOP, item.item_id): item
            for item in itinerary.visit_stops
        },
        **{
            (EntityType.DINING_STOP, item.item_id): item
            for item in itinerary.dining_stops
        },
        **{
            (EntityType.LODGING_STAY, item.stay_id): item
            for item in itinerary.lodging_stays
        },
    }
    transport_index = {item.transport_leg_id: item for item in itinerary.transport_legs}
    physical_types = {
        EntityType.VISIT_STOP,
        EntityType.DINING_STOP,
        EntityType.LODGING_STAY,
    }
    for day in itinerary.day_plans:
        previous_physical: tuple[EntityType, Any] | None = None
        local_connectors = []
        morning_base, evening_base = day_lodging_bases(itinerary, day)
        refs = list(day.timeline)
        present_stays = {
            ref.entity_id for ref in refs if ref.entity_type == EntityType.LODGING_STAY
        }
        if morning_base is not None and morning_base.stay_id not in present_stays:
            refs.insert(
                0,
                TimelineEntryRef(
                    entry_id=f"implicit_morning_{morning_base.stay_id}_{day.day_id}",
                    entity_type=EntityType.LODGING_STAY,
                    entity_id=morning_base.stay_id,
                    projection_role="check_out",
                ),
            )
        if evening_base is not None and evening_base.stay_id not in present_stays:
            refs.append(
                TimelineEntryRef(
                    entry_id=f"implicit_evening_{evening_base.stay_id}_{day.day_id}",
                    entity_type=EntityType.LODGING_STAY,
                    entity_id=evening_base.stay_id,
                    projection_role="check_in",
                )
            )
        for ref in refs:
            if ref.entity_type == EntityType.TRANSPORT_LEG:
                leg = transport_index.get(ref.entity_id)
                if leg and leg.transport_class in {"public_transit", "flexible"}:
                    local_connectors.append(leg)
                elif leg and leg.transport_class == "long_distance":
                    if (
                        ref.projection_role != "arrival"
                        and previous_physical is not None
                    ):
                        previous_entity = previous_physical[1]
                        if (
                            previous_entity.place_id != leg.from_endpoint.place_id
                            and not any(
                                route.route_status == "ready"
                                and route.from_endpoint.place_id
                                == previous_entity.place_id
                                and route.to_endpoint.place_id
                                == leg.from_endpoint.place_id
                                for route in local_connectors
                            )
                        ):
                            gaps.append(
                                _gap(
                                    gate="itinerary",
                                    reason="route_infeasible",
                                    field_path=f"itinerary.day_plans.{day.day_id}.timeline",
                                    retry_target="composition_repair",
                                    entity_id=ref.entity_id,
                                    gate_class=GateClass.COMPOSITION,
                                    research_domain=ResearchDomain.LOCAL_TRANSPORT,
                                )
                            )
                    previous_physical = (
                        None
                        if ref.projection_role == "departure"
                        else (
                            EntityType.TRANSPORT_LEG,
                            SimpleNamespace(
                                place_id=leg.to_endpoint.place_id,
                                name=leg.to_endpoint.name,
                                lineage=leg.lineage,
                            ),
                        )
                    )
                    local_connectors = []
            elif ref.entity_type in physical_types:
                current_physical = physical_entities.get(
                    (ref.entity_type, ref.entity_id)
                )
                if previous_physical is not None and current_physical is not None:
                    _, previous_entity = previous_physical

                    if previous_entity.place_id == current_physical.place_id:
                        previous_physical = (ref.entity_type, current_physical)
                        local_connectors = []
                        continue
                    has_ready_exact_connector = any(
                        leg.route_status == "ready"
                        and leg.from_endpoint.place_id == previous_entity.place_id
                        and leg.to_endpoint.place_id == current_physical.place_id
                        for leg in local_connectors
                    )
                    if local_connectors and not has_ready_exact_connector:
                        leg = local_connectors[-1]
                        gaps.append(
                            _gap(
                                gate="itinerary",
                                reason="route_endpoint_mismatch",
                                field_path=f"itinerary.transport_legs.{leg.transport_leg_id}.endpoints",
                                retry_target="composition_repair",
                                entity_id=leg.transport_leg_id,
                                candidate_id=leg.lineage.candidate_id,
                                worker_kind="transport_researcher",
                                repair_context={
                                    "from_entity_id": getattr(
                                        previous_entity,
                                        "item_id",
                                        getattr(previous_entity, "stay_id", None),
                                    ),
                                    "from_candidate_id": previous_entity.lineage.candidate_id,
                                    "from_place_id": previous_entity.place_id,
                                    "from_name": getattr(
                                        previous_entity,
                                        "name",
                                        getattr(previous_entity, "property_name", None),
                                    ),
                                    "to_entity_id": getattr(
                                        current_physical,
                                        "item_id",
                                        getattr(current_physical, "stay_id", None),
                                    ),
                                    "to_candidate_id": current_physical.lineage.candidate_id,
                                    "to_place_id": current_physical.place_id,
                                    "to_name": getattr(
                                        current_physical,
                                        "name",
                                        getattr(
                                            current_physical, "property_name", None
                                        ),
                                    ),
                                },
                                blocking=True,
                                gate_class=GateClass.COMPOSITION,
                                research_domain=ResearchDomain.LOCAL_TRANSPORT,
                            )
                        )
                    elif not local_connectors:
                        gaps.append(
                            _gap(
                                gate="itinerary",
                                reason="route_infeasible",
                                field_path=f"itinerary.day_plans.{day.day_id}.timeline",
                                retry_target="composition_repair",
                                entity_id=ref.entity_id,
                                blocking=True,
                                gate_class=GateClass.COMPOSITION,
                                research_domain=ResearchDomain.LOCAL_TRANSPORT,
                            )
                        )
                if current_physical is not None:
                    previous_physical = (ref.entity_type, current_physical)
                local_connectors = []

    for index in range(1, len(itinerary.day_plans)):
        previous = itinerary.day_plans[index - 1]
        current = itinerary.day_plans[index]
        if previous.destination_id == current.destination_id:
            continue
        transition_legs = [
            transport_index[ref.entity_id]
            for day in (previous, current)
            for ref in day.timeline
            if ref.entity_type == EntityType.TRANSPORT_LEG
            and ref.entity_id in transport_index
        ]
        if not any(leg.transport_class == "long_distance" for leg in transition_legs):
            gaps.append(
                _gap(
                    gate="itinerary",
                    reason="destination_transfer_missing",
                    field_path=f"itinerary.day_plans.{current.day_id}.timeline",
                    retry_target="composition_repair",
                    entity_id=current.day_id,
                    gate_class=GateClass.COMPOSITION,
                    research_domain=ResearchDomain.LONG_DISTANCE_TRANSPORT,
                )
            )
    return gaps


def _source_weather_gaps(state: TravelAgentState) -> list[DeliveryQualityGap]:
    """Record source and weather coverage per entity."""

    workspace = state.trip_workspace_v2
    if workspace is None:
        return []
    catalog = workspace.recommendation_catalog
    packet_by_candidate = {
        candidate.candidate_id: packet
        for packet in catalog.research_packets
        for candidate in packet.candidates
    }

    catalog_fact_ids = {
        fact.fact_assertion_id
        for packet in catalog.research_packets
        for fact in packet.fact_assertions
    }
    catalog_source_ids = {
        source.source_record_id
        for packet in catalog.research_packets
        for source in packet.source_records
    }
    weather_facts = {fact.fact_assertion_id for fact in state.weather_fact_assertions}
    impacts = state.weather_impacts
    gaps: list[DeliveryQualityGap] = []
    entities = [
        *workspace.itinerary.visit_stops,
        *workspace.itinerary.dining_stops,
        *workspace.itinerary.lodging_stays,
        *workspace.itinerary.transport_legs,
    ]
    for entity in entities:
        if entity.lineage.lineage_kind != "candidate_entity":
            continue
        candidate_id = entity.lineage.candidate_id
        packet = packet_by_candidate.get(candidate_id)
        if packet is None:
            gaps.append(
                _gap(
                    gate="integrity",
                    reason="catalog_missing",
                    field_path=f"entities.{candidate_id}",
                    retry_target="composition_repair",
                    entity_id=getattr(
                        entity,
                        "item_id",
                        getattr(
                            entity, "stay_id", getattr(entity, "transport_leg_id", None)
                        ),
                    ),
                    gate_class=GateClass.COMPOSITION,
                )
            )
            continue
        facts = {fact.fact_assertion_id: fact for fact in packet.fact_assertions}
        sources = {source.source_record_id for source in packet.source_records}
        candidate = next(
            (item for item in packet.candidates if item.candidate_id == candidate_id),
            None,
        )
        domain = {
            "visit": ResearchDomain.VISIT,
            "dining": ResearchDomain.DINING,
            "lodging": ResearchDomain.LODGING,
            "transport": ResearchDomain.LOCAL_TRANSPORT,
        }.get(candidate.candidate_kind if candidate is not None else "")
        if (
            candidate is not None
            and getattr(candidate, "transport_class", None) == "long_distance"
        ):
            domain = ResearchDomain.LONG_DISTANCE_TRANSPORT
        for fact_id in entity.lineage.fact_assertion_ids:
            fact = facts.get(fact_id)
            if fact is None or fact.status != "verified":
                gaps.append(
                    _gap(
                        gate="source_weather",
                        reason="fact_not_verified",
                        field_path=f"entities.{candidate_id}.facts.{fact_id}",
                        retry_target="composition_repair",
                        entity_id=getattr(
                            entity,
                            "item_id",
                            getattr(
                                entity,
                                "stay_id",
                                getattr(entity, "transport_leg_id", None),
                            ),
                        ),
                        candidate_id=candidate_id,
                        worker_kind=packet.worker_kind,
                        blocking=fact_id not in catalog_fact_ids,
                        gate_class=GateClass.COMPOSITION,
                        research_domain=domain,
                    )
                )
                continue
            unsourced = [
                link.source_record_id
                for link in fact.source_links
                if link.relation == "supports" and link.source_record_id not in sources
            ]
            if unsourced:
                gaps.append(
                    _gap(
                        gate="source_weather",
                        reason="source_missing",
                        field_path=f"entities.{candidate_id}.facts.{fact_id}.source_links",
                        retry_target="composition_repair",
                        entity_id=getattr(
                            entity,
                            "item_id",
                            getattr(
                                entity,
                                "stay_id",
                                getattr(entity, "transport_leg_id", None),
                            ),
                        ),
                        candidate_id=candidate_id,
                        worker_kind=packet.worker_kind,
                        blocking=any(
                            source_id not in catalog_source_ids
                            for source_id in unsourced
                        ),
                        gate_class=GateClass.COMPOSITION,
                        research_domain=domain,
                    )
                )
        for impact_id in entity.lineage.weather_impact_ids:
            impact = impacts.get(impact_id)
            if impact is None or not set(impact.fact_assertion_ids) <= weather_facts:
                gaps.append(
                    _gap(
                        gate="source_weather",
                        reason="weather_lineage_missing",
                        field_path=f"entities.{candidate_id}.weather_impact_ids.{impact_id}",
                        retry_target="composition_repair",
                        entity_id=getattr(
                            entity,
                            "item_id",
                            getattr(
                                entity,
                                "stay_id",
                                getattr(entity, "transport_leg_id", None),
                            ),
                        ),
                        candidate_id=candidate_id,
                        worker_kind=packet.worker_kind,
                        blocking=False,
                        gate_class=GateClass.COMPOSITION,
                        research_domain=domain,
                    )
                )

    if state.weather_context is not None:
        for day in state.weather_context.days:
            if day.data_kind == "unavailable":
                gaps.append(
                    _gap(
                        gate="source_weather",
                        reason="weather_unavailable_refreshable",
                        field_path=f"weather.days.{day.destination_id}.{day.date.isoformat()}",
                        retry_target="composition_repair",
                        entity_id=f"{day.destination_id}:{day.date.isoformat()}",
                        blocking=False,
                        gate_class=GateClass.COMPOSITION,
                    )
                )
    return gaps


def evaluate_delivery_quality(
    state: TravelAgentState,
) -> tuple[RecommendationQualityState, list[DeliveryQualityGap]]:
    if state.trip_workspace_v2 is None or state.recommendation_catalog is None:
        missing = (
            "workspace_missing"
            if state.trip_workspace_v2 is None
            else "catalog_missing"
        )
        gap = _gap(
            gate="integrity",
            reason=missing,
            field_path=missing,
            retry_target="composition_repair",
            gate_class=GateClass.COMPOSITION,
        )
        return (
            RecommendationQualityState(
                schema_gate="failed",
                candidate_gate="passed",
                slot_gate="pending",
                itinerary_gate="pending",
                source_weather_gate="pending",
                active_gap_ids=[gap.gap_id],
            ),
            [gap],
        )
    slot = _slot_gaps(state)
    itinerary = _itinerary_gaps(state)
    source_weather = _source_weather_gaps(state)
    gaps = [*slot, *itinerary, *source_weather]
    quality = RecommendationQualityState(
        schema_gate="passed",
        candidate_gate="passed",
        slot_gate="failed" if any(gap.blocking for gap in slot) else "passed",
        itinerary_gate="failed" if any(gap.blocking for gap in itinerary) else "passed",
        source_weather_gate="failed"
        if any(gap.blocking for gap in source_weather)
        else "passed",
        active_gap_ids=[gap.gap_id for gap in gaps],
    )
    return quality, gaps
