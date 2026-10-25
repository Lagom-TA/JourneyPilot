"""Research packet policy responsibilities."""

from __future__ import annotations

from typing import Any, Literal, Sequence

from travel_agent.planning.references import EntityType

ResearchWorkerKind = Literal[
    "destination_researcher",
    "accommodation_researcher",
    "transport_researcher",
]


_WORKER_CANDIDATE_MODELS: dict[ResearchWorkerKind, tuple[tuple[str, str], ...]] = {
    "destination_researcher": (
        ("visit", "VisitCandidate"),
        ("dining", "DiningCandidate"),
    ),
    "accommodation_researcher": (("lodging", "LodgingCandidate"),),
    "transport_researcher": (("transport", "TransportCandidate"),),
}


RESEARCH_PACKET_CANDIDATE_LIMITS: dict[ResearchWorkerKind, int] = {
    "destination_researcher": 4,
    "accommodation_researcher": 4,
    "transport_researcher": 3,
}


def packet_candidate_limit(
    worker_kind: ResearchWorkerKind,
    *,
    required_transport_classes: Sequence[str] | None = None,
    required_route_scopes: Sequence[Any] = (),
) -> int:
    "How many candidates one model-authoring act may return, for this call."
    if worker_kind == "transport_researcher" and required_transport_classes:
        return max(1, len(required_route_scopes))
    return RESEARCH_PACKET_CANDIDATE_LIMITS[worker_kind]


_DESTINATION_IDENTITY_FACTS_PER_CANDIDATE = 5


_PLACE_IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "visit": (
        "name",
        "place_id",
        "provider_place_type",
        "provider_country_code",
        "address",
    ),
    "dining": (
        "branch_name",
        "place_id",
        "provider_place_type",
        "provider_country_code",
        "address",
    ),
    "lodging": (
        "property_name",
        "place_id",
        "provider_place_type",
        "provider_country_code",
        "address",
    ),
}


_PLACE_NAME_FIELD = {
    "visit": "name",
    "dining": "branch_name",
    "lodging": "property_name",
}


_PLACE_ENTITY_TYPE = {
    "visit": EntityType.VISIT_STOP,
    "dining": EntityType.DINING_STOP,
    "lodging": EntityType.LODGING_STAY,
}


class ResearchPacketOutputError(ValueError):
    "The worker did not emit the exact v2 Research Packet contract."
