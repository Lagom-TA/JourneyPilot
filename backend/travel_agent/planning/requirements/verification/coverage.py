"""Planning requirements verification coverage."""

from __future__ import annotations

from collections import defaultdict
from travel_agent.planning.requirements.composition_contracts import CompositionRule
from travel_agent.planning.requirements.coverage_contracts import CoverageEntityRef
from travel_agent.planning.requirements.coverage_contracts import IntentCoverageItem
from travel_agent.planning.requirements.coverage_contracts import IntentCoverageReport
from travel_agent.planning.requirements.coverage_contracts import IntentCoverageStatus
from travel_agent.planning.requirements.coverage_contracts import IntentDeviation
from travel_agent.planning.requirements.coverage_contracts import IntentFidelityGap
from travel_agent.planning.requirements.entity_checks import check_final_entities
from travel_agent.planning.requirements.intent_contracts import AlternativeIntentValue
from travel_agent.planning.requirements.intent_contracts import IntentKind
from travel_agent.planning.requirements.intent_contracts import IntentSpec
from travel_agent.planning.requirements.intent_contracts import IntentStrength
from travel_agent.planning.requirements.intent_contracts import canonical_json_hash
from travel_agent.planning.requirements.snapshot_contracts import IntentContractSnapshot
from travel_agent.planning.requirements.verification.entities import (
    _delivered_alternative_count,
)
from travel_agent.planning.requirements.verification.entities import _entity_rows
from travel_agent.planning.requirements.verification.entities import _gap_reason
from travel_agent.planning.requirements.verification.entities import _retry_target
from travel_agent.planning.requirements.verification.rules import _evaluate_rule
from travel_agent.planning.research.selection_contracts import CandidateSelectionRole
from travel_agent.planning.workspace import TripWorkspaceV2
from typing import Iterable


def evaluate_intent_fidelity(
    *,
    intent_spec: IntentSpec | IntentContractSnapshot,
    rules: Iterable[CompositionRule],
    workspace: TripWorkspaceV2,
    repair_budget_exhausted: bool,
) -> tuple[IntentCoverageReport, list[IntentFidelityGap]]:
    rules_by_intent: dict[str, list[CompositionRule]] = defaultdict(list)
    for rule in rules:
        rules_by_intent[rule.intent_id].append(rule)
    rows = _entity_rows(workspace)
    entity_checks = check_final_entities(workspace, intent_spec)
    selected_candidate_ids = (
        workspace.candidate_selection_plan.composition_candidate_ids()
    )
    matches = workspace.recommendation_catalog.candidate_intent_matches
    matched_by_intent: dict[str, set[str]] = defaultdict(set)
    violated_by_intent: dict[str, set[str]] = defaultdict(set)
    unknown_by_intent: dict[str, set[str]] = defaultdict(set)
    facts_by_intent: dict[str, set[str]] = defaultdict(set)
    for match in matches:
        if match.status.value == "matched":
            matched_by_intent[match.intent_id].add(match.candidate_id)
            facts_by_intent[match.intent_id].update(match.supporting_fact_assertion_ids)
        elif match.status.value == "violated":
            violated_by_intent[match.intent_id].add(match.candidate_id)
            facts_by_intent[match.intent_id].update(match.supporting_fact_assertion_ids)
        elif match.status.value == "unknown":
            unknown_by_intent[match.intent_id].add(match.candidate_id)
    day_number = {day.day_id: day.day for day in workspace.itinerary.day_plans}
    destination_ids = {day.destination_id for day in workspace.itinerary.day_plans}
    candidate_labels = {
        candidate.candidate_id: getattr(
            candidate,
            "name",
            getattr(
                candidate,
                "branch_name",
                getattr(candidate, "property_name", candidate.candidate_id),
            ),
        )
        for candidate in workspace.recommendation_catalog.candidate_index().values()
    }
    conflicted_intent_ids = (
        set(intent_spec.conflicted_intent_ids)
        if isinstance(intent_spec, IntentContractSnapshot)
        else {
            intent_id
            for conflict in intent_spec.conflicts
            for intent_id in conflict.intent_ids
        }
    )
    items: list[IntentCoverageItem] = []
    gaps: list[IntentFidelityGap] = []
    deviations: list[IntentDeviation] = []
    for intent in intent_spec.active_items:
        intent_rules = rules_by_intent.get(intent.intent_id, [])
        evaluations = [
            (
                rule,
                *_evaluate_rule(
                    rule,
                    rows=rows,
                    matched_candidates=matched_by_intent[intent.intent_id],
                    violated_candidates=violated_by_intent[intent.intent_id],
                    unknown_candidates=unknown_by_intent[intent.intent_id],
                    day_number=day_number,
                    destination_ids=destination_ids,
                    candidate_labels=candidate_labels,
                    entity_checks={
                        check.entity_id: check.status
                        for check in entity_checks
                        if check.intent_id == intent.intent_id
                    },
                ),
            )
            for rule in intent_rules
        ]
        if intent.intent_id in conflicted_intent_ids:
            evaluations = [(None, IntentCoverageStatus.CONFLICTED, [], [], [])]
        elif intent.kind is IntentKind.OBJECTIVE:
            status = (
                IntentCoverageStatus.SATISFIED
                if workspace.itinerary.day_plans
                else IntentCoverageStatus.UNSATISFIED
            )
            evaluations = [(None, status, rows, [], [])]
        elif intent.kind is IntentKind.DIVERSITY:
            selection_policy = workspace.candidate_selection_plan.selection_policy
            status = (
                IntentCoverageStatus.SATISFIED
                if selection_policy.mode == "explore"
                else IntentCoverageStatus.UNSATISFIED
            )
            evaluations = [(None, status, [], [], [])]
        elif intent.kind is IntentKind.ALTERNATIVES:
            selection_policy = workspace.candidate_selection_plan.selection_policy
            planned_alternative_count = sum(
                entry.role is CandidateSelectionRole.ALTERNATIVE
                for entry in workspace.candidate_selection_plan.entries
            )
            delivered_alternative_count = _delivered_alternative_count(workspace)
            requested_count = (
                intent.value.count
                if isinstance(intent.value, AlternativeIntentValue)
                else 2
            )
            status = (
                IntentCoverageStatus.SATISFIED
                if delivered_alternative_count >= requested_count - 1
                or (
                    selection_policy.mode == "explore"
                    and planned_alternative_count >= requested_count - 1
                )
                else IntentCoverageStatus.UNSATISFIED
            )
            evaluations = [(None, status, [], [], [])]
        elif not evaluations:
            matched_rows = [
                row
                for row in rows
                if row["candidate_id"] in matched_by_intent[intent.intent_id]
            ]
            if matched_rows:
                status = IntentCoverageStatus.SATISFIED
            elif unknown_by_intent[intent.intent_id]:
                status = IntentCoverageStatus.UNVERIFIABLE
            else:
                status = IntentCoverageStatus.UNSATISFIED
            evaluations = [(None, status, matched_rows, [], [])]
        statuses = [evaluation[1] for evaluation in evaluations]
        if IntentCoverageStatus.UNSATISFIED in statuses:
            status = IntentCoverageStatus.UNSATISFIED
        elif IntentCoverageStatus.CONFLICTED in statuses:
            status = IntentCoverageStatus.CONFLICTED
        elif IntentCoverageStatus.UNVERIFIABLE in statuses:
            status = IntentCoverageStatus.UNVERIFIABLE
        elif IntentCoverageStatus.PARTIALLY_SATISFIED in statuses:
            status = IntentCoverageStatus.PARTIALLY_SATISFIED
        else:
            status = IntentCoverageStatus.SATISFIED
        supporting_rows = {
            row["entity_id"]: row
            for _rule_value, _status, matched_rows, _covered, _missing in evaluations
            for row in matched_rows
        }
        failed_rules = [
            rule
            for rule, evaluation_status, _rows, _covered, _missing in evaluations
            if rule is not None
            and evaluation_status is not IntentCoverageStatus.SATISFIED
        ]
        covered_days = sorted(
            {
                day
                for _rule_value, _status, _rows, covered, _missing in evaluations
                for day in covered
            }
        )
        missing_days = sorted(
            {
                day
                for _rule_value, _status, _rows, _covered, missing in evaluations
                for day in missing
            }
        )
        hard = intent.strength is IntentStrength.HARD
        never_violate = status is IntentCoverageStatus.UNSATISFIED and any(
            rule.policy_on_failure == "never_violate" for rule in failed_rules
        )
        blocking = (
            hard
            and status is not IntentCoverageStatus.SATISFIED
            and (never_violate or not repair_budget_exhausted)
        )
        public_explanation = (
            f"已落实：{intent.public_summary}"
            if status is IntentCoverageStatus.SATISFIED
            else f"{intent.public_summary}：{status.value}"
        )
        item = IntentCoverageItem(
            intent_id=intent.intent_id,
            status=status,
            supporting_entity_refs=[
                CoverageEntityRef(entity_type=row["kind"], entity_id=row["entity_id"])
                for row in supporting_rows.values()
            ]
            if not never_violate
            else [],
            supporting_candidate_ids=sorted(
                {
                    row["candidate_id"]
                    for row in supporting_rows.values()
                    if row["candidate_id"]
                }
            ),
            supporting_fact_assertion_ids=sorted(facts_by_intent[intent.intent_id]),
            violated_entity_refs=[
                CoverageEntityRef(entity_type=row["kind"], entity_id=row["entity_id"])
                for row in supporting_rows.values()
            ]
            if never_violate
            else [],
            covered_days=covered_days,
            missing_days=missing_days,
            verification_mode=intent.verification_mode,
            public_explanation=public_explanation,
            blocking=blocking,
        )
        items.append(item)
        if status is IntentCoverageStatus.SATISFIED:
            continue
        primary_rule = (
            failed_rules[0]
            if failed_rules
            else (intent_rules[0] if intent_rules else None)
        )
        reason = (
            "intent_evidence_unavailable"
            if status is IntentCoverageStatus.UNVERIFIABLE
            else _gap_reason(primary_rule, status)
        )
        retry_target = _retry_target(
            primary_rule,
            any_catalog_match=bool(matched_by_intent[intent.intent_id]),
            any_selected_match=bool(
                matched_by_intent[intent.intent_id] & selected_candidate_ids
            ),
        )
        material = {
            "generation_id": intent_spec.generation_id,
            "intent_id": intent.intent_id,
            "reason": reason,
            "workspace_revision": workspace.workspace_revision,
        }
        gap_id = f"intent_gap_{canonical_json_hash(material)[:24]}"
        gaps.append(
            IntentFidelityGap(
                gap_id=gap_id,
                intent_id=intent.intent_id,
                reason=reason,
                blocking=blocking,
                retry_target=retry_target,
                affected_entity_ids=sorted(supporting_rows),
                violated_rule_ids=sorted(rule.rule_id for rule in failed_rules),
                repair_context={"missing_days": missing_days},
            )
        )
        deviations.append(
            IntentDeviation(
                deviation_id=f"intent_deviation_{canonical_json_hash(material)[:24]}",
                intent_id=intent.intent_id,
                status=status.value,
                reason_code=reason,
                public_explanation=public_explanation,
            )
        )
    strength_by_intent = {
        intent.intent_id: intent.strength for intent in intent_spec.active_items
    }
    hard_items = [
        item
        for item in items
        if strength_by_intent[item.intent_id] is IntentStrength.HARD
    ]
    soft_items = [item for item in items if item not in hard_items]
    hard_rate = (
        sum(item.status is IntentCoverageStatus.SATISFIED for item in hard_items)
        / len(hard_items)
        if hard_items
        else 1.0
    )
    soft_rate = (
        sum(
            1.0
            if item.status is IntentCoverageStatus.SATISFIED
            else 0.5
            if item.status is IntentCoverageStatus.PARTIALLY_SATISFIED
            else 0.0
            for item in soft_items
        )
        / len(soft_items)
        if soft_items
        else 1.0
    )
    material = {
        "generation_id": intent_spec.generation_id,
        "intent_spec_revision": intent_spec.revision,
        "workspace_revision": workspace.workspace_revision,
        "items": [item.model_dump(mode="json") for item in items],
        "deviations": [item.model_dump(mode="json") for item in deviations],
    }
    content_hash = canonical_json_hash(material)
    report = IntentCoverageReport(
        coverage_report_id=f"intent_coverage_{content_hash[:24]}",
        generation_id=intent_spec.generation_id,
        intent_spec_revision=intent_spec.revision,
        workspace_revision=workspace.workspace_revision,
        items=items,
        hard_satisfaction_rate=hard_rate,
        soft_coverage_rate=soft_rate,
        blocking_gap_ids=[gap.gap_id for gap in gaps if gap.blocking],
        deviations=deviations,
        content_hash=content_hash,
    )
    return report, gaps
