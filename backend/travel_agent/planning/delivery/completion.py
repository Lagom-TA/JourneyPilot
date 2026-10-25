"""Planning delivery completion."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from travel_agent.planning.completion_audit import build_trip_run_completion_audit
from travel_agent.planning.delivery.bundle import DeliveryBundle, RunCoverageDisclosure
from travel_agent.planning.outcomes import (
    DeliveryFailureRecord,
    GateClass,
    TerminalAttribution,
)
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.workspace import TripWorkspaceV2


class DeliveryFinalizationError(RuntimeError):
    def __init__(self, record: DeliveryFailureRecord, cause: Exception):
        super().__init__(record.public_message)
        self.record = record
        self.__cause__ = cause


def _terminal_recorded_at(
    state: TravelAgentState, bundle: Optional[DeliveryBundle] = None
) -> datetime:
    """Use the durable deadline observation, never a fresh lifecycle clock."""

    if state.run_deadline is not None:
        return state.run_deadline.last_observed_at
    if bundle is not None:
        return bundle.manifest.created_at
    if state.minimum_delivery_draft is not None:
        return state.minimum_delivery_draft.planning_authorized_at
    return datetime.now(timezone.utc)


def _completion_audit_with_terminal(
    state: TravelAgentState,
    *,
    closure_status: str,
    reason_code: str,
    gate_class: Optional[GateClass] = None,
    bundle: Optional[DeliveryBundle] = None,
) -> Dict[str, Any]:
    """Bind the final lifecycle outcome to the sealed Draft's audit projection."""

    audit = build_trip_run_completion_audit(state)
    draft = state.minimum_delivery_draft
    if not audit or draft is None:
        return audit
    if bundle is not None:
        document = bundle.report_projection.document
        audit["formal_delivery"] = {
            "bundle_id": bundle.manifest.bundle_id,
            "has_bundle": True,
            "report_ready": bundle.report_projection.status == "ready",
            "report_content_nonempty": bool(
                document and (document.days or document.overview or document.title)
            ),
            "projection_consistent": True,
        }
    terminal = TerminalAttribution(
        draft_id=draft.draft_id,
        closure_status=closure_status,
        reason_code=reason_code,
        recorded_at=_terminal_recorded_at(state, bundle),
        delivery_bundle_id=(bundle.manifest.bundle_id if bundle is not None else None),
        gate_class=gate_class,
    )
    audit["terminal_attribution"] = terminal.model_dump(mode="json")
    return audit


def _require_sealed_completion_generation(state: TravelAgentState) -> None:
    """Reject direct finalization that bypasses the authorized 5/6/8 contract."""

    draft = state.minimum_delivery_draft
    if (
        draft is None
        or draft.run_id != state.run_id
        or not draft.planning_authorized
        or draft.planning_authorized_at is None
    ):
        raise ValueError(
            "delivery finalizer requires a sealed minimum delivery draft for this run"
        )
    deadline = state.run_deadline
    if (
        deadline is None
        or deadline.draft_id != draft.draft_id
        or deadline.planning_authorized_at != draft.planning_authorized_at
    ):
        raise ValueError(
            "delivery finalizer requires the sealed Draft deadline snapshot"
        )


def reduce_coverage_disclosure(state: TravelAgentState) -> RunCoverageDisclosure:
    """Say which research domains this Run finished without usable results for."""

    domains: list[ResearchDomain] = []
    for gap in state.delivery_quality_gaps:
        if gap.research_domain is not None and gap.research_domain not in domains:
            domains.append(gap.research_domain)
    for attribution in state.gate_failure_attributions.values():
        domain = attribution.research_domain
        if domain is not None and domain not in domains:
            domains.append(domain)
    delivered = _delivered_research_domains(state.trip_workspace_v2)
    return RunCoverageDisclosure(
        domains_without_results=sorted(
            (domain for domain in domains if domain not in delivered),
            key=lambda item: item.value,
        )
    )


def _delivered_research_domains(
    workspace: Optional[TripWorkspaceV2],
) -> frozenset[ResearchDomain]:
    """Which research domains actually put something on the delivered plan."""

    if workspace is None:
        return frozenset()
    itinerary = workspace.itinerary
    delivered: set[ResearchDomain] = set()
    if itinerary.visit_stops:
        delivered.add(ResearchDomain.VISIT)
    if itinerary.dining_stops:
        delivered.add(ResearchDomain.DINING)
    if itinerary.lodging_stays:
        delivered.add(ResearchDomain.LODGING)
    for leg in itinerary.transport_legs:
        if leg.transport_class == "long_distance":
            delivered.add(ResearchDomain.LONG_DISTANCE_TRANSPORT)
        else:
            delivered.add(ResearchDomain.LOCAL_TRANSPORT)
    return frozenset(delivered)
