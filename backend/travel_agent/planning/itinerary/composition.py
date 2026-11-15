from __future__ import annotations

import json
import logging
import time
from typing import Any, Union

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.itinerary.draft import ItineraryCompositionDraft
from travel_agent.planning.itinerary.locations import _reuse_located_places
from travel_agent.planning.itinerary.parsing import _parse_exact_llm_composition
from travel_agent.planning.itinerary.prompts import _build_composition_prompt
from travel_agent.planning.nodes import NODE_ITINERARY
from travel_agent.planning.research.feedback import (
    ResearchRedoRequest,
    parse_research_redo_request,
)
from travel_agent.planning.research.transport.followup import (
    FOLLOWUP_TOOL,
    FOLLOWUP_TOOL_NAME,
    _restore_catalog,
    research_transport_followup,
)
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.runtime.operations import ModelWindowClosed, remaining_model_seconds
from travel_agent.tools.governance import build_tool_execution_envelope
from travel_agent.tools.react import streaming_react_loop
from travel_agent.tools.result import ReactOutcome

logger = logging.getLogger(__name__)


class CompositionTimeExhausted(ValueError):
    """组合在运行时限内未能产生完整草稿。"""


# 组合补查的工具调用轮数上限；与 Worker 的迭代上限同一量级。
_COMPOSITION_TOOL_ITERATIONS = 5
# 为最终草稿保留模型时间；最后一小段留给地点、路线物化与交付。
_FINAL_ANSWER_RESERVE_SECONDS = 180.0
_MATERIALIZATION_RESERVE_SECONDS = 20.0
_TRANSPORT_FOLLOWUP_LIMIT_SECONDS = 45.0

_COMPOSITION_FINAL_ROUND_NOTICE = (
    "补查时间已用完。请直接基于已经取得的资料输出完整的行程草稿 JSON 对象；"
    "不要再调用工具或请求返研。无法安全安排的事项写入 day_design.unresolved，"
    "不要编造交通路线、时间或来源。"
)


def _remaining_composition_seconds(operation: str) -> float:
    """组合窗口已关闭时返回零，取消请求仍由运行时向上传播。"""
    try:
        remaining = remaining_model_seconds(operation)
    except ModelWindowClosed:
        return 0.0
    return float("inf") if remaining is None else remaining


def _remaining_materialization_seconds() -> float:
    """可用于地点与交通补查的时间，留出本地物化余量。"""
    return max(
        0.0,
        _remaining_composition_seconds("itinerary.materialization")
        - _MATERIALIZATION_RESERVE_SECONDS,
    )


def _can_reschedule() -> bool:
    """完整重排只在留有成稿与物化时间时启动。"""
    return _remaining_composition_seconds("itinerary.reschedule") > (
        _FINAL_ANSWER_RESERVE_SECONDS + _MATERIALIZATION_RESERVE_SECONDS
    )


def _remaining_exploration_seconds() -> float:
    """给当前封存期限留出最终成稿和物化的时间。"""
    remaining = remaining_model_seconds("itinerary.composition.exploration")
    if remaining is None:
        return float("inf")
    return max(
        0.0,
        remaining - _FINAL_ANSWER_RESERVE_SECONDS - _MATERIALIZATION_RESERVE_SECONDS,
    )


async def _compose_draft(
    state: TravelAgentState,
    task_desc: str,
    llm: Any,
    *,
    available_tools: list[dict[str, Any]],
    tool_context: dict[str, Any],
    stream_queue: Any = None,
    tool_cache: dict[str, Any] | None = None,
    catalog_updates: list[RecommendationCatalog] | None = None,
) -> Union[ItineraryCompositionDraft, ResearchRedoRequest]:
    """生成行程草稿；模型也可请求让某个研究 Worker 返研。

    组合先经历带工具的反应式循环，可自主补查地点、衔接等局部信息；
    JSON 解析或结构校验失败时带上错误重试一次。
    """
    prompt = _build_composition_prompt(
        state,
        task_desc,
        skeleton_only=True,
        strict_wire_schema=False,
        dynamic_transport=True,
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt.system},
        {"role": "user", "content": prompt.runtime},
    ]
    if state.composition_failure_context and state.composition_failure_context.startswith("交通研究员补查结果："):
        messages.extend([
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "prior_transport_followup", "name": FOLLOWUP_TOOL_NAME,
                "arguments": {"question": "核对上一轮相邻接驳"},
            }]},
            {"role": "tool", "tool_call_id": "prior_transport_followup", "content": state.composition_failure_context},
        ])
    previous = state.placement_skeleton
    current_catalog = state.recommendation_catalog
    followup_remaining = _TRANSPORT_FOLLOWUP_LIMIT_SECONDS
    closing_answer_required = False

    async def transport_followup(arguments: Any, call_id: str) -> dict[str, Any]:
        nonlocal current_catalog, followup_remaining
        if not isinstance(arguments, dict):
            arguments = {}
        available = min(followup_remaining, _remaining_exploration_seconds())
        if available <= 0:
            return build_tool_execution_envelope(
                tool_name=FOLLOWUP_TOOL_NAME,
                arguments=arguments,
                status="failed",
                error="交通补查时间已用完，相关路线仍待确认。",
                source="local",
                category="internal",
            )
        started = time.monotonic()
        response, current_catalog = await research_transport_followup(
            state.model_copy(update={"recommendation_catalog": current_catalog}),
            question=str(arguments.get("question") or ""),
            arrangement=arguments.get("current_arrangement") or "",
            destination_id=str(arguments.get("destination_id") or ""),
            from_destination_id=str(arguments.get("from_destination_id") or ""),
            to_destination_id=str(arguments.get("to_destination_id") or ""),
            service_date=str(arguments.get("service_date") or ""),
            stream_queue=stream_queue,
            request_id=call_id,
            max_duration_seconds=available,
        )
        followup_remaining = max(0.0, followup_remaining - (time.monotonic() - started))
        if catalog_updates is not None:
            catalog_updates.append(current_catalog)
        return response

    for attempt in range(2):
        react = await streaming_react_loop(
            llm=llm,
            messages=messages,
            available_tools=[*available_tools, FOLLOWUP_TOOL],
            stream_queue=stream_queue,
            node_name=NODE_ITINERARY,
            max_iterations=_COMPOSITION_TOOL_ITERATIONS,
            tool_cache=tool_cache,
            tool_context=tool_context,
            final_round_notice=_COMPOSITION_FINAL_ROUND_NOTICE,
            journal_key=f"composition_react_{attempt}",
            local_tool_handlers={FOLLOWUP_TOOL_NAME: transport_followup},
            exploration_remaining=(
                (lambda: float("inf")) if closing_answer_required else _remaining_exploration_seconds
            ),
        )
        for tool_result in react.tool_results:
            if tool_result.get("tool_name") == FOLLOWUP_TOOL_NAME:
                current_catalog = _restore_catalog(current_catalog, tool_result)
        if catalog_updates is not None:
            catalog_updates.append(current_catalog)
        if react.outcome is not ReactOutcome.FINAL_ANSWER:
            detail = f": {react.error}" if react.error else ""
            error = (
                f"composition tool loop ended without a final answer: "
                f"{react.outcome.value}{detail}"
            )
            if react.outcome is ReactOutcome.BUDGET_LIMIT:
                raise CompositionTimeExhausted(error)
            raise ValueError(error)
        content = react.content
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        redo = parse_research_redo_request(content)
        if redo is not None:
            if _remaining_exploration_seconds() > 0:
                return ResearchRedoRequest.model_validate(redo)
            if attempt:
                raise ValueError("composition requested research after the final-answer reserve")
            logger.info("行程组合不再启动返研，保留时间生成可交付草稿")
            messages.extend([
                {"role": "assistant", "content": content},
                {"role": "user", "content": _COMPOSITION_FINAL_ROUND_NOTICE},
            ])
            closing_answer_required = True
            continue
        try:
            draft = _reuse_located_places(
                _parse_exact_llm_composition(content), previous
            )
            expected_dates = [day.date for day in state.minimum_delivery_draft.day_shells]
            if [day.date for day in draft.days] != expected_dates:
                raise ValueError("行程日期必须与已确认的旅行日期逐日一致")
        except ValueError as exc:
            if attempt:
                raise
            messages.extend(
                [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            "上一次输出无法解析为行程草稿结构。请修正下面的问题并重新输出完整 JSON 对象，"
                            "其余内容保持不变。"
                            f"问题：{exc}"
                        ),
                    },
                ]
            )
            closing_answer_required = _remaining_exploration_seconds() <= 0
            continue
        return draft
    raise AssertionError("composition attempt budget exhausted")
