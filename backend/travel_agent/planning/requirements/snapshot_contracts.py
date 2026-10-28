"""需求快照契约。"""

from __future__ import annotations

from pydantic import Field
from travel_agent.planning.requirements.intent_contracts import IntentImpactStage
from travel_agent.planning.requirements.intent_contracts import IntentKind
from travel_agent.planning.requirements.intent_contracts import IntentSpec
from travel_agent.planning.requirements.intent_contracts import IntentStrength
from travel_agent.planning.requirements.intent_contracts import IntentTarget
from travel_agent.planning.requirements.intent_contracts import IntentValue
from travel_agent.planning.requirements.intent_contracts import VerificationMode
from travel_agent.planning.requirements.intent_contracts import canonical_json_hash
from travel_agent.schema import StrictModel
from typing import List
from typing import Literal


INTENT_CONTRACT_SNAPSHOT_VERSION = "journeypilot.intent_contract_snapshot.v1"


class IntentContractRequirement(StrictModel):
    intent_id: str = Field(min_length=1)
    kind: IntentKind
    target: IntentTarget
    strength: IntentStrength
    value: IntentValue
    verification_mode: VerificationMode
    impact_stages: List[IntentImpactStage] = Field(min_length=1)
    public_summary: str = Field(min_length=1, max_length=300)


class IntentContractSnapshot(StrictModel):
    schema_version: Literal[INTENT_CONTRACT_SNAPSHOT_VERSION] = (
        INTENT_CONTRACT_SNAPSHOT_VERSION
    )
    generation_id: str = Field(min_length=1)
    intent_spec_revision: int = Field(ge=1)
    objective_summary: str = Field(min_length=1, max_length=500)
    requirements: List[IntentContractRequirement] = Field(default_factory=list)
    conflicted_intent_ids: List[str] = Field(default_factory=list)
    conflict_summaries: List[str] = Field(default_factory=list)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_intent_spec(cls, intent_spec: IntentSpec) -> "IntentContractSnapshot":
        requirements = [
            IntentContractRequirement(
                intent_id=intent.intent_id,
                kind=intent.kind,
                target=intent.target,
                strength=intent.strength,
                value=intent.value,
                verification_mode=intent.verification_mode,
                impact_stages=intent.impact_stages,
                public_summary=intent.public_summary,
            )
            for intent in intent_spec.active_items
        ]
        material = {
            "generation_id": intent_spec.generation_id,
            "intent_spec_revision": intent_spec.revision,
            "objective_summary": intent_spec.objective_summary,
            "requirements": [item.model_dump(mode="json") for item in requirements],
            "conflict_summaries": [
                conflict.user_visible_summary for conflict in intent_spec.conflicts
            ],
            "conflicted_intent_ids": sorted(
                {
                    intent_id
                    for conflict in intent_spec.conflicts
                    for intent_id in conflict.intent_ids
                }
            ),
        }
        return cls(
            generation_id=intent_spec.generation_id,
            intent_spec_revision=intent_spec.revision,
            objective_summary=intent_spec.objective_summary,
            requirements=requirements,
            conflict_summaries=material["conflict_summaries"],
            conflicted_intent_ids=material["conflicted_intent_ids"],
            content_hash=canonical_json_hash(material),
        )
