"""研究未完成时保留已有成果并等待用户决定。"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from datetime import datetime
from typing import Any, Dict

from langgraph.types import interrupt

from travel_agent.planning.assignments import resolve_agent_assignment
from travel_agent.planning.nodes import NODE_RESEARCH_GATE, RESEARCH_WORKER_NODES
from travel_agent.planning.presentation import get_agent_display_name
from travel_agent.planning.research.plan import build_worker_assignment
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.runtime.deadlines import shift_run_deadline, utc_now


def research_gate_payload(state: TravelAgentState) -> Dict[str, Any]:
    failed = sorted(set(state.research_failed_workers))
    completed = []
    for worker in sorted(RESEARCH_WORKER_NODES):
        if worker in failed:
            continue
        try:
            key, _ = resolve_agent_assignment(state.agent_assignments, worker)
        except ValueError:
            continue
        if state.agent_status.get(key) == "completed":
            completed.append(worker)
    failed_labels = "、".join(get_agent_display_name(worker) for worker in failed)
    completed_labels = "、".join(get_agent_display_name(worker) for worker in completed)
    message = f"{failed_labels}未完成，已保留其他研究成果。"
    if completed_labels:
        message = f"{failed_labels}未完成；{completed_labels}的成果已保留。"
    message += "重试沿用本次规划的时限设置，可用研究时间可能少于首次；调整时限后需取消并重新规划。"
    material = {
        "run_id": state.run_id,
        "generation": state.planning_generation.generation_id if state.planning_generation else "",
        "revision": state.research_retry_count,
        "failed": failed,
        "started_at": state.research_gate_started_at,
    }
    digest = hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return {
        "gate": "research",
        "revision": state.research_retry_count,
        "approval_token": f"research_gate.v1:{digest}",
        "failed_workers": failed,
        "completed_workers": completed,
        "message": message,
        "decision_options": ["retry", "cancel"],
    }


def _renew_deadline(state: TravelAgentState) -> Any:
    deadline = state.run_deadline
    if deadline is None or not state.research_gate_started_at:
        raise ValueError("研究重试需要运行期限")
    now = utc_now()
    started = datetime.fromisoformat(state.research_gate_started_at)
    waiting = max(0.0, (now - started).total_seconds())
    elapsed = deadline.checkpointed_elapsed_seconds
    extension = math.ceil(waiting + max(0.0, elapsed - deadline.target_seconds))
    return shift_run_deadline(deadline, int(extension), now=now)


async def research_gate_node(state: TravelAgentState) -> Dict[str, Any]:
    payload = research_gate_payload(state)
    while True:
        decision = interrupt(payload)
        if not isinstance(decision, dict):
            continue
        action = str(decision.get("action") or "")
        if action == "cancel":
            raise RunCancelled(state.run_id, NODE_RESEARCH_GATE)
        supplied = str(decision.get("approval_token") or "")
        try:
            valid = hmac.compare_digest(supplied.encode(), payload["approval_token"].encode())
        except UnicodeEncodeError:
            valid = False
        if action != "retry" or not valid:
            continue
        assignments = dict(state.agent_assignments)
        statuses: Dict[str, str] = {}
        for worker in state.research_failed_workers:
            key, previous = resolve_agent_assignment(assignments, worker)
            assignments[key] = {
                **previous,
                **build_worker_assignment(state, worker, str(previous["objective"])),
            }
            statuses[key] = "pending"
        return {
            "agent_assignments": assignments,
            "agent_status": statuses,
            "research_retry_workers": list(state.research_failed_workers),
            "research_failed_workers": [],
            "research_gate_started_at": None,
            "research_retry_count": state.research_retry_count + 1,
            "run_deadline": _renew_deadline(state),
            "next_agent": "dispatch_group",
        }
