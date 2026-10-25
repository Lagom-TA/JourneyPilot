"""Planning requirements verification entities."""

from __future__ import annotations

from datetime import datetime
from travel_agent.planning.requirements.composition_contracts import CompositionRule
from travel_agent.planning.requirements.composition_contracts import CompositionRuleKind
from travel_agent.planning.requirements.coverage_contracts import IntentCoverageStatus
from travel_agent.planning.requirements.entity_checks import requirement_check_objects
from travel_agent.planning.workspace import TripWorkspaceV2


def _entity_rows(workspace: TripWorkspaceV2) -> list[dict]:
    candidate_index = workspace.recommendation_catalog.candidate_index()
    objects = {obj.entity_id: obj for obj in requirement_check_objects(workspace)}
    day_context = {
        day.day_id: (day.day, day.destination_id)
        for day in workspace.itinerary.day_plans
    }
    timeline_order: dict[str, tuple[int, int]] = {}
    timeline_day: dict[str, str] = {}
    for day in sorted(workspace.itinerary.day_plans, key=lambda item: item.day):
        for index, entry in enumerate(day.timeline):
            timeline_order.setdefault(entry.entity_id, (day.day, index))
            timeline_day.setdefault(entry.entity_id, day.day_id)
    rows: list[dict] = []
    for kind, entities in (
        ("visit", workspace.itinerary.visit_stops),
        ("dining", workspace.itinerary.dining_stops),
        ("lodging", workspace.itinerary.lodging_stays),
        ("transport", workspace.itinerary.transport_legs),
    ):
        for entity in entities:
            entity_id = getattr(
                entity,
                "item_id",
                getattr(entity, "stay_id", getattr(entity, "transport_leg_id", "")),
            )
            day_id = getattr(entity, "day_id", None) or timeline_day.get(entity_id)
            candidate = candidate_index.get(entity.lineage.candidate_id)
            rows.append(
                {
                    **objects[entity_id].model_dump(),
                    "kind": kind,
                    "entity_id": entity_id,
                    "day_id": day_id,
                    "destination_id": (
                        day_context.get(day_id, (None, None))[1]
                        or getattr(candidate, "destination_id", None)
                    ),
                    "candidate_id": entity.lineage.candidate_id,
                    "label": getattr(
                        entity,
                        "name",
                        getattr(
                            entity,
                            "property_name",
                            getattr(entity, "transport_leg_id", entity_id),
                        ),
                    ),
                    "fact_ids": list(entity.lineage.fact_assertion_ids),
                    "planned_start": getattr(
                        entity,
                        "planned_start",
                        getattr(entity, "departure_at", None),
                    ),
                    "intent_explanations": list(
                        getattr(entity, "intent_explanations", [])
                    ),
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            timeline_order.get(row["entity_id"], (10**6, 10**6)),
            row["kind"],
            row["entity_id"],
        ),
    )


def _domain_kind(rule: CompositionRule) -> str | None:
    if rule.target_domain is None:
        return None
    return {
        "visit": "visit",
        "dining": "dining",
        "lodging": "lodging",
        "local_transport": "transport",
        "long_distance_transport": "transport",
    }[rule.target_domain.value]


def _window_matches(value: datetime | None, window: str) -> bool:
    if value is None:
        return False
    normalized = window.casefold()
    hour = value.hour
    if "afternoon" in normalized or "下午" in normalized:
        return 12 <= hour < 18
    if "morning" in normalized or "上午" in normalized:
        return 5 <= hour < 12
    if "evening" in normalized or "晚上" in normalized or "晚间" in normalized:
        return 18 <= hour <= 23
    if "lunch" in normalized or "午餐" in normalized:
        return 11 <= hour < 14
    if "dinner" in normalized or "晚餐" in normalized:
        return 17 <= hour < 22
    return True


def _gap_reason(rule: CompositionRule | None, status: IntentCoverageStatus) -> str:
    if rule is None:
        return (
            "intent_evidence_unavailable"
            if status is IntentCoverageStatus.UNVERIFIABLE
            else "semantic_coverage_low"
        )
    return {
        CompositionRuleKind.MUST_PLACE: "required_candidate_missing",
        CompositionRuleKind.MUST_NOT_PLACE: "excluded_candidate_present",
        CompositionRuleKind.MAX_PER_DAY: "quantity_rule_violated",
        CompositionRuleKind.MIN_PER_DAY: "quantity_rule_violated",
        CompositionRuleKind.CADENCE: "cadence_rule_missing",
        CompositionRuleKind.TIME_WINDOW: "time_window_violated",
        CompositionRuleKind.SEQUENCE: "sequence_rule_violated",
        CompositionRuleKind.DESTINATION_SCOPE: "semantic_coverage_low",
        CompositionRuleKind.REST_WINDOW: "time_window_violated",
        CompositionRuleKind.MAX_TRAVEL_TIME: "quantity_rule_violated",
        CompositionRuleKind.OUTPUT_EXPLANATION: "output_requirement_missing",
    }[rule.rule_kind]


def _retry_target(
    rule: CompositionRule | None,
    *,
    any_catalog_match: bool,
    any_selected_match: bool,
) -> str:
    if rule is None:
        return "none"
    if rule.rule_kind is CompositionRuleKind.OUTPUT_EXPLANATION:
        return "delivery_projection"
    if rule.rule_kind is CompositionRuleKind.MUST_PLACE:
        if not any_catalog_match:
            return "candidate_gate"
        if not any_selected_match:
            return "candidate_selection"
    if rule.rule_kind in {
        CompositionRuleKind.MUST_PLACE,
        CompositionRuleKind.MUST_NOT_PLACE,
        CompositionRuleKind.MAX_PER_DAY,
        CompositionRuleKind.MIN_PER_DAY,
        CompositionRuleKind.CADENCE,
        CompositionRuleKind.TIME_WINDOW,
        CompositionRuleKind.SEQUENCE,
    }:
        return "itinerary_planner"
    return "none"


def _delivered_alternative_count(workspace: TripWorkspaceV2) -> int:
    """Count choice options the delivery can actually show beyond selections.

    Candidate Selection roles control composition eligibility; they are not the
    public alternatives contract.  A candidate can be required for composition
    and still be an unselected option in another typed Selection Slot.  Fidelity
    therefore audits the materialized choice surface first, while the selection
    plan remains a fallback for pre-slot/direct-node callers.
    """

    count = 0
    for slot in getattr(workspace, "selection_slots", []) or []:
        options = list(getattr(slot, "options", []) or [])
        selected_option_id = getattr(slot, "selected_option_id", None)
        if selected_option_id is None:
            count += max(len(options) - 1, 0)
            continue
        count += sum(
            getattr(option, "option_id", None) != selected_option_id
            for option in options
        )
    return count
