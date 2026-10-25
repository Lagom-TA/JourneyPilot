from __future__ import annotations

from typing import List
from typing import Literal
from pydantic import BaseModel
from pydantic import Field
from travel_agent.planning.requirements.identity_contracts import PlaceIdentity


class PlaceCandidateResponse(BaseModel):
    place: PlaceIdentity
    confidence: float = Field(ge=0, le=1)
    requires_confirmation: bool = True


class PlaceSearchResponse(BaseModel):
    query: str
    role: Literal["origin", "destination", "itinerary_place"]
    candidates: List[PlaceCandidateResponse] = Field(default_factory=list)
