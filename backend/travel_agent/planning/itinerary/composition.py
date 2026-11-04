from __future__ import annotations

import json
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
from travel_agent.tools.react import streaming_react_loop
from travel_agent.tools.result import ReactOutcome

# 组合补查的工具调用轮数上限；与 Worker 的迭代上限同一量级。
_COMPOSITION_TOOL_ITERATIONS = 5

_COMPOSITION_FINAL_ROUND_NOTICE = (
    "工具调用轮数已用完，本轮必须直接输出完整的行程草稿 JSON 对象"
    "或返研请求 JSON 对象，不要再调用任何工具。"
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

    async def transport_followup(arguments: Any, call_id: str) -> dict[str, Any]:
        nonlocal current_catalog
        if not isinstance(arguments, dict):
            arguments = {}
        response, current_catalog = await research_transport_followup(
            state.model_copy(update={"recommendation_catalog": current_catalog}),
            question=str(arguments.get("question") or ""),
            arrangement=arguments.get("current_arrangement") or "",
            destination_id=str(arguments.get("destination_id") or ""),
            stream_queue=stream_queue,
            request_id=call_id,
        )
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
        )
        for tool_result in react.tool_results:
            if tool_result.get("tool_name") == FOLLOWUP_TOOL_NAME:
                current_catalog = _restore_catalog(current_catalog, tool_result)
        if catalog_updates is not None:
            catalog_updates.append(current_catalog)
        if react.outcome is not ReactOutcome.FINAL_ANSWER:
            detail = f": {react.error}" if react.error else ""
            raise ValueError(
                f"composition tool loop ended without a final answer: "
                f"{react.outcome.value}{detail}"
            )
        content = react.content
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        redo = parse_research_redo_request(content)
        if redo is not None:
            request = ResearchRedoRequest.model_validate(redo)
            return request
        try:
            draft = _reuse_located_places(
                _parse_exact_llm_composition(content), previous
            )
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
            continue
        return draft
    raise AssertionError("composition attempt budget exhausted")
