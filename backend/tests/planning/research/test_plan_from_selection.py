"""The selected plan retains its server-owned candidate provenance."""

import json

import pytest

from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.plan_from_selection import plan_from_authorized_selection
from travel_agent.planning.research.selection import (
    AuthorizedCandidate, CandidateSelectionInput, select_research_candidates,
)


class Model:
    async def ainvoke(self, _messages, **_kwargs):
        return json.dumps({"domains": {"visit": {"focus_candidate_ids": ["museum"], "search_candidate_ids": ["park"]}}})


async def test_selection_compiles_only_confirmed_candidate_ids_and_labels():
    allowed = CandidateSelectionInput(
        confirmation_digest="a" * 64, required_domains=frozenset({ResearchDomain.VISIT}),
        candidates=frozenset({
            AuthorizedCandidate(candidate_id="museum", domain=ResearchDomain.VISIT, label="博物馆"),
            AuthorizedCandidate(candidate_id="park", domain=ResearchDomain.VISIT, label="公园"),
        }),
    )
    result = await select_research_candidates(allowed, Model())
    plan = plan_from_authorized_selection(allowed, result)
    assert plan.domains[0].focus_atoms == ["博物馆"]
    assert plan.domains[0].focus_candidate_ids == ["museum"]
    assert plan.domains[0].search_terms == ["公园"]
    assert plan.domains[0].search_candidate_ids == ["park"]
    assert plan == plan_from_authorized_selection(allowed, result)

    stale = result.model_copy(update={"confirmation_digest": "b" * 64})
    with pytest.raises(ValueError, match="different confirmation"):
        plan_from_authorized_selection(allowed, stale)
    altered = result.projection["visit"].model_copy(update={"search_labels": ("东京",)})
    poisoned = result.model_copy(update={"projection": {"visit": altered}})
    with pytest.raises(ValueError, match="authorized candidate"):
        plan_from_authorized_selection(allowed, poisoned)


@pytest.mark.parametrize("label", ["公园  步道", "New\u00a0York"])
async def test_approved_candidate_label_is_not_rewritten_by_plan_compilation(label):
    class SingleModel:
        async def ainvoke(self, _messages, **_kwargs):
            return json.dumps({"domains": {"visit": {"focus_candidate_ids": ["path"], "search_candidate_ids": ["path"]}}})

    allowed = CandidateSelectionInput(
        confirmation_digest="a" * 64, required_domains=frozenset({ResearchDomain.VISIT}),
        candidates=frozenset({AuthorizedCandidate(candidate_id="path", domain=ResearchDomain.VISIT, label=label)}),
    )
    result = await select_research_candidates(allowed, SingleModel())
    plan = plan_from_authorized_selection(allowed, result)
    assert plan.domains[0].focus_atoms == [label]
    assert plan.domains[0].search_terms == [label]
