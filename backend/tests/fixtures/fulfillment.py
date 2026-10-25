from datetime import datetime
from types import SimpleNamespace

from travel_agent.planning.requirements.candidate_match_contracts import (
    CandidateIntentMatch,
)
from travel_agent.planning.requirements.intent_contracts import (
    IntentItem,
    IntentKind,
    IntentSpec,
    IntentStrength,
    IntentTarget,
    VerificationMode,
    canonical_json_hash,
)


def make_composition_intent(
    intent_id: str,
    *,
    kind: IntentKind,
    strength: IntentStrength,
    value,
) -> IntentItem:
    return IntentItem(
        intent_id=intent_id,
        kind=kind,
        target=IntentTarget.VISIT,
        strength=strength,
        priority=90,
        value=value,
        source_kind="current_request",
        source_ref_id="message_test",
        verification_mode=VerificationMode.DETERMINISTIC,
        impact_stages=["composition"],
        public_summary=f"requirement {intent_id}",
    )

def make_fulfillment_spec(*intents: IntentItem) -> IntentSpec:
    material = [intent.model_dump(mode="json") for intent in intents]
    return IntentSpec(
        intent_spec_id="intent_spec_test",
        revision=1,
        generation_id="generation_test",
        content_hash=canonical_json_hash(material),
        active_items=list(intents),
        objective_summary="test intent coverage",
    )

def make_fulfillment_workspace(
    *,
    placements: list[tuple[str, str, int]],
    matches: list[CandidateIntentMatch] | None = None,
    day_count: int = 2,
    candidate_names: dict[str, str] | None = None,
):
    names = candidate_names or {}
    candidates = {
        candidate_id: SimpleNamespace(
            candidate_id=candidate_id, candidate_kind="visit",
            name=names.get(candidate_id, candidate_id),
            place_id=f"place_{candidate_id}", fact_assertion_ids=[],
        )
        for candidate_id, _day_id, _hour in placements
    }
    catalog = SimpleNamespace(
        candidate_intent_matches=matches or [],
        research_packets=[],
        candidate_index=lambda: candidates,
    )
    visit_stops = [
        SimpleNamespace(
            item_id=f"item_{candidate_id}",
            name=names.get(candidate_id, candidate_id),
            place_id=f"place_{candidate_id}",
            day_id=day_id,
            planned_start=datetime(2026, 9, int(day_id.rsplit("_", 1)[1]), hour),
            lineage=SimpleNamespace(
                candidate_id=candidate_id,
                fact_assertion_ids=[f"fact_{candidate_id}"],
            ),
            intent_explanations=[],
        )
        for candidate_id, day_id, hour in placements
    ]
    itinerary = SimpleNamespace(
        visit_stops=visit_stops,
        dining_stops=[],
        lodging_stays=[],
        transport_legs=[],
        day_plans=[
            SimpleNamespace(
                day_id=f"day_{day}",
                day=day,
                destination_id="destination_tokyo",
                timeline=[
                    SimpleNamespace(entity_id=f"item_{candidate_id}")
                    for candidate_id, day_id, _hour in placements
                    if day_id == f"day_{day}"
                ],
            )
            for day in range(1, day_count + 1)
        ],
    )
    return SimpleNamespace(
        workspace_revision=0,
        entity_intent_checks=[],
        recommendation_catalog=catalog,
        itinerary=itinerary,
        candidate_selection_plan=SimpleNamespace(
            composition_candidate_ids=lambda: set(candidates),
            selection_policy=SimpleNamespace(mode="deterministic"),
            entries=[],
        ),
        selection_slots=[],
    )
