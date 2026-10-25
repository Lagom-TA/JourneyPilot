"""Planning requirements check contracts."""

from __future__ import annotations

from pydantic import Field
from travel_agent.planning.requirements.candidate_match_contracts import (
    IntentMatchStatus,
)
from travel_agent.schema import StrictModel
from typing import Any
from typing import Literal


class IntentCheckObject(StrictModel):
    entity_id: str = Field(min_length=1)
    kind: Literal["visit", "dining", "lodging", "transport"]
    transport_class: Literal["long_distance", "public_transit", "flexible"] | None = (
        None
    )
    candidate_id: str | None = None
    place_id: str | None = None
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    facts: list[dict[str, Any]] = Field(default_factory=list)


class EntityIntentCheck(StrictModel):
    entity_id: str = Field(min_length=1)
    intent_id: str = Field(min_length=1)
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: IntentMatchStatus
    evidence_basis: Literal["verified_fact", "planning_judgment", "unverified"]
    reason: str = Field(min_length=1, max_length=300)
    supporting_fact_assertion_ids: list[str] = Field(default_factory=list)
