"""Planning requirements entity binding."""

from __future__ import annotations

from travel_agent.planning.delivery.requirement_contracts import EntityIntentExplanation
from travel_agent.planning.itinerary.models import DiningStop
from travel_agent.planning.itinerary.models import LodgingStay
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.itinerary.models import VisitStop
from travel_agent.planning.itinerary.options import PersonalizationInfluence
from travel_agent.planning.references import EntityRef
from travel_agent.planning.references import EntityType
from travel_agent.planning.requirements.intent_contracts import IntentItem
from travel_agent.planning.requirements.intent_contracts import IntentKind
from travel_agent.planning.requirements.intent_contracts import IntentSpec
from travel_agent.planning.requirements.intent_contracts import IntentTarget
from travel_agent.planning.requirements.intent_contracts import OutputRequirementValue
from travel_agent.planning.requirements.intent_contracts import canonical_json_hash
from travel_agent.planning.requirements.snapshot_contracts import (
    IntentContractRequirement,
)
from travel_agent.planning.requirements.snapshot_contracts import IntentContractSnapshot
from travel_agent.planning.workspace import TripWorkspaceV2


def _entity_ref(entity) -> EntityRef:
    if isinstance(entity, VisitStop):
        return EntityRef(entity_type=EntityType.VISIT_STOP, entity_id=entity.item_id)
    if isinstance(entity, DiningStop):
        return EntityRef(entity_type=EntityType.DINING_STOP, entity_id=entity.item_id)
    if isinstance(entity, LodgingStay):
        return EntityRef(entity_type=EntityType.LODGING_STAY, entity_id=entity.stay_id)
    return EntityRef(
        entity_type=EntityType.TRANSPORT_LEG,
        entity_id=entity.transport_leg_id,
    )


def _target_matches(intent: IntentItem | IntentContractRequirement, entity) -> bool:
    if (
        intent.kind is IntentKind.OUTPUT_REQUIREMENT
        and intent.target is IntentTarget.DELIVERY
    ):
        return True
    target = {
        VisitStop: IntentTarget.VISIT,
        DiningStop: IntentTarget.DINING,
        LodgingStay: IntentTarget.LODGING,
        TransportLeg: IntentTarget.LOCAL_TRANSPORT,
    }[type(entity)]
    if isinstance(entity, TransportLeg) and entity.transport_class == "long_distance":
        target = IntentTarget.LONG_DISTANCE_TRANSPORT
    return intent.target in {target, IntentTarget.TRIP, IntentTarget.ITINERARY}


def _default_explanation(entity, intent: IntentItem | IntentContractRequirement) -> str:
    selection_reason = getattr(entity, "selection_reason", None)
    if selection_reason:
        return f"{intent.public_summary}：{selection_reason}"
    if isinstance(entity, TransportLeg):
        return f"{intent.public_summary}：已按行程结构选择{entity.selected_mode.value}"
    return f"已按要求落实：{intent.public_summary}"


def bind_intent_context(
    workspace: TripWorkspaceV2,
    intent_spec: IntentSpec | IntentContractSnapshot,
) -> TripWorkspaceV2:
    """把输出要求类的 intent 绑定到每个行程实体，形成个性化影响记录。"""
    influences: dict[str, PersonalizationInfluence] = {}

    def bind_entity(entity):
        entity_ref = _entity_ref(entity)
        explanations: dict[str, EntityIntentExplanation] = {}
        lineage_ids: set[str] = set()

        for intent in intent_spec.active_items:
            if (
                intent.kind is not IntentKind.OUTPUT_REQUIREMENT
                or not isinstance(intent.value, OutputRequirementValue)
                or intent.value.applies_to not in {"each_item", "each_day"}
                or not _target_matches(intent, entity)
            ):
                continue
            explanations[intent.intent_id] = EntityIntentExplanation(
                intent_id=intent.intent_id,
                label=intent.public_summary[:160],
                explanation=_default_explanation(entity, intent),
                evidence_basis="planning_judgment",
            )
            influence_id = f"influence_{canonical_json_hash({'generation_id': workspace.generation_id, 'entity_id': entity_ref.entity_id, 'intent_id': intent.intent_id})[:24]}"
            influences[influence_id] = PersonalizationInfluence(
                influence_id=influence_id,
                target_ref=entity_ref,
                intent_id=intent.intent_id,
                effect="output_requirement",
                source_kind=_source_kind(intent),
                display_text=intent.public_summary,
            )
            lineage_ids.add(influence_id)

        return entity.model_copy(
            update={
                "intent_explanations": sorted(
                    explanations.values(), key=lambda item: item.intent_id
                ),
                "lineage": entity.lineage.model_copy(
                    update={
                        "personalization_influence_ids": sorted(lineage_ids),
                    }
                ),
            }
        )

    itinerary = workspace.itinerary.model_copy(
        update={
            "visit_stops": [
                bind_entity(item) for item in workspace.itinerary.visit_stops
            ],
            "dining_stops": [
                bind_entity(item) for item in workspace.itinerary.dining_stops
            ],
            "lodging_stays": [
                bind_entity(item) for item in workspace.itinerary.lodging_stays
            ],
            "transport_legs": [
                bind_entity(item) for item in workspace.itinerary.transport_legs
            ],
        }
    )
    return workspace.model_copy(
        update={
            "itinerary": itinerary,
            "personalization_influences": sorted(
                influences.values(), key=lambda item: item.influence_id
            ),
        }
    )


def _source_kind(intent: IntentItem | IntentContractRequirement) -> str:
    source_kind = getattr(intent, "source_kind", "current_request")
    if source_kind == "saved_preference":
        return "saved_preference"
    if source_kind == "trip_context":
        return "trip_context"
    return "current_request"
