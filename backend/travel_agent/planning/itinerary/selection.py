from __future__ import annotations

from typing import Mapping, Sequence

from travel_agent.planning.research.option_availability import candidate_option_availability
from travel_agent.planning.itinerary.draft import _stable_id
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.itinerary.options import (
    SELECTION_SLOT_ENTITY_TYPES,
    SelectionOption,
    SelectionSlot,
    SelectionSlotType,
)
from travel_agent.planning.references import EntityRef
from travel_agent.planning.research.candidates import (
    DiningCandidate,
    LodgingCandidate,
    ResearchCandidate,
    TransportCandidate,
    VisitCandidate,
)
from travel_agent.planning.transport_semantics import (
    replacement_display_mode,
    transport_mode_satisfies,
)


def _option(
    candidate: LodgingCandidate | DiningCandidate | VisitCandidate | TransportCandidate,
    *,
    slot_id: str,
    target_entity_id: str,
    rank: int,
) -> SelectionOption:
    entity_type = SELECTION_SLOT_ENTITY_TYPES[candidate.candidate_kind]
    availability_status = candidate_option_availability(candidate)
    return SelectionOption(
        option_id=_stable_id("option", slot_id, candidate.candidate_id),
        selection_slot_id=slot_id,
        candidate_id=candidate.candidate_id,
        candidate_entity_ref=EntityRef(
            entity_type=entity_type, entity_id=target_entity_id
        ),
        rank=rank,
        selection_reasons=candidate.selection_reasons,
        tradeoff=candidate.tradeoff,
        comparison_facts=candidate.field_paths,
        availability_status=availability_status,
        fact_assertion_ids=candidate.fact_assertion_ids,
        source_record_ids=candidate.source_record_ids,
        personalization_influence_ids=candidate.personalization_influence_ids,
    )


def _slot(
    *,
    selected: LodgingCandidate | DiningCandidate | VisitCandidate | TransportCandidate,
    eligible: Sequence[
        LodgingCandidate | DiningCandidate | VisitCandidate | TransportCandidate
    ],
    slot_id: str,
    target_entity_id: str,
    slot_type: SelectionSlotType,
    context: dict[str, object],
) -> SelectionSlot:
    ordered = [
        selected,
        *[item for item in eligible if item.candidate_id != selected.candidate_id],
    ][:3]
    options = [
        _option(item, slot_id=slot_id, target_entity_id=target_entity_id, rank=index)
        for index, item in enumerate(ordered, 1)
    ]
    selected_option_id = options[0].option_id
    return SelectionSlot(
        selection_slot_id=slot_id,
        slot_type=slot_type,
        target_entity_id=target_entity_id,
        context=context,
        options=options,
        recommended_option_id=selected_option_id,
        selected_option_id=selected_option_id,
        status="ready",
    )


def _transport_alternatives(
    leg: TransportLeg,
    candidates: Mapping[str, ResearchCandidate],
) -> list[TransportCandidate]:
    # 只提供满足本次变更范围、端点与交通方式规则的路线。
    preference = leg.mode_preference
    selected = candidates.get(leg.lineage.candidate_id or "")
    selected_scope_id = (
        selected.provider_evidence_scope_id
        if isinstance(selected, TransportCandidate)
        and selected.transport_class == "long_distance"
        else None
    )
    eligible: list[TransportCandidate] = []
    for candidate in candidates.values():
        if not isinstance(candidate, TransportCandidate):
            continue
        display_mode = replacement_display_mode(
            preference.locked_mode or leg.selected_mode, candidate.selected_mode
        )
        if (
            preference.locked_mode is not None
            and not transport_mode_satisfies(
                candidate.selected_mode, preference.locked_mode
            )
        ):
            continue
        if display_mode in preference.excluded_modes:
            continue
        if leg.transport_class == "long_distance":
            if (
                candidate.transport_class != "long_distance"
                or selected_scope_id is None
                or candidate.provider_evidence_scope_id != selected_scope_id
            ):
                continue
        elif candidate.transport_class not in {"public_transit", "flexible"}:
            continue
        elif not (
            leg.from_endpoint.place_id is not None
            and leg.to_endpoint.place_id is not None
            and candidate.from_endpoint.place_id == leg.from_endpoint.place_id
            and candidate.to_endpoint.place_id == leg.to_endpoint.place_id
        ):
            continue
        eligible.append(candidate)
    return eligible


def _transport_slots(
    legs: Sequence[TransportLeg],
    candidates: Mapping[str, ResearchCandidate],
) -> tuple[list[SelectionSlot], list[TransportLeg]]:
    # 来自候选的行程段必须指向同一个 selection slot。
    slots: list[SelectionSlot] = []
    stamped: list[TransportLeg] = []
    for leg in legs:
        candidate_id = leg.lineage.candidate_id
        selected = candidates.get(candidate_id) if candidate_id else None
        if leg.lineage.lineage_kind != "candidate_entity" or not isinstance(
            selected, TransportCandidate
        ):
            stamped.append(leg)
            continue
        slot_id = _stable_id("slot_transport", leg.transport_leg_id)
        slots.append(
            _slot(
                selected=selected,
                eligible=_transport_alternatives(leg, candidates),
                slot_id=slot_id,
                target_entity_id=leg.transport_leg_id,
                slot_type="transport",
                context={
                    "transport_class": leg.transport_class,
                    "from_endpoint": leg.from_endpoint.name,
                    "to_endpoint": leg.to_endpoint.name,
                },
            )
        )
        stamped.append(
            leg.model_copy(
                update={
                    "lineage": leg.lineage.model_copy(
                        update={"selection_slot_id": slot_id}
                    )
                }
            )
        )
    return slots, stamped
