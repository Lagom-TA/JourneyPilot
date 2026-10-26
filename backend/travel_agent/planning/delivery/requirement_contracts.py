"""交付需求契约。"""

from __future__ import annotations

from pydantic import Field
from travel_agent.schema import StrictModel
from typing import Literal


class EntityIntentExplanation(StrictModel):
    intent_id: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=160)
    explanation: str = Field(min_length=1, max_length=500)
    evidence_basis: Literal[
        "verified_fact",
        "supported_description",
        "planning_judgment",
    ]


class PublicRequirementFulfillment(StrictModel):
    requirement_id: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=300)
    status: Literal[
        "satisfied",
        "partially_satisfied",
        "unsatisfied",
        "unverifiable",
    ]
    explanation: str = Field(min_length=1, max_length=500)
