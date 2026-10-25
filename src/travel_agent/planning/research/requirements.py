from __future__ import annotations

from datetime import date

from travel_agent.entities.state import TravelAgentState
from travel_agent.planning.assignments import strip_round_suffix
from travel_agent.planning.nodes import RESEARCH_WORKER_NODES
from travel_agent.services.destination_scope import destination_points
from travel_agent.services.product_requirements import required_physical_candidate_kinds


def _destination_country_codes(state: TravelAgentState) -> dict[str, str]:
    destinations = (state.controlled_trip_identity or {}).get("destinations") or []
    return {
        str(item.get("place_id") or ""): str(item.get("country_code") or "").casefold()
        for item in destinations
        if isinstance(item, dict) and item.get("place_id") and item.get("country_code")
    }


def _destination_points(state: TravelAgentState) -> dict[str, tuple[float, float]]:
    """Each controlled destination's own point, by ``place_id``."""
    return destination_points(state.controlled_trip_identity)


def _required_workers(state: TravelAgentState) -> set[str]:
    return {
        strip_round_suffix(agent)
        for group in state.execution_plan
        for agent in group
        if strip_round_suffix(agent) in RESEARCH_WORKER_NODES
    }


def _required_candidate_kinds(state: TravelAgentState) -> dict[str, set[str]]:
    """Translate controlled product choices into non-compensating domain coverage."""
    required = required_physical_candidate_kinds(state.controlled_trip_identity)
    return {"destination_researcher": required} if required else {}


def _trip_duration_days(state: TravelAgentState) -> int:
    identity = state.controlled_trip_identity or {}
    try:
        start = date.fromisoformat(str(identity.get("start_date") or ""))
        end = date.fromisoformat(str(identity.get("end_date") or ""))
    except ValueError:
        if state.weather_context is None:
            return 0
        start = state.weather_context.trip_start_date
        end = state.weather_context.trip_end_date
    return (end - start).days + 1 if end >= start else 0
