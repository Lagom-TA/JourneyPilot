"""Planning requirements amendments."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from travel_agent.planning.invalidation import invalidation_update
from travel_agent.planning.requirements.identity_amendments import (
    classify_locked_identity_intent,
)
from travel_agent.planning.requirements.request_contracts import (
    AmendmentImpact,
    IntentAmendment,
    IntentAmendmentRejection,
)
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.deadlines import observe_run_deadline


async def intent_amendment_router_node(state: TravelAgentState) -> Dict[str, Any]:
    # Run control schedules async nodes differently; keep the policy itself synchronous.
    return apply_runtime_amendments(state)


_PROJECTION_CUES = (
    "报告",
    "输出",
    "措辞",
    "格式",
    "排版",
    "摘要",
    "summary",
    "format",
)


_RESEARCH_CUES = (
    "景点",
    "餐厅",
    "咖啡",
    "酒店",
    "住宿",
    "交通",
    "预算",
    "不要",
    "排除",
    "必须",
    "provider",
    "avoid",
    "must",
)


_UNSUPPORTED_CUES = (
    "代订",
    "预订并付款",
    "直接付款",
    "帮我付款",
    "购买机票",
    "book and pay",
    "purchase for me",
)


_IMPACT_PRECEDENCE = {
    AmendmentImpact.PROJECTION_ONLY: 0,
    AmendmentImpact.COMPOSITION_AFFECTING: 1,
    AmendmentImpact.RESEARCH_AFFECTING: 2,
}


def classify_amendment(amendment: IntentAmendment) -> AmendmentImpact:
    if (
        classify_locked_identity_intent(amendment.content).classification
        == "change_requested"
    ):
        return AmendmentImpact.IDENTITY_CHANGE
    lowered = amendment.content.lower()
    if any(cue in lowered for cue in _UNSUPPORTED_CUES):
        return AmendmentImpact.UNSUPPORTED
    if any(cue in lowered for cue in _PROJECTION_CUES) and not any(
        cue in lowered for cue in _RESEARCH_CUES
    ):
        return AmendmentImpact.PROJECTION_ONLY
    if amendment.category == "pace":
        return AmendmentImpact.COMPOSITION_AFFECTING
    return AmendmentImpact.RESEARCH_AFFECTING


def apply_runtime_amendments(state: TravelAgentState) -> Dict[str, Any]:
    amendments = list(state.pending_intent_amendments)
    if not amendments:
        return {
            "intent_amendment_route": state.intent_amendment_resume_node,
            "intent_amendment_resume_node": None,
        }

    observed_deadline = state.run_deadline
    observation = None
    if observed_deadline is not None:
        observed_deadline, observation = observe_run_deadline(observed_deadline)

    accepted: list[IntentAmendment] = []
    rejected: list[IntentAmendmentRejection] = []
    for amendment in amendments:
        impact = amendment.impact or classify_amendment(amendment)
        rejection = _rejection_for_stage(
            amendment,
            impact,
            research_closed=bool(observation and observation.research_closed),
            composition_closed=bool(observation and observation.composition_closed),
            delivery_committed=bool(state.delivery_persisted or state.delivery_bundle),
        )
        if rejection is not None:
            rejected.append(rejection)
            continue
        accepted.append(amendment.model_copy(update={"impact": impact}))

    update: Dict[str, Any] = {
        "pending_intent_amendments": accepted,
        "rejected_intent_amendments": rejected,
        "run_deadline": observed_deadline,
    }
    if not accepted:
        update.update(
            {
                "intent_amendment_route": state.intent_amendment_resume_node,
                "intent_amendment_resume_node": None,
            }
        )
        return update

    impact = _strongest_impact(item.impact for item in accepted if item.impact)
    update.update(
        {
            "intent_amendment_route": "request_contract_normalizer",
            "intent_amendment_resume_node": None,
            "plan_gate_revision_count": state.plan_gate_revision_count + 1,
            "plan_gate_decision": {
                "action": "runtime_amendment",
                "revision": state.plan_gate_revision_count + 1,
            },
            "previous_selected_candidate_ids": _lineage_candidate_ids(state)
            or state.previous_selected_candidate_ids,
            **invalidation_update(impact),
        }
    )
    return update


def _lineage_candidate_ids(state: TravelAgentState) -> list[str]:
    """当前工作区行程实体引用过的候选 id，供下一轮调研去重。"""
    workspace = state.trip_workspace_v2
    if workspace is None:
        return []
    itinerary = workspace.itinerary
    return sorted(
        {
            entity.lineage.candidate_id
            for entity in (
                *itinerary.visit_stops,
                *itinerary.dining_stops,
                *itinerary.lodging_stays,
                *itinerary.transport_legs,
            )
            if entity.lineage.candidate_id
        }
    )


def _strongest_impact(impacts: Iterable[AmendmentImpact]) -> AmendmentImpact:
    return max(impacts, key=lambda item: _IMPACT_PRECEDENCE[item])


def _rejection_for_stage(
    amendment: IntentAmendment,
    impact: AmendmentImpact,
    *,
    research_closed: bool,
    composition_closed: bool,
    delivery_committed: bool,
) -> IntentAmendmentRejection | None:
    if impact is AmendmentImpact.IDENTITY_CHANGE:
        return IntentAmendmentRejection(
            command_id=amendment.command_id,
            impact=impact,
            reason_code="identity_change_requires_new_run",
            requires_new_run=True,
        )
    if impact is AmendmentImpact.UNSUPPORTED:
        return IntentAmendmentRejection(
            command_id=amendment.command_id,
            impact=impact,
            reason_code="unsupported_amendment",
        )
    if delivery_committed:
        return IntentAmendmentRejection(
            command_id=amendment.command_id,
            impact=impact,
            reason_code="delivery_already_committed",
        )
    if (
        impact is AmendmentImpact.RESEARCH_AFFECTING
        and research_closed
    ):
        return IntentAmendmentRejection(
            command_id=amendment.command_id,
            impact=impact,
            reason_code="research_window_closed",
            requires_new_run=True,
        )
    if (
        impact is AmendmentImpact.COMPOSITION_AFFECTING
        and composition_closed
    ):
        return IntentAmendmentRejection(
            command_id=amendment.command_id,
            impact=impact,
            reason_code="composition_window_closed",
            requires_new_run=True,
        )
    return None
