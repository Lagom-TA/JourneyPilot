"""确认当前自然语言研究方案。"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from travel_agent.config.loader import get_settings
from travel_agent.planning.delivery.minimum_draft import seal_minimum_delivery_draft
from travel_agent.planning.invalidation import invalidation_update
from travel_agent.planning.nodes import NODE_DISPATCHER, NODE_INTENT_AMENDMENT_ROUTER, NODE_PLAN_GATE, NODE_RESEARCH_PLAN_GENERATOR
from travel_agent.planning.requirements.amendment_contracts import IntentAmendment
from travel_agent.planning.research.plan import RESEARCH_EXECUTION_PLAN
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.cancellation import RunCancelled


def _is_plan_gate_enabled(config: Optional[RunnableConfig]) -> bool:
    configurable = (config or {}).get("configurable", {})
    value = configurable.get("plan_gate_enabled")
    return bool(get_settings().run_control.plan_gate_enabled if value is None else value)


def _build_plan_gate_payload(state: TravelAgentState) -> Dict[str, Any]:
    plan = state.research_plan
    failed = plan is None or state.research_plan_error is not None
    # 门禁展示与批准后的实际执行使用同一份计划定义。
    groups = RESEARCH_EXECUTION_PLAN
    steps = [
        {"step": index, "agents": group, "tasks": {worker: plan.summary for worker in group}}
        for index, group in enumerate(groups, 1)
    ] if plan else []
    text = plan.summary if plan else "可以重试、补充要求或取消。"
    payload: Dict[str, Any] = {
        "gate": "plan",
        "revision": state.plan_gate_revision_count,
        "plan": {"steps": steps},
        "plan_text": text,
        "decision_options": ["retry", "supplement", "cancel"] if failed else ["approve", "supplement", "cancel"],
    }
    material = {
        "run_id": state.run_id,
        "generation_id": state.planning_generation.generation_id if state.planning_generation else "",
        "revision": state.plan_gate_revision_count,
        "plan": payload["plan"],
        "plan_text": text,
    }
    digest = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload["approval_token"] = f"plan_gate.approval:{digest}"
    return payload


async def plan_gate_node(state: TravelAgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    if not _is_plan_gate_enabled(config):
        raise RuntimeError("正式研究需要确认方案")
    payload = _build_plan_gate_payload(state)
    while True:
        decision = interrupt(payload)
        if not isinstance(decision, dict):
            continue
        action = str(decision.get("action") or "").lower()
        if action == "cancel":
            raise RunCancelled(state.run_id, NODE_PLAN_GATE)
        if action not in payload["decision_options"]:
            continue
        supplied = str(decision.get("approval_token") or "")
        try:
            valid = bool(supplied) and hmac.compare_digest(supplied.encode(), payload["approval_token"].encode())
        except UnicodeEncodeError:
            valid = False
        if not valid:
            continue
        if action == "retry":
            return {"plan_gate_decision": {"action": "retry"}, "research_plan_error": None}
        content = str(decision.get("content") or "").strip()[:2000]
        if action == "supplement":
            if not content:
                continue
            revision = state.plan_gate_revision_count + 1
            return {
                **invalidation_update(),
                "plan_gate_amendment": IntentAmendment(command_id=f"plan_gate_{state.run_id}_{revision}", category=action, content=content, source_kind="plan_gate_amendment"),
                "plan_gate_decision": {"action": "amendment", "revision": revision},
                "plan_gate_revision_count": revision,
                "understanding_messages": [],
                "understanding_pending_questions": None,
            }
        return {
            "plan_gate_decision": {"action": "approve", "revision": state.plan_gate_revision_count, "approval_token": supplied},
            # 批准时落章确认门展示的执行分组，保持授权与实际执行一致。
            "execution_plan": RESEARCH_EXECUTION_PLAN,
            "current_plan_step": 0,
            **seal_minimum_delivery_draft(state),
        }


def route_after_plan_gate(state: TravelAgentState) -> str:
    if state.pending_intent_amendments:
        return NODE_INTENT_AMENDMENT_ROUTER
    action = (state.plan_gate_decision or {}).get("action")
    if action == "amendment":
        return "understanding_agent"
    if action == "retry":
        return NODE_RESEARCH_PLAN_GENERATOR
    return NODE_DISPATCHER
