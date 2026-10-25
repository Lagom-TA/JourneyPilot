"""Planning delivery candidate presentation."""

from __future__ import annotations

from travel_agent.planning.delivery.projection_errors import DeliveryProjectionError
from travel_agent.planning.research.candidates import DiningCandidate
from travel_agent.planning.research.candidates import LodgingCandidate
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.candidates import VisitCandidate


def candidate_display_name(candidate: object) -> str:
    """The one name a Candidate is called by, whatever its domain calls the field.

    Public alongside :func:`candidate_place_id`: three domains spell this field three
    ways, so a copy of the mapping anywhere else is a derived quantity that goes stale
    the moment a fourth domain lands.
    """
    if isinstance(candidate, VisitCandidate):
        return candidate.name
    if isinstance(candidate, DiningCandidate):
        return candidate.branch_name
    if isinstance(candidate, LodgingCandidate):
        return candidate.property_name
    if isinstance(candidate, TransportCandidate):
        return f"{candidate.from_endpoint.name} → {candidate.to_endpoint.name}"
    raise DeliveryProjectionError(
        "selection option references an unsupported candidate"
    )


def candidate_place_id(candidate: object) -> str:
    """The Provider identity a Candidate is pinned to, or "" where there is none.

    Three of the four domains are a place and carry ``place_id`` under that exact
    name; transport is a route between two endpoints and has no single place, so
    it answers "" rather than being coerced into one. Callers keyed on identity
    (the knowledge-base nomination funnel) drop the empty answer, which is the
    right outcome: a route was never a place a chunk could have nominated.
    """
    if isinstance(candidate, (VisitCandidate, DiningCandidate, LodgingCandidate)):
        return candidate.place_id
    if isinstance(candidate, TransportCandidate):
        return ""
    raise DeliveryProjectionError(
        "selection option references an unsupported candidate"
    )
