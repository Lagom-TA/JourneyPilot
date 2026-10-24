from __future__ import annotations

from datetime import date as Date
from datetime import datetime, timedelta
from typing import Any, List, Literal, Optional

from pydantic import Field, model_validator

from travel_agent.schema import StrictModel


class UserInputAnchor(StrictModel):
    # Controlled user inputs are planning requirements, never external evidence.
    anchor_id: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    value: Any
    input_kind: Literal[
        "controlled_identity",
        "hard_constraint",
        "intent_requirement",
        "preference",
        "fixed_transport",
        "planning_authorization",
    ]
    constraint_id: Optional[str] = None
    intent_id: Optional[str] = None
    public_summary: Optional[str] = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_constraint_anchor(self) -> "UserInputAnchor":
        if self.input_kind == "hard_constraint" and not self.constraint_id:
            raise ValueError("hard-constraint user input requires a constraint id")
        if self.input_kind == "hard_constraint" and not self.public_summary:
            raise ValueError("hard-constraint user input requires a public summary")
        if self.input_kind != "hard_constraint" and self.constraint_id is not None:
            raise ValueError("only hard-constraint input may name a constraint id")
        if self.input_kind == "intent_requirement" and not self.intent_id:
            raise ValueError("intent-requirement input requires an intent id")
        if self.input_kind != "intent_requirement" and self.intent_id is not None:
            raise ValueError("only intent-requirement input may name an intent id")
        if (
            self.input_kind not in {"hard_constraint", "intent_requirement"}
            and self.public_summary is not None
        ):
            raise ValueError("only contract inputs may define a public summary")
        if self.input_kind == "intent_requirement" and not self.public_summary:
            raise ValueError("intent-requirement input requires a public summary")
        return self


class MinimumDeliveryDayShell(StrictModel):
    day_id: str = Field(min_length=1)
    day: int = Field(ge=1)
    date: Date
    destination_id: str = Field(min_length=1)

    lodging_night: bool = False
    arrival_from_destination_id: Optional[str] = None
    time_structure: List[Literal["morning", "lunch", "afternoon", "evening"]] = Field(
        default_factory=lambda: ["morning", "lunch", "afternoon", "evening"]
    )

    @model_validator(mode="after")
    def validate_time_structure(self) -> "MinimumDeliveryDayShell":
        expected = ["morning", "lunch", "afternoon", "evening"]
        if self.time_structure != expected:
            raise ValueError(
                "minimum delivery day shell must retain the four canonical time blocks"
            )
        return self


class MinimumDeliveryDraft(StrictModel):
    draft_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    planning_generation_id: str = Field(min_length=1)
    controlled_trip_identity_revision: int = Field(ge=0)
    intent_spec_revision: int = Field(ge=1)
    intent_spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    constraint_pack_revision: int = Field(ge=0)
    plan_revision: int = Field(ge=0)
    policy_version: str = Field(min_length=1)
    day_shells: List[MinimumDeliveryDayShell] = Field(min_length=1)
    preserved_constraint_ids: List[str] = Field(default_factory=list)
    preserved_hard_intent_ids: List[str] = Field(default_factory=list)
    user_input_anchors: List[UserInputAnchor] = Field(default_factory=list)
    planning_authorized: bool = False
    planning_authorized_at: Optional[datetime] = None
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_draft(self) -> "MinimumDeliveryDraft":
        if [item.day for item in self.day_shells] != list(
            range(1, len(self.day_shells) + 1)
        ):
            raise ValueError(
                "minimum delivery draft day shells must be contiguous from one"
            )
        dates = [item.date for item in self.day_shells]
        if dates != [dates[0] + timedelta(days=index) for index in range(len(dates))]:
            raise ValueError("minimum delivery draft day dates must be contiguous")
        ids = [item.day_id for item in self.day_shells]
        if len(ids) != len(set(ids)):
            raise ValueError("minimum delivery draft day ids must be unique")
        expected_lodging_nights = [
            index < len(self.day_shells) - 1 for index in range(len(self.day_shells))
        ]
        if [item.lodging_night for item in self.day_shells] != expected_lodging_nights:
            raise ValueError(
                "minimum delivery draft must retain every required lodging night"
            )
        for index, item in enumerate(self.day_shells):
            if index == 0 and item.arrival_from_destination_id is not None:
                raise ValueError(
                    "first minimum delivery day cannot have an inter-city arrival"
                )
            if index > 0:
                previous = self.day_shells[index - 1]
                changed_destination = previous.destination_id != item.destination_id
                if changed_destination != (
                    item.arrival_from_destination_id is not None
                ):
                    raise ValueError(
                        "minimum delivery draft must retain each inter-city boundary"
                    )
                if item.arrival_from_destination_id not in (
                    None,
                    previous.destination_id,
                ):
                    raise ValueError(
                        "minimum delivery inter-city boundary must reference the prior destination"
                    )
        if len(self.preserved_constraint_ids) != len(
            set(self.preserved_constraint_ids)
        ):
            raise ValueError("minimum delivery draft constraints must be unique")
        anchor_ids = [item.anchor_id for item in self.user_input_anchors]
        if len(anchor_ids) != len(set(anchor_ids)):
            raise ValueError("minimum delivery draft user-input anchors must be unique")
        hard_constraint_ids = {
            item.constraint_id
            for item in self.user_input_anchors
            if item.input_kind == "hard_constraint" and item.constraint_id is not None
        }
        if not set(self.preserved_constraint_ids) <= hard_constraint_ids:
            raise ValueError(
                "minimum delivery draft preserves an unanchored hard constraint"
            )
        if self.planning_authorized != (self.planning_authorized_at is not None):
            raise ValueError(
                "draft authorization timestamp must match authorization state"
            )
        return self
