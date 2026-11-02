"""需求修订处理。"""

from __future__ import annotations

from typing import Any, Dict

from travel_agent.planning.invalidation import invalidation_update
from travel_agent.planning.nodes import (
    AMENDMENT_CONTINUATION_NODES,
    NODE_UNDERSTANDING_AGENT,
)
from travel_agent.planning.requirements.amendment_contracts import (
    AmendmentImpact,
    IntentAmendment,
    IntentAmendmentRejection,
)
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.deadlines import observe_run_deadline


def _resumable_route(route: str | None) -> str | None:
    """续跑目标必须在图的续跑表内；越界说明状态里带了图不认识的目标。"""

    if route is None:
        return None
    if route not in AMENDMENT_CONTINUATION_NODES:
        raise ValueError("amendment route outside continuation table")
    return route


async def intent_amendment_router_node(state: TravelAgentState) -> Dict[str, Any]:
    # Run control 对异步节点的调度方式不同；判断逻辑本身保持同步。
    return apply_runtime_amendments(state)


_UNSUPPORTED_CUES = (
    "代订",
    "预订并付款",
    "直接付款",
    "帮我付款",
    "购买机票",
    "book and pay",
    "purchase for me",
)


def classify_amendment(amendment: IntentAmendment) -> AmendmentImpact:
    lowered = amendment.content.lower()
    if any(cue in lowered for cue in _UNSUPPORTED_CUES):
        return AmendmentImpact.UNSUPPORTED
    return AmendmentImpact.RESEARCH_AFFECTING


def apply_runtime_amendments(state: TravelAgentState) -> Dict[str, Any]:
    amendments = list(state.pending_intent_amendments)
    if not amendments:
        return {
            "intent_amendment_route": _resumable_route(
                state.intent_amendment_resume_node
            ),
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
            delivery_committed=bool(state.delivery_persisted or state.delivery_bundle),
        )
        if rejection is not None:
            rejected.append(rejection)
            continue
        accepted.append(amendment.model_copy(update={"impact": impact}))

    update: Dict[str, Any] = {
        "pending_intent_amendments": accepted,
        "rejected_intent_amendments": rejected,
    }
    if observed_deadline is not None:
        update["run_deadline"] = observed_deadline
    if not accepted:
        update.update(
            {
                "intent_amendment_route": _resumable_route(
                    state.intent_amendment_resume_node
                ),
                "intent_amendment_resume_node": None,
            }
        )
        return update

    update.update(
        {
            "intent_amendment_route": NODE_UNDERSTANDING_AGENT,
            "intent_amendment_resume_node": None,
            "understanding_messages": [],
            "understanding_pending_questions": None,
            "plan_gate_revision_count": state.plan_gate_revision_count + 1,
            "plan_gate_decision": {
                "action": "runtime_amendment",
                "revision": state.plan_gate_revision_count + 1,
            },
            **invalidation_update(),
        }
    )
    return update


def _rejection_for_stage(
    amendment: IntentAmendment,
    impact: AmendmentImpact,
    *,
    research_closed: bool,
    delivery_committed: bool,
) -> IntentAmendmentRejection | None:
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
    return None
