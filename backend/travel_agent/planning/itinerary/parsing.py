from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.itinerary.draft import (
    _SERVER_OWNED_PLACE_FIELDS,
    ItineraryCompositionDraft,
)
from travel_agent.planning.itinerary.requirements import _verify_day_window


def parse_itinerary_composition(raw: str) -> ItineraryCompositionDraft:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("itinerary composition must be one exact JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError("itinerary composition must be one JSON object")
    _normalize_time_structure(payload)
    try:
        return ItineraryCompositionDraft.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"itinerary composition failed schema gate: {exc}") from exc


def _normalize_time_structure(payload: dict[str, Any]) -> None:
    # Time blocks are fixed display scaffolding, not authored placement data.
    days = payload.get("days")
    if not isinstance(days, list):
        return
    for day in days:
        if isinstance(day, dict):
            day["time_structure"] = ["morning", "lunch", "afternoon", "evening"]


def _parse_exact_llm_composition(
    raw: str,
    state: TravelAgentState,
) -> ItineraryCompositionDraft:
    payload = json.loads(raw)
    if isinstance(payload, dict):
        for day in payload.get("days", []) or []:
            if not isinstance(day, dict):
                continue
            for placement in day.get("placements", []) or []:
                if not isinstance(placement, dict):
                    continue
                place = placement.get("authored_place")
                if isinstance(place, dict):
                    for field in _SERVER_OWNED_PLACE_FIELDS:
                        place.pop(field, None)
    return _verify_day_window(parse_itinerary_composition(json.dumps(payload)), state)
