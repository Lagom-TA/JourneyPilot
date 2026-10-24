from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import Field, model_validator

from travel_agent.planning.references import EntityRef, EntityType, SelectionSlotRef
from travel_agent.schema import StrictModel


class PersonalizationInfluence(StrictModel):
    influence_id: str = Field(min_length=1)
    target_ref: Union[EntityRef, SelectionSlotRef]
    intent_id: str = Field(min_length=1)
    constraint_id: Optional[str] = Field(default=None, min_length=1)
    effect: Literal[
        "candidate_filter",
        "option_ranking",
        "selection_reason",
        "schedule_rule",
        "output_requirement",
    ]
    source_kind: Literal["current_request", "saved_preference", "trip_context"]
    display_text: str = Field(min_length=1)


class SelectionOption(StrictModel):
    option_id: str = Field(min_length=1)
    selection_slot_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    candidate_entity_ref: EntityRef
    rank: int = Field(ge=1, le=3)
    constraint_result: Literal["passed"] = "passed"
    selection_reasons: List[str] = Field(min_length=2, max_length=3)
    tradeoff: Optional[str] = None
    comparison_facts: List[str] = Field(min_length=1)
    availability_status: Literal["confirmed", "needs_confirmation"]
    fact_assertion_ids: List[str] = Field(min_length=1)
    source_record_ids: List[str] = Field(min_length=1)
    personalization_influence_ids: List[str] = Field(default_factory=list)


# Slots and their projections use the same canonical entity type per domain.
SELECTION_SLOT_ENTITY_TYPES: dict[str, EntityType] = {
    "lodging": EntityType.LODGING_STAY,
    "dining": EntityType.DINING_STOP,
    "visit": EntityType.VISIT_STOP,
    "transport": EntityType.TRANSPORT_LEG,
}


SelectionSlotType = Literal["lodging", "dining", "visit", "transport"]


class SelectionSlot(StrictModel):
    selection_slot_id: str = Field(min_length=1)
    slot_type: SelectionSlotType
    target_entity_id: str = Field(min_length=1)
    context: Dict[str, Any]
    options: List[SelectionOption] = Field(default_factory=list, max_length=3)
    recommended_option_id: Optional[str] = None
    selected_option_id: Optional[str] = None
    status: Literal["researching", "ready", "refreshing", "needs_user_decision"]

    @model_validator(mode="after")
    def validate_options(self) -> "SelectionSlot":
        ids = [item.option_id for item in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("selection option ids must be unique")
        if not ids:
            if self.status == "ready":
                raise ValueError(
                    "ready selection slot requires at least one passed option"
                )
            if (
                self.recommended_option_id is not None
                or self.selected_option_id is not None
            ):
                raise ValueError(
                    "empty selection slot cannot name recommended or selected options"
                )
            return self
        if self.recommended_option_id not in ids:
            raise ValueError("recommended option must belong to the slot")
        if self.selected_option_id is not None and self.selected_option_id not in ids:
            raise ValueError("selected option must belong to the slot")
        if self.status == "ready" and self.selected_option_id is None:
            raise ValueError("ready selection slot requires a selected option")
        expected_ranks = list(range(1, len(self.options) + 1))
        if sorted(item.rank for item in self.options) != expected_ranks:
            raise ValueError("selection option ranks must be contiguous from 1")
        if any(
            item.selection_slot_id != self.selection_slot_id for item in self.options
        ):
            raise ValueError("selection option belongs to a different slot")
        return self
