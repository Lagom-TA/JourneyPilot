from __future__ import annotations

from enum import Enum

from pydantic import Field

from travel_agent.schema import StrictModel


class InternalFailureClass(str, Enum):
    TRANSIENT_DEPENDENCY = "transient_dependency"
    RESEARCH_GAP = "research_gap"
    CONTRACT_VIOLATION = "contract_violation"
    PROJECTION_FAILURE = "projection_failure"
    PERSISTENCE_FAILURE = "persistence_failure"
    SAFETY_BLOCK = "safety_block"
    USER_DECISION_REQUIRED = "user_decision_required"


class DeliveryFailureRecord(StrictModel):
    failure_class: InternalFailureClass
    operation: str = Field(min_length=1)
    attempts: int = Field(ge=1)
    retry_exhausted: bool
    public_message: str = Field(min_length=1)
