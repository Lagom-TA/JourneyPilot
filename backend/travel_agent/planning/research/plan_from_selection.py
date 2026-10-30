"""Compile a model's ID-only selection into a bounded research plan.

The caller must bind ``selection_input`` to the current clarified request
contract. This function checks exact ID/label/domain alignment again; it does not
make an unclarified candidate authoritative.
"""

from __future__ import annotations

from travel_agent.planning.requirements.research_plan_contracts import (
    ResearchDomainPlanDraft, ResearchPlanDraft,
)
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.selection import (
    CandidateSelectionInput, CandidateSelectionResult, CandidateSelectionStatus,
)


def plan_from_authorized_selection(
    selection_input: CandidateSelectionInput, result: CandidateSelectionResult,
) -> ResearchPlanDraft:
    """Reject stale, forged or unrepresentable selections; never invent a fallback."""
    selection_input = CandidateSelectionInput.model_validate(selection_input.model_dump(mode="json"))
    result = CandidateSelectionResult.model_validate(result.model_dump(mode="json"))
    if result.status is not CandidateSelectionStatus.SELECTED or result.projection is None:
        raise ValueError("model selection is not complete")
    if result.confirmation_digest != selection_input.confirmation_digest:
        raise ValueError("model selection belongs to a different confirmation")
    if set(result.projection) != {domain.value for domain in selection_input.required_domains}:
        raise ValueError("model selection does not cover the authorized domains")

    candidates = {item.candidate_id: item for item in selection_input.candidates}
    rows = []
    for domain in sorted(selection_input.required_domains, key=lambda value: value.value):
        projected = result.projection[domain.value]
        if len(projected.search_candidate_ids) > 3:
            raise ValueError("model selection exceeds the executable query limit")
        for ids, labels in (
            (projected.focus_candidate_ids, projected.focus_labels),
            (projected.search_candidate_ids, projected.search_labels),
        ):
            if len(ids) != len(set(ids)):
                raise ValueError("model selection contains duplicate candidates")
            for candidate_id, label in zip(ids, labels):
                candidate = candidates.get(candidate_id)
                if candidate is None or candidate.domain is not domain or candidate.label != label:
                    raise ValueError("model selection does not match an authorized candidate")
        rows.append(ResearchDomainPlanDraft(
            domain=ResearchDomain(domain),
            focus_atoms=list(projected.focus_labels),
            search_terms=list(projected.search_labels),
            focus_candidate_ids=list(projected.focus_candidate_ids),
            search_candidate_ids=list(projected.search_candidate_ids),
        ))
    return ResearchPlanDraft(domains=rows)
