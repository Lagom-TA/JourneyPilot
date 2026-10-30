from __future__ import annotations

from typing import Any, Mapping

from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity
from travel_agent.planning.requirements.intent_contracts import canonical_json_hash
from travel_agent.planning.requirements.request_contracts import RequestContract
from travel_agent.planning.requirements.revision import request_contract_with_research_plan
from travel_agent.planning.research.brief_builder import required_research_domains
from travel_agent.planning.research.research_plan_validation import grounded_research_atoms
from travel_agent.planning.research.selection import AuthorizedCandidate, CandidateSelectionInput


def build_authorized_candidate_selection(
    contract: RequestContract,
    controlled_identity: Mapping[str, Any],
    confirmation_digest: str,
) -> CandidateSelectionInput:
    identity = ControlledTripIdentity.model_validate(controlled_identity)
    candidate_contract = request_contract_with_research_plan(contract, None)
    if confirmation_digest != candidate_contract.content_hash:
        raise ValueError("research candidates require the matching clarified contract")
    required_domains = required_research_domains(candidate_contract, controlled_identity)
    candidates = []
    per_domain_limit = min(12, max(1, 40 // len(required_domains)))
    for domain in sorted(required_domains, key=lambda item: item.value):
        atoms = grounded_research_atoms(
            identity=identity,
            active_items=candidate_contract.intent_spec.active_items,
            constraint_pack=candidate_contract.constraint_pack,
            clause_texts=[
                item.source_text
                for item in candidate_contract.intent_spec.active_items
                if item.source_kind in {"current_request", "plan_gate_amendment", "run_supplement"}
                and item.source_text
            ],
            domain=domain,
        )
        for label in atoms[:per_domain_limit]:
            candidate_id = "candidate_" + canonical_json_hash({
                "domain": domain.value,
                "label": label,
            })[:24]
            candidates.append(AuthorizedCandidate(
                candidate_id=candidate_id,
                domain=domain,
                label=label,
            ))
    return CandidateSelectionInput(
        confirmation_digest=confirmation_digest,
        required_domains=frozenset(required_domains),
        candidates=frozenset(candidates),
    )
