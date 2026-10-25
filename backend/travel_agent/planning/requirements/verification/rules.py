"""Planning requirements verification rules."""

from __future__ import annotations

from collections import defaultdict
from travel_agent.planning.requirements.candidate_match_contracts import (
    IntentMatchStatus,
)
from travel_agent.planning.requirements.composition_contracts import (
    CadenceRuleParameters,
)
from travel_agent.planning.requirements.composition_contracts import CompositionRule
from travel_agent.planning.requirements.composition_contracts import CompositionRuleKind
from travel_agent.planning.requirements.composition_contracts import CountRuleParameters
from travel_agent.planning.requirements.composition_contracts import (
    OutputExplanationRuleParameters,
)
from travel_agent.planning.requirements.composition_contracts import (
    SequenceRuleParameters,
)
from travel_agent.planning.requirements.composition_contracts import (
    TimeWindowRuleParameters,
)
from travel_agent.planning.requirements.coverage_contracts import IntentCoverageStatus
from travel_agent.planning.requirements.verification.entities import _domain_kind
from travel_agent.planning.requirements.verification.entities import _window_matches


def _evaluate_rule(
    rule: CompositionRule,
    *,
    rows: list[dict],
    matched_candidates: set[str],
    violated_candidates: set[str],
    unknown_candidates: set[str],
    day_number: dict[str, int],
    destination_ids: set[str],
    candidate_labels: dict[str, str],
    entity_checks: dict[str, IntentMatchStatus],
) -> tuple[IntentCoverageStatus, list[dict], list[int], list[int]]:
    kind = _domain_kind(rule)
    scoped = [row for row in rows if kind is None or row["kind"] == kind]
    matched = [row for row in scoped if row["candidate_id"] in matched_candidates]
    unknown = [row for row in scoped if row["candidate_id"] in unknown_candidates]
    all_days = sorted(day_number.values())
    if rule.rule_kind is CompositionRuleKind.MUST_NOT_PLACE:
        violated = [
            row
            for row in scoped
            if entity_checks.get(row["entity_id"]) is IntentMatchStatus.VIOLATED
        ]
        unchecked = [
            row
            for row in scoped
            if entity_checks.get(row["entity_id"], IntentMatchStatus.UNKNOWN)
            is IntentMatchStatus.UNKNOWN
        ]
        return (
            IntentCoverageStatus.UNSATISFIED
            if violated
            else IntentCoverageStatus.UNVERIFIABLE
            if unchecked
            else IntentCoverageStatus.SATISFIED,
            violated or unchecked,
            [],
            [],
        )
    if rule.rule_kind is CompositionRuleKind.MUST_PLACE:
        if matched:
            return IntentCoverageStatus.SATISFIED, matched, [], []
        if unknown:
            return IntentCoverageStatus.UNVERIFIABLE, unknown, [], []
        return IntentCoverageStatus.UNSATISFIED, [], [], []
    if rule.rule_kind in {
        CompositionRuleKind.MAX_PER_DAY,
        CompositionRuleKind.MIN_PER_DAY,
    }:
        assert isinstance(rule.parameters, CountRuleParameters)
        counts: dict[int, int] = defaultdict(int)
        for row in scoped:
            if row["day_id"] in day_number:
                counts[day_number[row["day_id"]]] += 1
        if rule.parameters.unit == "day":
            if rule.rule_kind is CompositionRuleKind.MAX_PER_DAY:
                missing = [
                    day for day in all_days if counts[day] > rule.parameters.count
                ]
            else:
                missing = [
                    day for day in all_days if counts[day] < rule.parameters.count
                ]
            covered = [day for day in all_days if day not in missing]
            return (
                IntentCoverageStatus.SATISFIED
                if not missing
                else IntentCoverageStatus.UNSATISFIED,
                scoped,
                covered,
                missing,
            )
        if rule.parameters.unit == "destination":
            destinations = sorted(destination_ids)
            counts = {
                destination_id: sum(
                    row["destination_id"] == destination_id for row in scoped
                )
                for destination_id in destinations
            }
            passed = all(
                count <= rule.parameters.count
                if rule.rule_kind is CompositionRuleKind.MAX_PER_DAY
                else count >= rule.parameters.count
                for count in counts.values()
            )
            return (
                IntentCoverageStatus.SATISFIED
                if destinations and passed
                else IntentCoverageStatus.UNSATISFIED,
                scoped,
                [],
                [],
            )
        total = len(scoped)
        passed = (
            total <= rule.parameters.count
            if rule.rule_kind is CompositionRuleKind.MAX_PER_DAY
            else total >= rule.parameters.count
        )
        return (
            IntentCoverageStatus.SATISFIED
            if passed
            else IntentCoverageStatus.UNSATISFIED,
            scoped,
            all_days if passed else [],
            [] if passed else all_days,
        )
    if rule.rule_kind is CompositionRuleKind.CADENCE:
        assert isinstance(rule.parameters, CadenceRuleParameters)
        relevant = matched if rule.parameters.required_attributes else scoped
        if rule.parameters.frequency == "once_per_day":
            counts: dict[int, int] = defaultdict(int)
            for row in relevant:
                if row["day_id"] in day_number:
                    counts[day_number[row["day_id"]]] += 1
            missing = [day for day in all_days if counts[day] < rule.parameters.count]
            if rule.parameters.time_window:
                missing.extend(
                    day_number[row["day_id"]]
                    for row in relevant
                    if row["day_id"] in day_number
                    and not _window_matches(
                        row["planned_start"], rule.parameters.time_window
                    )
                )
            missing = sorted(set(missing))
            return (
                IntentCoverageStatus.SATISFIED
                if not missing
                else IntentCoverageStatus.UNSATISFIED,
                relevant,
                [day for day in all_days if day not in missing],
                missing,
            )
        if rule.parameters.frequency == "once_per_destination":
            destinations = destination_ids
            counts = {
                destination_id: sum(
                    row["destination_id"] == destination_id for row in relevant
                )
                for destination_id in destinations
            }
            passed = bool(destinations) and all(
                count >= rule.parameters.count for count in counts.values()
            )
            return (
                IntentCoverageStatus.SATISFIED
                if passed
                else IntentCoverageStatus.UNSATISFIED,
                relevant,
                [],
                [],
            )
        passed = len(relevant) >= rule.parameters.count
        return (
            IntentCoverageStatus.SATISFIED
            if passed
            else IntentCoverageStatus.UNSATISFIED,
            relevant,
            [],
            [],
        )
    if rule.rule_kind is CompositionRuleKind.TIME_WINDOW:
        assert isinstance(rule.parameters, TimeWindowRuleParameters)
        relevant = matched if rule.parameters.applies_to else scoped
        failed = [
            row
            for row in relevant
            if not _window_matches(row["planned_start"], rule.parameters.window)
        ]
        return (
            IntentCoverageStatus.SATISFIED
            if relevant and not failed
            else IntentCoverageStatus.UNSATISFIED,
            relevant,
            [],
            sorted(
                {
                    day_number[row["day_id"]]
                    for row in failed
                    if row["day_id"] in day_number
                }
            ),
        )
    if rule.rule_kind is CompositionRuleKind.SEQUENCE:
        assert isinstance(rule.parameters, SequenceRuleParameters)
        order = [
            candidate_labels.get(row["candidate_id"], row["label"]) for row in rows
        ]
        positions = [
            next(
                (
                    index
                    for index, value in enumerate(order)
                    if item.casefold() in value.casefold()
                ),
                -1,
            )
            for item in rule.parameters.ordered_items
        ]
        passed = all(index >= 0 for index in positions) and positions == sorted(
            positions
        )
        return (
            IntentCoverageStatus.SATISFIED
            if passed
            else IntentCoverageStatus.UNSATISFIED,
            matched,
            [],
            [],
        )
    if rule.rule_kind is CompositionRuleKind.OUTPUT_EXPLANATION:
        assert isinstance(rule.parameters, OutputExplanationRuleParameters)
        if rule.parameters.applies_to in {"trip", "delivery"}:
            return IntentCoverageStatus.SATISFIED, [], [], []
        explained = [
            row
            for row in scoped
            if any(
                explanation.intent_id == rule.intent_id
                for explanation in row.get("intent_explanations", [])
            )
        ]
        if rule.parameters.applies_to == "each_day":
            explained_days = {
                day_number[row["day_id"]]
                for row in explained
                if row["day_id"] in day_number
            }
            passed = explained_days == set(all_days)
        else:
            passed = bool(explained) and len(explained) == len(scoped)
        return (
            IntentCoverageStatus.SATISFIED
            if passed
            else IntentCoverageStatus.UNSATISFIED,
            explained,
            [],
            [],
        )
    if matched:
        return IntentCoverageStatus.SATISFIED, matched, [], []
    if unknown:
        return IntentCoverageStatus.UNVERIFIABLE, unknown, [], []
    return IntentCoverageStatus.UNSATISFIED, [], [], []
