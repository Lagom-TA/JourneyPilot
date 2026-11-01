"""会话意图分流契约。"""

from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, Field


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
