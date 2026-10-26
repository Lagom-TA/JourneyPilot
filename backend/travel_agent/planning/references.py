from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import Field, model_validator

from travel_agent.schema import StrictModel


class EntityType(str, Enum):
    VISIT_STOP = "visit_stop"
    DINING_STOP = "dining_stop"
    LODGING_STAY = "lodging_stay"
    TRANSPORT_LEG = "transport_leg"
    TRANSPORT_SEGMENT = "transport_segment"
    CUSTOM_BLOCK = "custom_block"
    WEATHER_DAY = "weather_day"


class EntityRef(StrictModel):
    entity_type: EntityType
    entity_id: str = Field(min_length=1)


class SelectionSlotRef(StrictModel):
    selection_slot_id: str = Field(min_length=1)


class TransportLegRef(StrictModel):
    transport_leg_id: str = Field(min_length=1)


class EntityLineage(StrictModel):
    # reference 实体只标识返回的服务，不确认带日期的断言。
    lineage_kind: Literal["candidate_entity", "authored_entity", "reference_entity"] = (
        "candidate_entity"
    )
    research_packet_id: Optional[str] = None
    candidate_id: Optional[str] = None
    selection_slot_id: Optional[str] = None
    fact_assertion_ids: List[str] = Field(default_factory=list)
    source_record_ids: List[str] = Field(default_factory=list)
    planning_decision_ids: List[str] = Field(default_factory=list)
    weather_impact_ids: List[str] = Field(default_factory=list)
    personalization_influence_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_lineage(self) -> "EntityLineage":
        if self.lineage_kind == "candidate_entity":
            if not self.research_packet_id or not self.candidate_id:
                raise ValueError("candidate lineage requires a packet and candidate id")
            if not self.fact_assertion_ids or not self.source_record_ids:
                raise ValueError("candidate lineage requires fact and source ids")
        elif self.lineage_kind == "reference_entity":
            if not self.research_packet_id or not self.candidate_id:
                raise ValueError("reference lineage requires a packet and candidate id")
            if self.fact_assertion_ids or self.source_record_ids:
                raise ValueError(
                    "reference lineage carries no fact or source ids: its claims are "
                    "not confirmed for the requested date"
                )
        else:
            if (
                self.research_packet_id
                or self.candidate_id
                or self.selection_slot_id
                or self.fact_assertion_ids
                or self.source_record_ids
            ):
                raise ValueError(
                    "authored lineage carries no candidate, fact, or source reference"
                )
        return self
