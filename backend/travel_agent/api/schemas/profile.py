from __future__ import annotations

from typing import Any
from typing import Dict
from typing import Optional
from pydantic import BaseModel
from travel_agent.planning.requirements.identity_contracts import PlaceIdentity


class DefaultOriginRequest(BaseModel):
    place: PlaceIdentity


class DefaultOriginResponse(BaseModel):
    place: Optional[PlaceIdentity] = None


class UserProfileResponse(BaseModel):
    display_name: str
    preferences: Dict[str, Any]


class UpdatePreferencesRequest(BaseModel):
    preferences: Dict[str, Any]
