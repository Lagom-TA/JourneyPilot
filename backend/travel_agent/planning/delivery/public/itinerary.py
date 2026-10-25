"""Planning delivery public itinerary."""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from travel_agent.planning.costs.coverage import CostCoverageSummary
from travel_agent.planning.delivery.evidence_basis import EvidenceBasisView
from travel_agent.planning.delivery.travel_content import selection_reason
from travel_agent.planning.itinerary.models import CustomBlock
from travel_agent.planning.itinerary.models import DayPlanV2
from travel_agent.planning.itinerary.models import DiningStop
from travel_agent.planning.itinerary.models import LodgingStay
from travel_agent.planning.itinerary.models import StructuredItineraryV2
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.itinerary.models import VisitStop
from travel_agent.planning.references import EntityType
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence


def _timestamp(value: Optional[datetime]) -> Optional[str]:
    """Encode an instant exactly as the rest of the Bundle's JSON does.

    Pydantic's JSON mode emits RFC 3339 with a ``Z`` for UTC where
    ``datetime.isoformat()`` emits ``+00:00``.  The two are equivalent instants
    but not equal strings, and clients diff these payloads.
    """

    if value is None:
        return None
    text = value.isoformat()
    return f"{text[:-6]}Z" if text.endswith("+00:00") else text


def _day(value: Optional[Date]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _public_endpoint(endpoint: Any) -> Dict[str, Any]:
    return endpoint.model_dump(mode="json")


def _public_segments(segments: Sequence[Any]) -> List[Dict[str, Any]]:
    return [segment.model_dump(mode="json") for segment in segments]


def _public_entity_ref(entity_ref: Any) -> Dict[str, Any]:
    return entity_ref.model_dump(mode="json")


def _public_cost_summary(summary: CostCoverageSummary) -> Dict[str, Any]:

    return summary.model_copy(update={"llm_estimated_total_cny": None}).model_dump(
        mode="json"
    )


def _public_intent_explanations(items: Sequence[Any]) -> List[Dict[str, Any]]:
    return [
        {
            "label": item.label,
            "explanation": item.explanation,
            "evidence_basis": item.evidence_basis,
        }
        for item in items
    ]


def _public_visit_stop(stop: VisitStop, evidence_basis: str) -> Dict[str, Any]:
    return {
        "type": stop.type,
        "item_id": stop.item_id,
        "day_id": stop.day_id,
        "place_id": stop.place_id,
        "name": stop.name,
        "address": stop.address,
        "latitude": stop.latitude,
        "longitude": stop.longitude,
        "planned_start": _timestamp(stop.planned_start),
        "planned_end": _timestamp(stop.planned_end),
        "duration_minutes": stop.duration_minutes,
        "estimated_cost_cny": stop.estimated_cost_cny,
        "selection_reason": selection_reason(stop),
        "visit_type": stop.visit_type,
        "opening_window": stop.opening_window,
        "reservation_required": stop.reservation_required,
        "visit_highlights": list(stop.visit_highlights),
        "intent_explanations": _public_intent_explanations(stop.intent_explanations),
        "evidence_basis": evidence_basis,
    }


def _public_dining_stop(stop: DiningStop, evidence_basis: str) -> Dict[str, Any]:
    return {
        "type": stop.type,
        "item_id": stop.item_id,
        "day_id": stop.day_id,
        "place_id": stop.place_id,
        "name": stop.name,
        "address": stop.address,
        "latitude": stop.latitude,
        "longitude": stop.longitude,
        "planned_start": _timestamp(stop.planned_start),
        "planned_end": _timestamp(stop.planned_end),
        "duration_minutes": stop.duration_minutes,
        "estimated_cost_cny": stop.estimated_cost_cny,
        "selection_reason": selection_reason(stop),
        "meal_type": stop.meal_type,
        "cuisine_types": list(stop.cuisine_types),
        "average_spend_cny": stop.average_spend_cny,
        "recommended_dishes": list(stop.recommended_dishes),
        "reservation_required": stop.reservation_required,
        "opening_window": stop.opening_window,
        "dining_reminders": list(stop.dining_reminders),
        "intent_explanations": _public_intent_explanations(stop.intent_explanations),
        "evidence_basis": evidence_basis,
    }


def _public_lodging_stay(stay: LodgingStay, evidence_basis: str) -> Dict[str, Any]:
    return {
        "type": stay.type,
        "stay_id": stay.stay_id,
        "place_id": stay.place_id,
        "name": stay.name,
        "check_in_date": _day(stay.check_in_date),
        "check_out_date": _day(stay.check_out_date),
        "check_in_time": stay.check_in_time,
        "check_out_time": stay.check_out_time,
        "nights": stay.nights,
        "room_type": stay.room_type,
        "nightly_price_cny": stay.nightly_price_cny,
        "total_price_cny": stay.total_price_cny,
        "price_kind": stay.price_kind,
        "availability_status": stay.availability_status,
        "address": stay.address,
        "selection_reason": selection_reason(stay),
        "intent_explanations": _public_intent_explanations(stay.intent_explanations),
        "evidence_basis": evidence_basis,
    }


def _public_transport_leg(
    leg: TransportLeg, evidence_basis: str, *, is_micro_transport: bool
) -> Dict[str, Any]:
    """Project one leg, including the connector verdict.

    *Which* legs are connectors is domain judgement over Bundle fields, not a
    threshold a reader should re-apply, so the projection ships the verdict as
    ``is_micro_transport``: the server-rendered PDF reads
    :meth:`EvidenceBasisView.stated_basis_for` while the browser reads this
    field, and the two must not be able to reach different conclusions about the
    same leg.
    """

    return {
        "type": leg.type,
        "transport_leg_id": leg.transport_leg_id,
        "transport_class": leg.transport_class,
        "selected_mode": leg.selected_mode.value,
        "from_endpoint": _public_endpoint(leg.from_endpoint),
        "to_endpoint": _public_endpoint(leg.to_endpoint),
        "departure_at": _timestamp(leg.departure_at),
        "arrival_at": _timestamp(leg.arrival_at),
        "duration_minutes": leg.duration_minutes,
        "distance_meters": leg.distance_meters,
        "total_cost_cny": leg.total_cost_cny,
        "transfer_count": leg.transfer_count,
        "segments": _public_segments(leg.segments),
        "booking_status": leg.booking_status,
        "route_status": leg.route_status,
        "mode_preference": leg.mode_preference.model_dump(mode="json"),
        "intent_explanations": _public_intent_explanations(leg.intent_explanations),
        "evidence_basis": evidence_basis,
        "is_micro_transport": is_micro_transport,
    }


def _public_custom_block(block: CustomBlock) -> Dict[str, Any]:
    """A traveller's own arrangement: no lineage, and so no evidence basis."""

    return {
        "type": block.type,
        "item_id": block.item_id,
        "day_id": block.day_id,
        "title": block.title,
        "note": block.note,
        "planned_start": _timestamp(block.planned_start),
        "planned_end": _timestamp(block.planned_end),
        "duration_minutes": block.duration_minutes,
    }


def _public_day_plan(day: DayPlanV2) -> Dict[str, Any]:
    return {
        "day_id": day.day_id,
        "day": day.day,
        "date": _day(day.date),
        "destination_id": day.destination_id,
        "theme": day.theme,
        "timeline": [
            {
                "entry_id": entry.entry_id,
                "entity_type": entry.entity_type.value,
                "entity_id": entry.entity_id,
                "projection_role": entry.projection_role,
            }
            for entry in day.timeline
        ],
        "time_structure": list(day.time_structure),
        "estimated_cost_cny": day.estimated_cost_cny,
    }


def _public_itinerary(
    itinerary: StructuredItineraryV2, view: EvidenceBasisView
) -> Dict[str, Any]:
    """Project the canonical itinerary and state each entry's evidence basis.

    Every lineage-bearing entry carries ``evidence_basis``, including micro
    connectors: suppressing the *statement* on a connector is a rendering rule
    each artifact applies through :meth:`EvidenceBasisView.stated_basis_for`, not
    a hole in the transport contract.
    """

    return {
        "itinerary_id": itinerary.itinerary_id,
        "title": itinerary.title,
        "destination_ids": list(itinerary.destination_ids),
        "duration_days": itinerary.duration_days,
        "day_plans": [_public_day_plan(day) for day in itinerary.day_plans],
        "visit_stops": [
            _public_visit_stop(
                stop, view.basis_for(EntityType.VISIT_STOP, stop.item_id)
            )
            for stop in itinerary.visit_stops
        ],
        "dining_stops": [
            _public_dining_stop(
                stop, view.basis_for(EntityType.DINING_STOP, stop.item_id)
            )
            for stop in itinerary.dining_stops
        ],
        "lodging_stays": [
            _public_lodging_stay(
                stay, view.basis_for(EntityType.LODGING_STAY, stay.stay_id)
            )
            for stay in itinerary.lodging_stays
        ],
        "transport_legs": [
            _public_transport_leg(
                leg,
                view.basis_for(EntityType.TRANSPORT_LEG, leg.transport_leg_id),
                is_micro_transport=leg.transport_leg_id in view.micro_transport_leg_ids,
            )
            for leg in itinerary.transport_legs
        ],
        "custom_blocks": [
            _public_custom_block(block) for block in itinerary.custom_blocks
        ],
        "cost_summary": _public_cost_summary(itinerary.cost_summary),
        "highlights": list(itinerary.highlights),
        "important_notes": list(itinerary.important_notes),
    }
