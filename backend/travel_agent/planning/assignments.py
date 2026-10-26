from __future__ import annotations

import re
from typing import Any, Dict, Tuple


def resolve_agent_assignment(
    agent_assignments: Dict[str, Any],
    base_name: str,
) -> Tuple[str, Dict[str, Any]]:
    """
    为 Worker 节点查找当前轮次的任务分配。

    精炼/补研轮次的 assignment key 带轮次后缀（如 destination_researcher_r2），
    而 Worker 节点以 base_name 注册；存在 `_rN` 形式的 key 时取编号最大者，
    否则退回 base_name。

    返回 (output_key, assignment_dict)：
    - output_key: 存储输出时使用的 key（base_name 或 base_name_rN）
    - assignment_dict: 完整的 capability assignment 契约
    """

    def require_assignment(key: str) -> Tuple[str, Dict[str, Any]]:
        assignment = agent_assignments.get(key)
        if (
            not isinstance(assignment, dict)
            or not str(assignment.get("objective") or "").strip()
        ):
            raise ValueError(f"missing capability assignment for {key}")
        return key, assignment

    matching_keys_with_round = []
    for key in agent_assignments:
        m = re.match(rf"^{re.escape(base_name)}_r(\d+)$", key)
        if m:
            matching_keys_with_round.append((int(m.group(1)), key))

    if matching_keys_with_round:
        matching_keys_with_round.sort(key=lambda x: x[0], reverse=True)
        latest_key = matching_keys_with_round[0][1]
        return require_assignment(latest_key)

    return require_assignment(base_name)


def assignment_research_round(assignment_key: str) -> int:
    match = re.fullmatch(r".+_r(\d+)", assignment_key)
    return max(int(match.group(1)) - 1, 0) if match else 0


def strip_round_suffix(agent_name: str) -> str:
    "去除 Agent 名称的轮次后缀，返回基础名称。"
    return re.sub(r"_r\d+$", "", agent_name)
