"""公开 Workspace 投影。"""

from __future__ import annotations

from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.delivery.evidence_basis import EvidenceBasisView
from travel_agent.planning.delivery.public.itinerary import _day
from travel_agent.planning.delivery.public.itinerary import _public_itinerary
from travel_agent.planning.delivery.travel_content import public_selection_text
from travel_agent.planning.itinerary.options import SelectionSlot
from travel_agent.planning.weather.models import WeatherProposalDecision
from travel_agent.planning.workspace import TripWorkspaceV2
from typing import Any
from typing import Dict
from typing import List


def _public_selection_slot(slot: SelectionSlot) -> Dict[str, Any]:
    return {
        "selection_slot_id": slot.selection_slot_id,
        "slot_type": slot.slot_type,
        "target_entity_id": slot.target_entity_id,
        "context": dict(slot.context),
        "options": [
            {
                "option_id": option.option_id,
                "rank": option.rank,
                "selected": option.option_id == slot.selected_option_id,
                "recommended": option.option_id == slot.recommended_option_id,
                "selection_reasons": [
                    public_selection_text(reason) for reason in option.selection_reasons
                ],
                "tradeoff": public_selection_text(option.tradeoff)
                if option.tradeoff
                else None,
                "comparison_facts": list(option.comparison_facts),
                "availability_status": option.availability_status,
            }
            for option in slot.options
        ],
        "status": slot.status,
    }


def _public_weather_proposal_decision(
    decision: WeatherProposalDecision,
) -> Dict[str, Any]:
    return {"proposal_id": decision.proposal_id, "decision": decision.decision}


def _public_weather_adjustments(bundle: DeliveryBundle) -> List[Dict[str, Any]]:
    """暴露待定的天气选择，但不暴露原始天气账本。

    天气刷新是用户主动发起的操作：客户端需要稳定的 proposal id 与可操作摘要来
    确认或忽略，但不应收到 provider 观测、原始操作或事实标识。
    """

    decisions = {
        item.proposal_id: item.decision
        for item in bundle.workspace.weather_proposal_decisions
    }
    return [
        {
            "proposal_id": proposal.proposal_id,
            "date": _day(proposal.date),
            "severity": proposal.severity,
            "summary": proposal.summary,
            "cost_delta_cny": proposal.cost_delta_cny,
            "time_delta_minutes": proposal.time_delta_minutes,
            "status": decisions.get(proposal.proposal_id, "pending"),
        }
        for proposal in bundle.weather_snapshot.adjustment_proposals
    ]


def _public_workspace(
    workspace: TripWorkspaceV2, bundle: DeliveryBundle, view: EvidenceBasisView
) -> Dict[str, Any]:
    """投影 Workspace。

    ``recommendation_catalog``、``user_input_anchors`` 与
    ``personalization_influences`` 不输出：catalog 是研究账本，anchor 已在报告
    备注中重述，influence 属于内部个性化记录。
    """

    return {
        "contract_version": workspace.contract_version,
        "run_id": workspace.run_id,
        "generation_id": workspace.generation_id,
        "workspace_revision": workspace.workspace_revision,
        "itinerary": _public_itinerary(workspace.itinerary, view),
        "selection_slots": [
            _public_selection_slot(slot) for slot in workspace.selection_slots
        ],
        "weather_proposal_decisions": [
            _public_weather_proposal_decision(item)
            for item in workspace.weather_proposal_decisions
        ],
        "weather_adjustments": _public_weather_adjustments(bundle),
    }
