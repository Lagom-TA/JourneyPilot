"""Planning requirements verification workspace."""

from __future__ import annotations

from travel_agent.planning.requirements.coverage_contracts import IntentCoverageReport
from travel_agent.planning.requirements.coverage_contracts import IntentFidelityGap
from travel_agent.planning.requirements.verification.coverage import (
    evaluate_intent_fidelity,
)
from travel_agent.planning.workspace import TripWorkspaceV2


def revalidate_workspace_intent(
    workspace: TripWorkspaceV2,
) -> tuple[TripWorkspaceV2, IntentCoverageReport, list[IntentFidelityGap]]:
    from travel_agent.planning.requirements.composition_compiler import (
        compile_composition_rules,
    )
    from travel_agent.planning.requirements.entity_binding import bind_intent_context

    intent_contract = workspace.intent_contract_snapshot
    bound = bind_intent_context(workspace, intent_contract)
    rules = compile_composition_rules(intent_contract)
    report, gaps = evaluate_intent_fidelity(
        intent_spec=intent_contract,
        rules=rules,
        workspace=bound,
        repair_budget_exhausted=True,
    )
    rules_by_id = {rule.rule_id: rule for rule in rules}
    if any(
        rules_by_id[rule_id].policy_on_failure == "never_violate"
        and gap.reason != "intent_evidence_unavailable"
        for gap in gaps
        for rule_id in gap.violated_rule_ids
    ):
        raise ValueError("workspace mutation violates a never-violate intent rule")
    updated = bound.model_copy(update={"intent_coverage_report": report})
    return TripWorkspaceV2.model_validate(updated.model_dump(mode="json")), report, gaps
