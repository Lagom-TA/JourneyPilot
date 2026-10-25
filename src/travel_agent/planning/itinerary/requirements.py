from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from travel_agent.entities.provider_evidence import (
    provider_evidence_scope_id,
)
from travel_agent.entities.state import TravelAgentState
from travel_agent.planning.itinerary.draft import (
    ItineraryCompositionDraft,
)
from travel_agent.planning.requirements.inputs import UserInputAnchor
from travel_agent.planning.research.domains import ResearchDomain


def controlled_day_dates(state: TravelAgentState) -> List[date]:
    """Exactly which days the composition has to fill, read off the controlled window."""
    identity = state.controlled_trip_identity or {}
    start = end = None
    if isinstance(identity, dict):
        try:
            start = date.fromisoformat(str(identity.get("start_date") or "")[:10])
            end = date.fromisoformat(str(identity.get("end_date") or "")[:10])
        except ValueError:
            start = end = None
    if (
        start is None or end is None or end < start
    ) and state.weather_context is not None:
        start = state.weather_context.trip_start_date
        end = state.weather_context.trip_end_date
    if start is None or end is None or end < start:
        return []
    return [start + timedelta(days=index) for index in range((end - start).days + 1)]


def itinerary_day_count(state: TravelAgentState) -> int:
    """How many days the composition has to fill, read off the controlled window."""
    return len(controlled_day_dates(state))


def _verify_day_window(
    draft: ItineraryCompositionDraft,
    state: TravelAgentState,
) -> ItineraryCompositionDraft:
    """The composition covers the controlled window exactly, or it is not this trip."""
    expected = controlled_day_dates(state)
    if not expected:
        return draft
    actual = [day.date for day in draft.days]
    if actual != expected:
        raise ValueError(
            "itinerary must cover the controlled window exactly: "
            f"{len(expected)} 天 {expected[0].isoformat()}..{expected[-1].isoformat()}，"
            f"当前 {len(actual)} 天 "
            f"{actual[0].isoformat() if actual else '(空)'}"
            f"..{actual[-1].isoformat() if actual else '(空)'}"
        )
    return draft


def _required_leg_scope_ids(
    required_legs: Optional[List[Any]],
    run_id: str,
    constraint_pack_revision: int,
) -> Dict[str, str]:
    """Map each required long-distance leg to its authoritative Provider scope id."""
    if not required_legs:
        return {}
    return {
        f"{leg.leg_role}@{leg.service_date.isoformat()}": provider_evidence_scope_id(
            run_id=run_id,
            constraint_pack_revision=constraint_pack_revision,
            worker_kind="transport_researcher",
            research_domain=ResearchDomain.LONG_DISTANCE_TRANSPORT,
            candidate_kind=None,
            transport_class="long_distance",
            target_identity=None,
            route_leg=leg,
        )
        for leg in required_legs
    }


def _draft_user_input_anchors(state: TravelAgentState) -> List[UserInputAnchor]:
    """Carry the Draft's controlled anchors into the composed Workspace."""
    draft = state.minimum_delivery_draft
    if draft is None:
        return []
    return list(draft.user_input_anchors)
