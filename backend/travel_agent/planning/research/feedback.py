"""组合对研究 Worker 的返研请求合同与消息构造。"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Literal, Optional

from pydantic import Field

from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.schema import StrictModel


class ResearchRedoRequest(StrictModel):
    """组合请求某个研究 Worker 重做的自然语言反馈。"""

    worker_kind: Literal[
        "destination_researcher",
        "transport_researcher",
        "accommodation_researcher",
    ]
    feedback: str = Field(min_length=1)

# 每个 Worker 至多返研一次；达到上限后组合必须基于现有成果继续安排，
# 并在说明中写明无法安排的部分。
RESEARCH_REDO_ROUNDS_CAP = 1

# 反馈消息里错误成果摘要的规模上限，避免超长 packet 淹没任务上下文。
_PRIOR_PACKET_CHAR_LIMIT = 6000

_WORKER_BASES = ("destination_researcher", "transport_researcher", "accommodation_researcher")


def redo_assignment_key(worker_base: str, round_number: int) -> str:
    """返研轮的 assignment key：基础名加轮次后缀。"""
    return f"{worker_base}_r{round_number}"


def latest_worker_packet(
    state: Any,
    worker_base: str,
) -> tuple[str, ResearchPacket] | None:
    """返回该 Worker 在当前规划版本内最新轮次 packet 的存储键与 packet。

    research_packets 跨规划代际保留；非当前代际的同轮次 packet 不能作为
    当前返研的对照成果。
    """
    from travel_agent.planning.assignments import strip_round_suffix

    generation = getattr(getattr(state, "planning_generation", None), "generation_id", None)
    run_id = getattr(state, "run_id", "")
    fact_revision = getattr(state, "fact_data_revision", 0)
    best: tuple[int, str, ResearchPacket] | None = None
    for key, packet in (getattr(state, "research_packets", None) or {}).items():
        if (
            generation is not None
            and (packet.run_id != run_id or packet.generation_id != generation)
        ) or packet.fact_data_revision != fact_revision:
            continue
        task_key = key.split("@", 1)[0]
        if strip_round_suffix(task_key) != worker_base:
            continue
        suffix = re.search(r"_r(\d+)$", task_key)
        round_number = int(suffix.group(1)) if suffix else 1
        if best is None or round_number >= best[0]:
            best = (round_number, key, packet)
    if best is None:
        return None
    return best[1], best[2]


def parse_research_redo_request(raw: str) -> Optional[Dict[str, Any]]:
    """解析组合输出中的返研请求；结构与行程草稿二选一。

    返回 ``{"worker_kind", "feedback"}``；不是合法的返研请求时返回 ``None``。
    """
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("action") != "request_research_redo":
        return None
    worker = str(payload.get("worker_kind") or "")
    feedback = str(payload.get("feedback") or "").strip()
    if worker not in _WORKER_BASES or not feedback:
        return None
    return {"worker_kind": worker, "feedback": feedback}


def build_research_redo_request(
    *,
    worker_base: str,
    feedback: str,
    prior_packet_key: str,
    next_round: int,
) -> Dict[str, Any]:
    """构造写入 state 的返研请求载荷。"""
    return {
        "worker_base": worker_base,
        "feedback": feedback,
        "prior_packet_key": prior_packet_key,
        "round": next_round,
    }


def prior_packet_digest(prior_packet: ResearchPacket) -> str:
    """把需要重做的错误成果压成有边界的摘要，供返研提示词引用。

    候选保留标识与核心字段，事实保留字段名和取值；来源只保留标题。
    """
    candidates = []
    for candidate in prior_packet.candidates:
        candidates.append(
            {
                "candidate_id": candidate.candidate_id,
                "candidate_kind": candidate.candidate_kind,
                "name": getattr(candidate, "name", None),
                "destination_id": candidate.destination_id,
                "selection_reasons": candidate.selection_reasons,
                "tradeoff": candidate.tradeoff,
            }
        )
    facts = [
        {"candidate_id": fact.entity_ref.entity_id, "field_path": fact.field_path, "value": fact.asserted_value}
        for fact in prior_packet.fact_assertions
    ]
    digest = json.dumps(
        {"candidates": candidates, "facts": facts},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(digest) > _PRIOR_PACKET_CHAR_LIMIT:
        digest = digest[: _PRIOR_PACKET_CHAR_LIMIT - 1] + "…"
    return digest


def build_research_redo_messages(
    *,
    request: Dict[str, Any],
    prior_packet: Optional[ResearchPacket],
    task_desc: str,
    current_requirements: str,
) -> list[Dict[str, str]]:
    """返研轮追加给 Worker 的消息：问题、原因、需要重做什么与错误成果。"""
    sections = [
        "返研请求：上一轮研究成果无法支撑行程安排，需要重做。",
        f"组合反馈（问题、为什么无法安排、需要重做什么）：{request['feedback']}",
        f"原始任务（重做时仍适用）：{task_desc}",
        f"相关需求：{current_requirements}",
    ]
    if prior_packet is not None:
        sections.append(f"上一轮错误成果（整体被替代，只作对照，不要原样重交）：{prior_packet_digest(prior_packet)}")
        sections.append("结合反馈修正研究思路；其他角色的成果仍保留，不要复制它们。")
    return [{"role": "user", "content": "\n\n".join(sections)}]


def take_research_redo_request(
    research_redo_requests: Optional[Dict[str, Any]],
    worker_base: str,
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """取出该 Worker 的返研请求，并返回移除该键后的待处理集合。

    返回 ``(request, remaining)``；没有待处理请求时为 ``(None, None)``。
    """
    if not research_redo_requests:
        return None, None
    request = research_redo_requests.get(worker_base)
    if request is None:
        return None, None
    remaining = {
        key: value for key, value in research_redo_requests.items() if key != worker_base
    }
    return request, remaining or {}


def append_research_redo_messages(
    *,
    state: Any,
    messages: list[dict[str, Any]],
    worker_base: str,
    output_key: str,
    task_desc: str,
) -> Optional[Dict[str, Any]]:
    """返研轮给 Worker 追加反馈消息，并返回用于更新待处理集合的载荷。

    只有带轮次后缀的返研任务（``assignment_research_round > 0``）才消费请求；
    普通轮次保留请求给后续返研轮。返回 ``research_redo_requests`` 的更新值，
    无请求时返回 ``None``。
    """
    from travel_agent.planning.assignments import assignment_research_round

    request, remaining = take_research_redo_request(
        getattr(state, "research_redo_requests", None), worker_base
    )
    if request is None or assignment_research_round(output_key) == 0:
        return None
    prior_packet = (getattr(state, "research_packets", None) or {}).get(
        request["prior_packet_key"]
    )
    messages.extend(
        build_research_redo_messages(
            request=request,
            prior_packet=prior_packet,
            task_desc=task_desc,
            current_requirements=getattr(state, "current_requirements", ""),
        )
    )
    return remaining
