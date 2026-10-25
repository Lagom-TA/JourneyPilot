"""Conversation intake contracts."""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel
from pydantic import Field
from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity
from travel_agent.planning.requirements.identity_contracts import (
    MAX_CONTROLLED_DESTINATIONS,
)
from travel_agent.planning.requirements.identity_contracts import PlaceIdentity
from typing import List
from typing import Literal
from typing import Optional


class RouteName(str, Enum):
    TRIP_PLANNING = "trip_planning"
    DESTINATION_DISCOVERY = "destination_discovery"
    FAST_ANSWER = "fast_answer"
    TRIP_REFINEMENT = "trip_refinement"


class RouteAlternative(BaseModel):
    route: RouteName
    confidence: float = Field(ge=0, le=1)


class RouteDecision(BaseModel):
    route: RouteName
    confidence: float = Field(ge=0, le=1)
    alternatives: List[RouteAlternative] = Field(default_factory=list)
    signals: List[str] = Field(default_factory=list)
    requires_trip_draft: bool
    requires_confirmation: bool = False


class GuidedIntakeState(BaseModel):
    raw_input: str
    route_decision: RouteDecision
    controlled_identity: Optional[ControlledTripIdentity] = None
    seed_destinations: List[PlaceIdentity] = Field(
        default_factory=list, max_length=MAX_CONTROLLED_DESTINATIONS
    )
    missing_fields: List[
        Literal[
            "origin", "destinations", "dates", "party", "style", "place_confirmation"
        ]
    ] = Field(default_factory=list)
    ready_to_create: bool = False
