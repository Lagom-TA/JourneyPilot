from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from ..runtime.budget import RunBudgetExhausted
from ..runtime.cancellation import check_cancel_requested
from ..runtime.events import run_ts_ms
from ..runtime.operations import ModelWindowClosed, remaining_model_seconds
from .builtin_tools import SEARCH_TOOLS_NAME
from .content import compact_tool_content_for_model
from .display import (
    TOOL_CATEGORIES,
    _summarize_args,
    _summarize_tool_result,
    result_preview,
)
from .execution import execute_tool
from .exposure import ToolExposureSession, apply_tool_exposure, attach_tool_catalog
from .exposure_ledger import get_tool_exposure_ledger
from .governance import (
    CAPABILITY_DECLARATION_STATUSES,
    ToolExecutionStatus,
    is_tool_execution_envelope,
)
from .registry import get_tool_registry
from .result import ReactOutcome, ReactResult

if TYPE_CHECKING:
    from ..runtime.events import EventBuffer

logger = logging.getLogger(__name__)


_SUCCEEDED_TOOL_STATUSES = frozenset(
    {
        ToolExecutionStatus.SUCCESS.value,
        ToolExecutionStatus.DEGRADED.value,
    }
)


def _normalize_tool_arguments(arguments: Dict[str, Any]) -> str:
    """返回参数用于幂等工具重放键的稳定 JSON 表示。"""
    return json.dumps(
        arguments or {},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def _make_cache_key(tool_name: str, arguments: Dict[str, Any]) -> str:
    """生成工具调用缓存键：工具名 + 规范化参数 hash。"""
    normalized_args = _normalize_tool_arguments(arguments)
    digest = hashlib.sha256(normalized_args.encode("utf-8")).hexdigest()[:24]
    return f"{tool_name}:{digest}"


_NO_CACHE_TOOLS: Set[str] = {
    "knowledge_search",
    "ask_user",
    "global_place_search",
    "global_route_search",
    "maps_text_search",
    "maps_search_detail",
}


def _cacheable_tool_result(tool_name: str, result: Dict[str, Any]) -> bool:
    if tool_name in _NO_CACHE_TOOLS or not isinstance(result, dict):
        return False
    if result.get("status") not in {"success", "degraded"}:
        return False
    metadata = result.get("metadata") or {}
    if metadata.get("side_effecting"):
        return False
    sanitized_result = (
        result.get("sanitized_result") if is_tool_execution_envelope(result) else result
    )
    return not (
        isinstance(sanitized_result, dict)
        and sanitized_result.get("type") == "user_input_required"
    )


async def streaming_react_loop(
    llm: Any,
    messages: List[Dict[str, Any]],
    available_tools: List[Dict[str, Any]],
    stream_queue: Optional["EventBuffer"],
    node_name: str,
    max_iterations: int = 5,
    can_ask_user: bool = False,
    tool_cache: Optional[Dict[str, Any]] = None,
    tool_context: Optional[Dict[str, Any]] = None,
) -> ReactResult:
    "通用流式 ReAct 循环。"
    if stream_queue is not None:
        await stream_queue.put(("agent_activity", node_name, None))
    tool_results_summary: List[str] = []
    authoritative_tool_results: List[Dict[str, Any]] = []
    last_text_content = ""
    tool_context = tool_context or {}

    # 只有本次调用可以复用 envelope；跨轮重放需要 journal 校验。
    invocation_cache: Dict[str, Any] = {}
    allowed_names = {item["schema"]["function"]["name"] for item in available_tools}

    exposure_plan = apply_tool_exposure(available_tools, node_name)
    exposure = ToolExposureSession(available_tools, exposure_plan)

    messages[:] = attach_tool_catalog(messages, exposure_plan)
    get_tool_exposure_ledger().record(
        tool_context.get("run_id"),
        deferred=exposure_plan.deferred,
        injected_tokens=exposure_plan.injected_tokens,
        full_tokens=exposure_plan.full_tokens,
        exposed_tool_count=exposure_plan.exposed_tool_count,
        full_tool_count=exposure_plan.full_tool_count,
    )

    effective_max_iterations = max_iterations + (1 if exposure_plan.deferred else 0)

    from copy import deepcopy

    from travel_agent.runtime.journal import current_worker_journal

    journal = current_worker_journal.get()
    saved = journal.payload.get("react", {}) if journal else {}
    if saved:
        if any(
            item.get("tool_name") == "knowledge_search"
            for item in saved.get("results", [])
        ):
            from ..config.loader import get_settings
            from ..tools.gateway import _manifest_from_metadata

            manifest = _manifest_from_metadata(
                "knowledge_search",
                get_tool_registry().get_tool_metadata("knowledge_search"),
            )
            if (
                not get_settings().embedding.enabled
                or "knowledge_search" not in allowed_names
                or manifest.disabled
            ):
                raise RuntimeError("knowledge_search recovery is not authorized")
        messages[:] = deepcopy(saved["messages"])
        tool_results_summary[:] = saved["summaries"]
        authoritative_tool_results[:] = deepcopy(saved["results"])
        last_text_content = saved["last_text"]
        exposure.restore(saved["activated"])
        journal.tool_cursor = saved["tool_cursor"]
        if saved.get("done"):
            return ReactResult(
                outcome=ReactOutcome(saved["outcome"]),
                content=saved["content"],
                summaries=tool_results_summary,
                pending_choice=saved.get("pending_choice"),
                tool_results=authoritative_tool_results,
                error=saved.get("error"),
            )

    round_counts = {"fail": 0, "success": 0, "capabilities": []}

    async def save_round(iteration, **phase):
        if journal:
            journal.payload["react"] = {
                "iteration": iteration,
                "messages": deepcopy(messages),
                "summaries": list(tool_results_summary),
                "results": deepcopy(authoritative_tool_results),
                "last_text": last_text_content,
                "activated": exposure.activated_names,
                "tool_cursor": journal.tool_cursor,
                "round_counts": deepcopy(round_counts),
                **phase,
            }
            await journal.commit()

    async def terminate(
        iteration, outcome, *, content="", pending_choice=None, error=None
    ):
        await save_round(
            iteration,
            done=True,
            outcome=outcome.value,
            content=content,
            pending_choice=pending_choice,
            error=error,
        )
        return ReactResult(
            outcome=outcome,
            content=content,
            summaries=tool_results_summary,
            pending_choice=pending_choice,
            tool_results=authoritative_tool_results,
            error=error,
        )

    start_iteration = saved.get("iteration", 0)
    content = last_text_content
    for iteration in range(start_iteration, effective_max_iterations):
        check_cancel_requested(node_name)
        try:
            remaining_model_seconds(f"react.{node_name}.iteration_{iteration + 1}")
        except (ModelWindowClosed, RunBudgetExhausted) as exc:
            logger.info("[%s] research window closed: %s", node_name, exc)
            if iteration == start_iteration and saved.get("response"):
                for skipped in saved["response"][1][saved.get("next_tool", 0) :]:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": skipped["id"],
                            "content": '{"status":"not_executed","reason":"research_window_closed"}',
                        }
                    )
            return await terminate(iteration, ReactOutcome.BUDGET_LIMIT, error=str(exc))
        content = ""
        tool_calls: List[Dict[str, Any]] = []
        assistant_replay: Dict[str, Any] = {}

        recovered_response = (
            saved.get("response") if iteration == start_iteration else None
        )
        if recovered_response:
            content, tool_calls, assistant_replay = recovered_response
        else:
            await save_round(iteration, phase="request_started")
            finished = False
            try:
                async for event in llm.astream_with_tools(
                    messages, exposure.tool_schemas
                ):
                    if event["type"] == "text_delta":
                        content += event["content"]
                    elif event["type"] == "reasoning_delta":
                        pass
                    elif event["type"] == "finish":
                        finished = True
                        finish_content = event.get("content")
                        if finish_content is not None:
                            content = finish_content
                        tool_calls = event.get("tool_calls", [])
                        assistant_replay = event.get("assistant_replay") or {}
            except (ModelWindowClosed, RunBudgetExhausted) as exc:
                return await terminate(
                    iteration, ReactOutcome.BUDGET_LIMIT, error=str(exc)
                )
            except Exception as e:
                logger.error(f"[{node_name}] 流式 LLM 调用失败 (迭代 {iteration}): {e}")
                return await terminate(
                    iteration,
                    ReactOutcome.MODEL_FAILED,
                    error=f"{node_name} iteration {iteration + 1}: {type(e).__name__}: {e}",
                )

            if not finished:
                return await terminate(
                    iteration,
                    ReactOutcome.INCOMPLETE_STREAM,
                    error=f"{node_name} iteration {iteration + 1}: stream ended without finish",
                )

            for tc in tool_calls:
                tc["id"] = tc.get("id") or f"tool_{uuid.uuid4().hex}"

        if content.strip():
            last_text_content = content

        if not tool_calls:
            if not content.strip():
                return await terminate(
                    iteration,
                    ReactOutcome.INCOMPLETE_STREAM,
                    error=f"{node_name} iteration {iteration + 1}: empty final answer",
                )
            return await terminate(
                iteration, ReactOutcome.FINAL_ANSWER, content=content
            )

        round_counts = (
            deepcopy(saved.get("round_counts", round_counts))
            if recovered_response
            else {"fail": 0, "success": 0, "capabilities": []}
        )
        if not recovered_response:
            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                    "assistant_replay": assistant_replay,
                }
            )

            await save_round(
                iteration, response=[content, tool_calls, assistant_replay], next_tool=0
            )

        pending_choice: Optional[Dict[str, Any]] = None
        fail_count = round_counts["fail"]
        success_count = round_counts["success"]
        total_count = len(tool_calls)

        capability_tool_names: List[str] = list(round_counts["capabilities"])

        for tool_index, tc in enumerate(tool_calls):
            if recovered_response and tool_index < saved.get("next_tool", 0):
                continue
            tc_name = tc.get("name", "")
            tc_args = tc.get("arguments", {})
            tc_id = tc.get("id", "") or f"tool_{uuid.uuid4().hex}"

            try:
                remaining_model_seconds(f"react.{node_name}.tool.{tc_name}")
            except (ModelWindowClosed, RunBudgetExhausted) as exc:
                logger.info(
                    "[%s] suppressing tool after research cutoff: %s", node_name, exc
                )
                for skipped in tool_calls[tool_index:]:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": skipped["id"],
                            "content": '{"status":"not_executed","reason":"research_window_closed"}',
                        }
                    )
                return await terminate(
                    iteration, ReactOutcome.BUDGET_LIMIT, error=str(exc)
                )

            if tc_name == SEARCH_TOOLS_NAME:
                query = tc_args.get("query", "") if isinstance(tc_args, dict) else ""
                search_started = time.perf_counter()
                if stream_queue is not None:
                    await stream_queue.put(
                        (
                            "tool_start",
                            node_name,
                            {
                                "name": tc_name,
                                "tool_call_id": tc_id,
                                "args_summary": _summarize_args(tc_args),
                                "category": "internal",
                                "ts_ms": run_ts_ms(),
                            },
                        )
                    )
                search_result = exposure.activate(query)
                newly = search_result["activated"]
                logger.info(
                    "[%s] search_tools(query=%r) 激活: %s", node_name, query, newly
                )
                if stream_queue is not None:
                    await stream_queue.put(
                        (
                            "tool_done",
                            node_name,
                            {
                                "name": tc_name,
                                "tool_call_id": tc_id,
                                "summary": f"激活工具：{', '.join(newly)}"
                                if newly
                                else "未匹配到工具",
                                "status": ToolExecutionStatus.SUCCESS.value,
                                "category": "internal",
                                "duration_ms": round(
                                    (time.perf_counter() - search_started) * 1000.0, 3
                                ),
                                "ts_ms": run_ts_ms(),
                            },
                        )
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps(search_result, ensure_ascii=False),
                    }
                )
                await save_round(
                    iteration,
                    response=[content, tool_calls, assistant_replay],
                    next_tool=tool_index + 1,
                )
                check_cancel_requested(node_name)
                continue

            cache_key = _make_cache_key(tc_name, tc_args)
            cache_hit = (
                tc_name in allowed_names
                and tc_name not in _NO_CACHE_TOOLS
                and cache_key in invocation_cache
            )

            category = TOOL_CATEGORIES.get(tc_name, "other")

            tool_started = time.perf_counter()
            if cache_hit:
                tool_result = invocation_cache[cache_key]
                logger.info(f"[{node_name}] 缓存命中: {tc_name}")
                if stream_queue is not None:
                    await stream_queue.put(
                        (
                            "tool_start",
                            node_name,
                            {
                                "name": tc_name,
                                "tool_call_id": tc_id,
                                "args_summary": _summarize_args(tc_args),
                                "category": category,
                                "from_cache": True,
                                "ts_ms": run_ts_ms(),
                            },
                        )
                    )
            else:
                if stream_queue is not None:
                    await stream_queue.put(
                        (
                            "tool_start",
                            node_name,
                            {
                                "name": tc_name,
                                "tool_call_id": tc_id,
                                "args_summary": _summarize_args(tc_args),
                                "category": category,
                                "ts_ms": run_ts_ms(),
                            },
                        )
                    )
                tool_result = await execute_tool(
                    tc_name,
                    tc_args,
                    available_tools,
                    run_id=tool_context.get("run_id"),
                    node_name=node_name,
                    tool_audit_store=tool_context.get("tool_audit_store"),
                    tool_gateway=tool_context.get("tool_gateway"),
                    activation_source="searched"
                    if exposure.was_activated(tc_name)
                    else "preloaded",
                    provider_snapshot_cache=tool_context.get("provider_snapshot_cache"),
                    trip_run_store=tool_context.get("trip_run_store"),
                )
                if _cacheable_tool_result(tc_name, tool_result):
                    invocation_cache[cache_key] = tool_result
            if isinstance(tool_result, dict):
                authoritative_tool_results.append(tool_result)

            sanitized_result = (
                tool_result.get("sanitized_result")
                if is_tool_execution_envelope(tool_result)
                else tool_result
            )
            if (
                isinstance(sanitized_result, dict)
                and sanitized_result.get("type") == "user_input_required"
            ):
                if can_ask_user:
                    logger.info(
                        f"[{node_name}] ask_user: {sanitized_result.get('question', '')}"
                    )
                    pending_choice = {
                        "question": sanitized_result.get("question", ""),
                        "options": sanitized_result.get("options", []),
                        "selection_type": sanitized_result.get(
                            "selection_type", "single"
                        ),
                        "allow_free_input": sanitized_result.get(
                            "allow_free_input", True
                        ),
                    }
                else:
                    logger.info(f"[{node_name}] 无 ask_user 权限，忽略")
                if stream_queue is not None:
                    await stream_queue.put(
                        (
                            "tool_done",
                            node_name,
                            {
                                "name": tc_name,
                                "tool_call_id": tc_id,
                                "summary": "等待用户输入"
                                if can_ask_user
                                else "（已忽略提问）",
                                "status": ToolExecutionStatus.SUCCESS.value,
                                "duration_ms": round(
                                    (time.perf_counter() - tool_started) * 1000.0, 3
                                ),
                                "ts_ms": run_ts_ms(),
                            },
                        )
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": compact_tool_content_for_model(tool_result),
                    }
                )
                for skipped in tool_calls[tool_index + 1 :]:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": skipped["id"],
                            "content": '{"status":"not_executed","reason":"awaiting_user_input"}',
                        }
                    )
                if pending_choice is not None:
                    return await terminate(
                        iteration,
                        ReactOutcome.AWAITING_USER,
                        pending_choice=pending_choice,
                    )
                break

            tool_status = str(tool_result.get("status") or "")
            tool_succeeded = tool_status in _SUCCEEDED_TOOL_STATUSES
            tool_capability_declared = tool_status in CAPABILITY_DECLARATION_STATUSES
            if tool_capability_declared:
                capability_tool_names.append(tc_name)
            elif tool_succeeded:
                success_count += 1
            else:
                fail_count += 1

            round_counts = {
                "fail": fail_count,
                "success": success_count,
                "capabilities": list(capability_tool_names),
            }
            summary = _summarize_tool_result(tc_name, tool_result)
            model_tool_content = compact_tool_content_for_model(tool_result)
            tool_results_summary.append(f"[{tc_name}]: {summary[:400]}")

            snapshot_cache_metadata = (
                tool_result.get("metadata", {}).get("snapshot_cache", {})
                if isinstance(tool_result.get("metadata"), dict)
                else {}
            )
            provider_snapshot_hit = (
                isinstance(snapshot_cache_metadata, dict)
                and snapshot_cache_metadata.get("origin") == "provider_snapshot_cache"
            )
            if stream_queue is not None:
                await stream_queue.put(
                    (
                        "tool_done",
                        node_name,
                        {
                            "name": tc_name,
                            "tool_call_id": tc_id,
                            "summary": summary,
                            "result_preview": result_preview(tool_result),
                            "status": tool_status,
                            "audit_id": tool_result.get("audit_id"),
                            "degraded": tool_status == "degraded",
                            "fallback_from": tool_result.get("fallback_from"),
                            "fallback_to": tool_result.get("fallback_to"),
                            "category": category,
                            "from_cache": cache_hit or provider_snapshot_hit,
                            "duration_ms": round(
                                (time.perf_counter() - tool_started) * 1000.0, 3
                            ),
                            "ts_ms": run_ts_ms(),
                        },
                    )
                )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": model_tool_content,
                }
            )
            await save_round(
                iteration,
                response=[content, tool_calls, assistant_replay],
                next_tool=tool_index + 1,
            )
            check_cancel_requested(node_name)

        executed_count = total_count - len(capability_tool_names)
        notices: List[str] = []
        if fail_count > 0 and fail_count == executed_count:
            logger.warning(
                f"[{node_name}] 本轮 {executed_count} 个工具全部失败，注入断路提示"
            )
            notices.append(
                "本轮调用的工具未取得资料；这不代表其他来源或已有知识不可用。"
                "可在剩余轮数内换来源或换查询；如仍未核实，请准确说明缺少哪类资料，"
                "并继续提供明确、有用的建议，区分一般建议与必须核实的实时事实，不要编造。"
            )
        if capability_tool_names and success_count == 0:
            names = "、".join(dict.fromkeys(capability_tool_names))
            logger.info(
                f"[{node_name}] 本轮命中日期能力判定：{names}，提示改用其它模态"
            )
            notices.append(
                f"说明：{names} 未被调用，服务端已判定该数据源对你请求的日期没有可查数据"
                "（能力边界，不是调用失败，重试也不会有结果）。"
                f"请不要再调用 {names} 或用同一日期重试，"
                "改用其它交通模态或工具（例如航班、长途客运、通用路线检索、网页检索）"
                "去覆盖同一段行程；确实无任何可用工具时，如实说明该日期暂无法核实。"
            )
        if notices:
            messages.append({"role": "user", "content": "\n".join(notices)})

        await save_round(iteration + 1)

    return await terminate(
        effective_max_iterations,
        ReactOutcome.ITERATION_LIMIT,
        error=f"{node_name}: iteration limit {effective_max_iterations}",
    )
