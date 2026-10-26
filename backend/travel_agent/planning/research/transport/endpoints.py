from __future__ import annotations

from typing import Any, Dict, List, Optional

from travel_agent.planning.requirements.destination_scope import (
    destination_points,
    is_within_destination,
)
from travel_agent.planning.state import TravelAgentState


def _containing_destination_id(
    state: TravelAgentState,
    latitude: float,
    longitude: float,
) -> Optional[str]:
    """返回该坐标所属的受控目的地；无法归属时返回 None。"""
    for place_id, (dest_lat, dest_lon) in sorted(
        destination_points(state.controlled_trip_identity).items()
    ):
        if is_within_destination(latitude, longitude, dest_lat, dest_lon):
            return place_id
    return None


def _routable_connector_endpoints(
    state: TravelAgentState,
) -> List[Dict[str, Any]]:
    """返回接驳缺口可用的全部已定位端点，可作为起点或终点。"""
    catalog = state.recommendation_catalog
    if catalog is None:
        return []
    sources = {
        source.source_record_id: source
        for packet in catalog.research_packets
        for source in packet.source_records
    }

    def provider_coordinates(candidate: Any) -> tuple[float, float] | None:
        def find(value: Any) -> tuple[float, float] | None:
            if isinstance(value, dict):
                if str(value.get("place_id") or "") == candidate.place_id:
                    latitude = value.get("latitude")
                    longitude = value.get("longitude")
                    if isinstance(latitude, (int, float)) and isinstance(
                        longitude,
                        (int, float),
                    ):
                        return float(latitude), float(longitude)
                for nested in value.values():
                    matched = find(nested)
                    if matched is not None:
                        return matched
            elif isinstance(value, list):
                for nested in value:
                    matched = find(nested)
                    if matched is not None:
                        return matched
            return None

        for source_id in candidate.source_record_ids:
            source = sources.get(source_id)
            if source is None:
                continue
            matched = find(source.snapshot)
            if matched is not None:
                return matched
        return None

    endpoints: List[Dict[str, Any]] = []
    for candidate in catalog.candidate_index().values():
        if (
            candidate.candidate_kind == "transport"
            and getattr(candidate, "transport_class", "") == "long_distance"
        ):
            for endpoint in (candidate.from_endpoint, candidate.to_endpoint):
                station_place_id = str(endpoint.place_id or "").strip()
                station_name = str(endpoint.name or "").strip()
                if (
                    not station_place_id
                    or not station_name
                    or endpoint.latitude is None
                    or endpoint.longitude is None
                ):
                    continue
                destination_id = _containing_destination_id(
                    state, endpoint.latitude, endpoint.longitude
                )
                if destination_id is None:
                    continue
                endpoints.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "destination_id": destination_id,
                        "name": station_name,
                        "place_id": station_place_id,
                        "latitude": float(endpoint.latitude),
                        "longitude": float(endpoint.longitude),
                    }
                )
            continue
        if candidate.candidate_kind not in {
            "visit",
            "dining",
            "lodging",
        }:
            continue
        place_id = str(getattr(candidate, "place_id", "") or "").strip()
        coordinates = provider_coordinates(candidate)
        name = str(
            getattr(candidate, "name", None)
            or getattr(candidate, "branch_name", None)
            or getattr(candidate, "property_name", None)
            or ""
        ).strip()
        if not place_id or not name or coordinates is None:
            continue
        latitude, longitude = coordinates
        endpoints.append(
            {
                "candidate_id": candidate.candidate_id,
                "destination_id": candidate.destination_id,
                "name": name,
                "place_id": place_id,
                "latitude": float(latitude),
                "longitude": float(longitude),
            }
        )

    skeleton = getattr(state, "placement_skeleton", None)
    if skeleton is not None:
        seen_place_ids = {item["place_id"] for item in endpoints}
        for day in getattr(skeleton, "days", []) or []:
            for placement in getattr(day, "placements", []) or []:
                if getattr(placement, "candidate_id", None):
                    continue
                authored = getattr(placement, "authored_place", None)
                if authored is None or not getattr(authored, "is_located", False):
                    continue
                place_id = str(authored.resolved_place_id or "").strip()
                name = str(authored.name or "").strip()
                if not place_id or not name or place_id in seen_place_ids:
                    continue
                seen_place_ids.add(place_id)
                endpoints.append(
                    {
                        "candidate_id": f"authored:{place_id}",
                        "destination_id": day.destination_id,
                        "name": name,
                        "place_id": place_id,
                        "latitude": float(authored.resolved_latitude),
                        "longitude": float(authored.resolved_longitude),
                    }
                )

    return sorted(endpoints, key=lambda item: (item["candidate_id"], item["place_id"]))
