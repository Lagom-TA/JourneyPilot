"""理解代理：强模型按需联网、提问并形成旅行基础信息。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from travel_agent.llm.router import get_model_router
from travel_agent.llm.task_routing import TaskKind, llm_for_task
from travel_agent.llm.token_counting import estimate_request_tokens
from travel_agent.planning.nodes import NODE_UNDERSTANDING_AGENT
from travel_agent.planning.requirements.constraints.planning import build_planning_constraint_pack
from travel_agent.planning.requirements.identity_contracts import (
    ControlledTripIdentity,
)
from travel_agent.planning.requirements.understanding.contracts import (
    validate_understanding_questions,
)
from travel_agent.planning.requirements.understanding.places import bind_understanding_places
from travel_agent.planning.requirements.understanding.prompts import (
    initial_understanding_messages,
)
from travel_agent.planning.research.output.transcript import authoritative_tool_messages
from travel_agent.planning.tool_context import build_tool_context_from_state
from travel_agent.tools.access import filter_tools_for_agent, get_available_tools
from travel_agent.tools.react import streaming_react_loop
from travel_agent.tools.result import ReactOutcome
from travel_agent.utils.json_helpers import safe_parse_json

# 理解阶段的累计上限：提问轮数、每轮工具迭代数与上下文规模。取消由运行控制
# 与工具循环内的取消检查承担；每次模型与工具调用都记入运行台账，方案确认时
# 封存的研究预算会从台账读回已花量。
UNDERSTANDING_MAX_ROUNDS = 6
UNDERSTANDING_MAX_ITERATIONS = 4
UNDERSTANDING_ROUND_TIMEOUT_SECONDS = 300.0
UNDERSTANDING_PROMPT_MAX_ESTIMATED_TOKENS = 24000
_UNDERSTANDING_REPAIR_ATTEMPTS = 2


class UnderstandingFailed(RuntimeError):
    """理解阶段无法继续；应作为可见失败结束 Run，而不是静默降级。"""


def _append_final_answer(messages: List[Dict[str, Any]], content: str) -> None:
    """把本轮最终 JSON 答复保留进消息历史，下一轮模型能看到自己上次的结论。"""

    if messages and messages[-1].get("role") == "assistant" and messages[-1].get("content") == content:
        return
    messages.append({"role": "assistant", "content": content})


async def _persist_run_identity(config: Dict[str, Any], run_id: str, identity: ControlledTripIdentity) -> None:
    """把当前已知基础信息写回 Run 行，供刷新恢复读取。"""
    store = (config or {}).get("configurable", {}).get("trip_run_store")
    if store is not None:
        await store.update_controlled_trip_identity(
            run_id, controlled_trip_identity=identity.model_dump(mode="json")
        )


async def understanding_agent_node(state: Any, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    config = dict(config or {})
    stream_queue = (config.get("configurable") or {}).get("stream_queue")
    router = get_model_router()
    llm = llm_for_task(router, TaskKind.UNDERSTANDING, has_tools=True)
    available_tools = filter_tools_for_agent(
        await get_available_tools(),
        NODE_UNDERSTANDING_AGENT,
    )
    tool_context = build_tool_context_from_state(state)

    current_time = state.current_time or datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
    constraint_pack = state.constraint_pack or await build_planning_constraint_pack(state)
    context_state = state.model_copy(update={"constraint_pack": constraint_pack, "current_time": current_time})
    messages: List[Dict[str, Any]] = (
        list(state.understanding_messages) or initial_understanding_messages(context_state)
    )
    if state.understanding_messages and messages and messages[-1].get("role") == "user":
        messages = [
            *messages,
            {"role": "user", "content": f"本轮参考时间：{current_time}"},
        ]
    rounds = int(state.understanding_rounds or 0)
    repair = 0
    while True:
        estimated, _ = estimate_request_tokens({"messages": messages})
        if estimated > UNDERSTANDING_PROMPT_MAX_ESTIMATED_TOKENS:
            raise UnderstandingFailed("理解阶段的上下文过长，请精简要求后重新开始规划。")
        react = await asyncio.wait_for(
            streaming_react_loop(
                llm=llm,
                messages=messages,
                available_tools=available_tools,
                stream_queue=stream_queue,
                node_name=NODE_UNDERSTANDING_AGENT,
                max_iterations=UNDERSTANDING_MAX_ITERATIONS,
                tool_context=tool_context,
                final_round_notice=(
                    "工具调用轮数已用完，本轮必须直接输出完整的 JSON 结论"
                    "（ask 或 ready），不要再调用任何工具。"
                ),
                journal_key=f"understanding_react_{repair}",
            ),
            timeout=UNDERSTANDING_ROUND_TIMEOUT_SECONDS,
        )
        if react.outcome is not ReactOutcome.FINAL_ANSWER:
            raise UnderstandingFailed(f"需求理解没有产出结论: {react.outcome.value}")
        parsed = safe_parse_json(react.content, strip_think_tags=True)
        if not isinstance(parsed, dict):
            parsed = None
        action = str((parsed or {}).get("action") or "")
        try:
            if action not in {"ask", "ready"}:
                raise ValueError("action 必须是 ask 或 ready")
            raw_identity = parsed.get("trip_identity")
            requirements = parsed.get("requirements")
            if not isinstance(raw_identity, dict):
                raise ValueError("trip_identity 必须是对象")
            if not isinstance(requirements, str) or not requirements.strip():
                raise ValueError("requirements 必须是整理后的旅行要求")
            bound_identity = bind_understanding_places(
                raw_identity,
                state.controlled_trip_identity or {},
                [*messages, *authoritative_tool_messages(react.tool_results)],
            )
            identity = ControlledTripIdentity.model_validate(bound_identity)
            questions = validate_understanding_questions(parsed.get("questions")) if action == "ask" else None
        except (ValidationError, ValueError) as exc:
            if repair >= _UNDERSTANDING_REPAIR_ATTEMPTS:
                raise UnderstandingFailed(f"需求理解没有返回有效结果: {exc}") from exc
            repair += 1
            _append_final_answer(messages, react.content)
            messages.append({"role": "user", "content": f"请修正本轮输出格式：{exc}"})
            continue

        pending = [item.model_dump(mode="json") for item in questions] if questions else []
        missing_dates = identity.start_date is None or identity.end_date is None
        if action == "ready" and missing_dates:
            pending = [{
                "id": "travel_dates",
                "question": "旅行时间尚未明确，准备玩几天？也可以选择具体的出发和返程日期。",
                "kind": "date_range",
                "options": [],
            }]
        needs_retry = action == "ready" and not missing_dates and not identity.destinations
        if action == "ask" and rounds >= UNDERSTANDING_MAX_ROUNDS:
            raise UnderstandingFailed("已达到理解阶段的提问上限，请整理要求后重新开始规划。")
        _append_final_answer(messages, react.content)
        await _persist_run_identity(config, state.run_id, identity)
        update = {
            "understanding_messages": messages,
            "understanding_qa": list(state.understanding_qa or []),
            "understanding_pending_questions": pending if pending or needs_retry else None,
            "controlled_trip_identity": identity.model_dump(mode="json"),
            "current_requirements": requirements.strip(),
            "constraint_pack": constraint_pack,
        }
        if pending or needs_retry:
            update["understanding_rounds"] = rounds + 1
        return update
