from __future__ import annotations

from typing import Any, Dict, List, Literal, Union

from pydantic import Field, model_validator

from travel_agent.planning.research.selection_contracts import CandidateSelectionPlan
from travel_agent.planning.itinerary.mutation_contracts import CompositionMutation
from travel_agent.planning.requirements.snapshot_contracts import IntentContractSnapshot
from travel_agent.planning.itinerary.models import (
    DiningStop,
    LodgingStay,
    StructuredItineraryV2,
    TransportLeg,
    VisitStop,
)
from travel_agent.planning.itinerary.options import (
    SELECTION_SLOT_ENTITY_TYPES,
    PersonalizationInfluence,
    SelectionSlot,
)
from travel_agent.planning.requirements.inputs import UserInputAnchor
from travel_agent.planning.research.candidates import (
    DiningCandidate,
    LodgingCandidate,
    TransportCandidate,
    VisitCandidate,
)
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.weather.models import WeatherProposalDecision
from travel_agent.schema import StrictModel

TRIP_WORKSPACE_CONTRACT_VERSION = "journeypilot.trip_workspace.v10"


class TripWorkspaceV2(StrictModel):
    contract_version: Literal[TRIP_WORKSPACE_CONTRACT_VERSION] = (
        TRIP_WORKSPACE_CONTRACT_VERSION
    )
    run_id: str = Field(min_length=1)
    generation_id: str = Field(min_length=1)
    workspace_revision: int = Field(ge=0)
    itinerary: StructuredItineraryV2
    recommendation_catalog: RecommendationCatalog
    intent_contract_snapshot: IntentContractSnapshot
    composition_mutations: List[CompositionMutation] = Field(default_factory=list)
    candidate_selection_plan: CandidateSelectionPlan
    user_input_anchors: List[UserInputAnchor] = Field(default_factory=list)
    selection_slots: List[SelectionSlot] = Field(default_factory=list)
    personalization_influences: List[PersonalizationInfluence] = Field(
        default_factory=list
    )
    weather_proposal_decisions: List[WeatherProposalDecision] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_candidate_lineage(self) -> "TripWorkspaceV2":
        catalog = self.recommendation_catalog
        if catalog.generation_id != self.generation_id:
            raise ValueError("workspace and recommendation catalog generations differ")
        if self.intent_contract_snapshot.generation_id != self.generation_id:
            raise ValueError("workspace and intent contract generations differ")
        if self.candidate_selection_plan.generation_id != self.generation_id:
            raise ValueError("workspace and candidate selection generations differ")
        if (
            self.candidate_selection_plan.intent_spec_revision
            != self.intent_contract_snapshot.intent_spec_revision
        ):
            raise ValueError(
                "workspace intent and candidate selection revisions differ"
            )
        if self.candidate_selection_plan.catalog_revision != catalog.fact_data_revision:
            raise ValueError(
                "workspace candidate selection uses another catalog revision"
            )
        catalog_candidate_ids = set(catalog.candidate_index())
        if (
            not {entry.candidate_id for entry in self.candidate_selection_plan.entries}
            <= catalog_candidate_ids
        ):
            raise ValueError(
                "workspace candidate selection references a missing candidate"
            )
        mutation_ids = [item.mutation_id for item in self.composition_mutations]
        if len(mutation_ids) != len(set(mutation_ids)):
            raise ValueError("workspace composition mutations must be unique")
        if any(
            item.generation_id != self.generation_id
            for item in self.composition_mutations
        ):
            raise ValueError(
                "workspace composition mutation belongs to another generation"
            )
        candidates = catalog.candidate_index()
        anchor_ids = [item.anchor_id for item in self.user_input_anchors]
        if len(anchor_ids) != len(set(anchor_ids)):
            raise ValueError("workspace user-input anchor ids must be unique")
        packet_by_candidate = {
            candidate.candidate_id: packet.research_packet_id
            for packet in catalog.research_packets
            for candidate in packet.candidates
        }
        influence_ids = {item.influence_id for item in self.personalization_influences}
        if len(influence_ids) != len(self.personalization_influences):
            raise ValueError("personalization influence ids must be unique")
        proposal_decision_ids = [
            item.proposal_id for item in self.weather_proposal_decisions
        ]
        if len(proposal_decision_ids) != len(set(proposal_decision_ids)):
            raise ValueError("weather proposal decisions must be unique")

        entities: List[Union[VisitStop, DiningStop, LodgingStay, TransportLeg]] = [
            *self.itinerary.visit_stops,
            *self.itinerary.dining_stops,
            *self.itinerary.lodging_stays,
            *self.itinerary.transport_legs,
        ]
        for entity in entities:
            lineage = entity.lineage
            if lineage.lineage_kind == "authored_entity":
                continue
            candidate = candidates.get(lineage.candidate_id)
            if candidate is None:
                raise ValueError("canonical entity references a missing candidate")
            expected_candidate_type = {
                VisitStop: VisitCandidate,
                DiningStop: DiningCandidate,
                LodgingStay: LodgingCandidate,
                TransportLeg: TransportCandidate,
            }[type(entity)]
            if not isinstance(candidate, expected_candidate_type):
                raise ValueError("canonical entity references a cross-domain candidate")
            if packet_by_candidate[lineage.candidate_id] != lineage.research_packet_id:
                raise ValueError(
                    "canonical entity research packet lineage is inconsistent"
                )
            if not set(lineage.fact_assertion_ids) <= set(candidate.fact_assertion_ids):
                raise ValueError(
                    "canonical entity fact lineage exceeds candidate facts"
                )
            if not set(lineage.source_record_ids) <= set(candidate.source_record_ids):
                raise ValueError(
                    "canonical entity source lineage exceeds candidate sources"
                )
            if not set(lineage.personalization_influence_ids) <= influence_ids:
                raise ValueError(
                    "canonical entity references a missing personalization influence"
                )

        slot_ids = [slot.selection_slot_id for slot in self.selection_slots]
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("selection slot ids must be unique")
        slot_targets: Dict[str, Dict[str, Any]] = {
            "dining": {item.item_id: item for item in self.itinerary.dining_stops},
            "lodging": {item.stay_id: item for item in self.itinerary.lodging_stays},
            "visit": {item.item_id: item for item in self.itinerary.visit_stops},
            "transport": {
                item.transport_leg_id: item for item in self.itinerary.transport_legs
            },
        }
        for slot in self.selection_slots:
            target = slot_targets[slot.slot_type].get(slot.target_entity_id)
            if target is None:
                raise ValueError(
                    "selection slot target is missing from canonical itinerary"
                )
            if not slot.options:
                continue
            for option in slot.options:
                candidate = candidates.get(option.candidate_id)
                expected_kind = slot.slot_type
                if candidate is None or candidate.candidate_kind != expected_kind:
                    raise ValueError(
                        "selection option references a missing or cross-domain candidate"
                    )
                if option.candidate_entity_ref.entity_id != slot.target_entity_id:
                    raise ValueError(
                        "selection option entity ref must target the slot canonical entity"
                    )
                expected_entity_type = SELECTION_SLOT_ENTITY_TYPES[slot.slot_type]
                if option.candidate_entity_ref.entity_type != expected_entity_type:
                    raise ValueError(
                        "selection option entity ref has the wrong domain type"
                    )
                if not set(option.fact_assertion_ids) <= set(
                    candidate.fact_assertion_ids
                ):
                    raise ValueError(
                        "selection option fact refs exceed candidate facts"
                    )
                if not set(option.source_record_ids) <= set(
                    candidate.source_record_ids
                ):
                    raise ValueError(
                        "selection option source refs exceed candidate sources"
                    )
                if not set(option.personalization_influence_ids) <= influence_ids:
                    raise ValueError(
                        "selection option references a missing personalization influence"
                    )
            if slot.selected_option_id is None:
                if slot.status != "needs_user_decision":
                    raise ValueError(
                        "unselected non-empty slot must require a user decision"
                    )
                continue
            selected = next(
                option
                for option in slot.options
                if option.option_id == slot.selected_option_id
            )
            if target.lineage.candidate_id != selected.candidate_id:
                raise ValueError(
                    "canonical selected entity does not match slot selected option"
                )
            if target.lineage.selection_slot_id != slot.selection_slot_id:
                raise ValueError(
                    "canonical selected entity is missing its selection slot lineage"
                )
        return self
