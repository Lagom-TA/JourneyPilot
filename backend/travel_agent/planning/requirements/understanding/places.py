"""把理解阶段选中的地点绑定到表单或工具返回的地点记录。"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from travel_agent.planning.requirements.identity_contracts import (
    DESTINATION_PLACE_KINDS,
    ORIGIN_PLACE_KINDS,
    PlaceIdentity,
    PlaceKind,
)


def _nominatim_place(record: Mapping[str, Any]) -> PlaceIdentity | None:
    try:
        place = PlaceIdentity.model_validate(record.get("trip_identity"))
    except (ValidationError, TypeError, ValueError):
        return None
    if place.provider != "osm" or place.place_id != record.get("place_id"):
        return None
    return place


def _tool_places(messages: Sequence[Mapping[str, Any]]) -> dict[str, PlaceIdentity]:
    places: dict[str, PlaceIdentity] = {}
    for message in messages:
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        try:
            envelope = json.loads(content) if isinstance(content, str) else content
        except (TypeError, ValueError):
            continue
        if not isinstance(envelope, dict) or envelope.get("tool_name") != "global_place_search":
            continue
        metadata = envelope.get("metadata")
        result = envelope.get("sanitized_result")
        if (
            envelope.get("status") != "success"
            or not isinstance(metadata, dict)
            or metadata.get("evidence_allowed") is not True
            or metadata.get("quarantine_result") is True
            or not isinstance(result, dict)
            or result.get("success") is not True
            or result.get("provider") != "nominatim"
        ):
            continue
        for record in result.get("results") or []:
            if isinstance(record, dict):
                place = _nominatim_place(record)
                if place is not None:
                    places[place.place_id] = place
    return places


def bind_understanding_places(
    identity: Mapping[str, Any],
    previous_identity: Mapping[str, Any],
    messages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """模型决定地点角色，服务端只采用已有地点记录中的身份字段。"""
    places = _tool_places(messages)
    previous_destinations = previous_identity.get("destinations")
    previous_places = [previous_identity.get("origin")]
    if isinstance(previous_destinations, list):
        previous_places.extend(previous_destinations)
    for value in previous_places:
        if not isinstance(value, dict):
            continue
        try:
            place = PlaceIdentity.model_validate(value)
        except (ValidationError, TypeError, ValueError):
            continue
        places[place.place_id] = place

    def select(value: Any, allowed: set[PlaceKind]) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        place = places.get(str(value.get("place_id") or ""))
        if place is None or place.kind not in allowed:
            return None
        return place.model_dump(mode="json")

    bound = dict(identity)
    bound["origin"] = select(identity.get("origin"), ORIGIN_PLACE_KINDS)
    destinations = identity.get("destinations")
    if destinations is not None and not isinstance(destinations, list):
        raise ValueError("destinations 必须是数组或空值")
    bound["destinations"] = [
        place for item in destinations or [] if (place := select(item, DESTINATION_PLACE_KINDS)) is not None
    ]
    return bound
