from __future__ import annotations

from typing import Any

from ...tools.display import result_preview


def worker_result(
    node: str, update: dict[str, Any]
) -> tuple[str, str, list[dict[str, str]]]:
    """Project typed worker results, without trusting the worker's message text."""
    statuses = update.get("agent_status", {})
    if isinstance(statuses, dict) and "failed" in statuses.values():
        return "failed", "本轮调研未完成，暂未形成可用结果", []
    packets = update.get("research_packets", {})
    candidates: list[Any] = []
    if isinstance(packets, dict):
        for packet in packets.values():
            if hasattr(packet, "model_dump"):
                packet = packet.model_dump(mode="json")
            if not isinstance(packet, dict) or packet.get("worker_kind") != node:
                continue
            rows = packet.get("candidates")
            if isinstance(rows, list):
                candidates.extend(rows)
    if isinstance(packets, dict) and packets:
        noun = {
            "destination_researcher": "地点",
            "accommodation_researcher": "住宿",
            "transport_researcher": "交通",
        }.get(node, "调研")
        content = (
            f"已整理 {len(candidates)} 个{noun}候选"
            if candidates
            else f"本轮暂未找到可用的{noun}候选"
        )
        return "completed", content, result_preview(candidates)
    return "completed", "本轮资料整理已结束", []
