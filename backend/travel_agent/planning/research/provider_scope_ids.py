"""Planning research provider scope ids."""

from __future__ import annotations

from travel_agent.planning.research.domains import ResearchDomain
from typing import Optional, TYPE_CHECKING
import hashlib
import json


def provider_evidence_scope_id(
    *,
    run_id: str,
    constraint_pack_revision: int,
    worker_kind: ProviderEvidenceWorkerKind,
    research_domain: ResearchDomain,
    candidate_kind: Optional[ProviderEvidenceCandidateKind],
    transport_class: Optional[ProviderEvidenceTransportClass],
    target_identity: Optional[str],
    route_leg: Optional[ProviderRouteLegScope],
) -> str:
    material = {
        "run_id": run_id,
        "constraint_pack_revision": constraint_pack_revision,
        "worker_kind": worker_kind,
        "research_domain": research_domain.value,
        "candidate_kind": candidate_kind,
        "transport_class": transport_class,
        "target_identity": target_identity,
        "route_leg": (
            route_leg.model_dump(mode="json") if route_leg is not None else None
        ),
    }
    return hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


if TYPE_CHECKING:
    from travel_agent.planning.research.provider_contracts import (
        ProviderEvidenceCandidateKind,
    )
    from travel_agent.planning.research.provider_contracts import (
        ProviderEvidenceTransportClass,
    )
    from travel_agent.planning.research.provider_contracts import (
        ProviderEvidenceWorkerKind,
    )
    from travel_agent.planning.research.provider_contracts import ProviderRouteLegScope
