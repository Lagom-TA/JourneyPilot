from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any, Dict, List, Optional, Set

from travel_agent.tools.gateway_contracts import ToolGatewayDecision
from ..runtime.budget import RunBudgetExhausted, current_budget_ledger, guard_run_budget
from ..runtime.operations import (
    ModelWindowClosed,
    await_model_operation,
    remaining_model_seconds,
)
from .gateway import get_tool_gateway
from .governance import (
    PROVIDER_RESULT_OUTCOME_METADATA_KEY,
    ToolExecutionStatus,
    build_tool_execution_envelope,
)
from .registry import get_tool_registry
from .result import ToolResultOutcome, classify_tool_result

logger = logging.getLogger(__name__)


async def execute_tool(tool_name, arguments, *args, **kwargs):
    from copy import deepcopy

    from travel_agent.runtime.journal import current_worker_journal

    from ..tools.gateway import _manifest_from_metadata

    journal = current_worker_journal.get()
    if tool_name == "knowledge_search":
        from ..config.loader import get_settings

        if not get_settings().embedding.enabled:
            return build_tool_execution_envelope(
                tool_name=tool_name,
                arguments=arguments,
                status="blocked",
                error="向量知识库已由 embedding.enabled=false 关闭",
                source="builtin",
            )
    if journal is None:
        return await _execute_tool_once(tool_name, arguments, *args, **kwargs)
    allowed = kwargs.get("allowed_tool_names")
    available = args[0] if args else kwargs.get("available_tools")
    if allowed is None and available is not None:
        allowed = {item["schema"]["function"]["name"] for item in available}
    if allowed is not None and tool_name not in allowed:
        return await _execute_tool_once(tool_name, arguments, *args, **kwargs)
    key = journal.next_tool(tool_name, arguments)
    tools = journal.payload.setdefault("tools", {})
    previous = tools.get(key)
    manifest = _manifest_from_metadata(
        tool_name, get_tool_registry().get_tool_metadata(tool_name)
    )
    if manifest.disabled:
        return await _execute_tool_once(tool_name, arguments, *args, **kwargs)
    if previous and "result" in previous:
        return deepcopy(previous["result"])
    if previous and manifest.side_effecting:
        # A started write may have completed before the result was committed.
        result = build_tool_execution_envelope(
            tool_name=tool_name,
            arguments=arguments,
            status="failed",
            error="tool_outcome_unknown_requires_reconciliation",
        )
    else:
        tools[key] = {
            "name": tool_name,
            "arguments": deepcopy(arguments),
            "phase": "started",
        }
        await journal.commit()
        result = await _execute_tool_once(tool_name, arguments, *args, **kwargs)
    tools[key]["result"] = deepcopy(result)
    tools[key]["phase"] = "completed"
    await journal.commit()
    return result


async def _execute_tool_once(
    tool_name: str,
    arguments: Dict[str, Any],
    available_tools: Optional[List[Dict[str, Any]]] = None,
    allowed_tool_names: Optional[Set[str]] = None,
    max_retries: int = 2,
    run_id: Optional[str] = None,
    node_name: Optional[str] = None,
    tool_audit_store: Any = None,
    tool_gateway: Any = None,
    activation_source: Optional[str] = None,
    provider_snapshot_cache: Any = None,
    trip_run_store: Any = None,
    allow_fallback: bool = True,
) -> Dict[str, Any]:
    "执行工具调用，通过 ToolRegistry 路由到本地工具或 MCP 工具。"
    if allowed_tool_names is None and available_tools is not None:
        allowed_tool_names = {
            t["schema"]["function"]["name"]
            for t in available_tools
            if "schema" in t and "function" in t["schema"]
        }

    registry = get_tool_registry()
    main_meta = registry.get_tool_metadata(tool_name)
    gateway = tool_gateway or get_tool_gateway()
    before = await gateway.before_call(
        tool_name=tool_name,
        arguments=arguments,
        registry=registry,
        allowed_tool_names=allowed_tool_names,
        run_id=run_id,
        node_name=node_name,
        audit_store=tool_audit_store,
    )
    if before.envelope is not None:
        if before.decision in {
            ToolGatewayDecision.NOT_APPLICABLE,
            ToolGatewayDecision.REFERENCE_ONLY,
        }:
            logger.info(
                "工具 [%s] 日期能力判定为 %s: %s",
                tool_name,
                before.decision.value,
                before.reason,
            )
        elif before.decision != ToolGatewayDecision.ALLOW:
            logger.warning(
                "工具 [%s] 被 ToolGateway 阻断: %s", tool_name, before.reason
            )
        return before.envelope
    main_manifest = before.manifest
    if main_manifest.side_effecting or tool_name == "knowledge_search":
        max_retries = 0
        allow_fallback = False

    # Gateway permissions and date capabilities must be decided before spending budget.
    try:
        remaining_model_seconds(f"tool.{tool_name}")
    except ModelWindowClosed as exc:
        envelope = build_tool_execution_envelope(
            tool_name=tool_name,
            arguments=arguments,
            status=ToolExecutionStatus.FAILED.value,
            error=str(exc),
            source=str(main_meta.get("source") or "unknown"),
            server_name=main_meta.get("server_name"),
            category=str(main_meta.get("category") or "other"),
            activation_source=activation_source,
        )
        envelope["metadata"]["research_window_closed"] = True
        return envelope

    try:
        guard_run_budget(f"tool.{tool_name}", tool_calls=1)
    except RunBudgetExhausted as exc:
        envelope = build_tool_execution_envelope(
            tool_name=tool_name,
            arguments=arguments,
            status=ToolExecutionStatus.FAILED.value,
            error=exc.reason_code,
            source=str(main_meta.get("source") or "unknown"),
            server_name=main_meta.get("server_name"),
            category=str(main_meta.get("category") or "other"),
            activation_source=activation_source,
        )
        envelope["metadata"]["run_budget_exhausted"] = exc.dimension
        return envelope
    ledger = current_budget_ledger()
    if ledger is not None and ledger.tool_retries_exhausted(tool_name):
        envelope = build_tool_execution_envelope(
            tool_name=tool_name,
            arguments=arguments,
            status=ToolExecutionStatus.FAILED.value,
            error="tool_retries_exhausted",
            source=str(main_meta.get("source") or "unknown"),
            server_name=main_meta.get("server_name"),
            category=str(main_meta.get("category") or "other"),
            activation_source=activation_source,
        )
        envelope["metadata"]["tool_retries_exhausted"] = tool_name
        return envelope

    snapshot_scope = None
    snapshot_cache = provider_snapshot_cache
    try:
        from ..storage.provider_snapshot_cache import (
            get_provider_snapshot_cache,
            provider_snapshot_scope_for_tool,
        )

        snapshot_scope = provider_snapshot_scope_for_tool(tool_name, arguments)
        if snapshot_scope is not None:
            snapshot_cache = snapshot_cache or get_provider_snapshot_cache()
            lookup = await snapshot_cache.lookup(snapshot_scope)
            if lookup.outcome == "hit" and lookup.record is not None:
                cached_result = lookup.record.snapshot
                envelope = build_tool_execution_envelope(
                    tool_name=tool_name,
                    arguments=arguments,
                    result=cached_result,
                    status=ToolExecutionStatus.SUCCESS.value,
                    source=str(main_meta.get("source") or "unknown"),
                    server_name=main_meta.get("server_name"),
                    category=main_manifest.category,
                    retrieved_at=str(cached_result.get("retrieved_at") or "") or None,
                    freshness_hint=cached_result.get("freshness_hint"),
                    activation_source=activation_source,
                )

                envelope["sanitized_result"] = cached_result
                envelope["metadata"]["snapshot_cache"] = lookup.record.trace_metadata(
                    origin="provider_snapshot_cache",
                    outcome="hit",
                )
                return await gateway.after_call(
                    envelope,
                    manifest=main_manifest,
                    run_id=run_id,
                    audit_store=tool_audit_store,
                )
    except Exception as exc:
        logger.info(
            "provider snapshot cache unavailable; using live tool call: %s", exc
        )
        snapshot_scope = None
        snapshot_cache = None

    async def persist_provider_snapshot(envelope: Dict[str, Any]) -> None:
        if snapshot_scope is None or snapshot_cache is None:
            return
        from ..storage.provider_snapshot_cache import build_provider_snapshot_record

        record = build_provider_snapshot_record(scope=snapshot_scope, envelope=envelope)
        if record is None:
            return
        stored = await snapshot_cache.write(record)
        metadata = dict(envelope.get("metadata") or {})
        metadata["snapshot_cache"] = record.trace_metadata(
            origin="live",
            outcome="stored" if stored else "unavailable",
        )
        envelope["metadata"] = metadata

    async def record_retry_failure(error: str, attempt: int) -> None:
        envelope = build_tool_execution_envelope(
            tool_name=tool_name,
            arguments=arguments,
            status=ToolExecutionStatus.FAILED.value,
            error=error,
            source=str(main_meta.get("source") or "unknown"),
            server_name=main_meta.get("server_name"),
            category=main_manifest.category,
            activation_source=activation_source,
        )
        envelope["metadata"].update(
            {
                "retry_attempt": attempt + 1,
                "retry_scheduled": True,
                "max_attempts": max_retries + 1,
            }
        )
        await gateway.after_call(
            envelope,
            manifest=main_manifest,
            run_id=run_id,
            audit_store=tool_audit_store,
        )

    last_error: Optional[str] = None
    research_window_closed = False
    budget_exhausted: Optional[str] = None
    for attempt in range(max_retries + 1):
        try:
            remaining_model_seconds(f"tool.{tool_name}.attempt_{attempt + 1}")

            if ledger is not None:
                ledger.reserve_tool_call(f"tool.{tool_name}", tool_name)
                if attempt > 0:
                    ledger.record_tool_retry(tool_name)
            result = await await_model_operation(
                registry.execute(tool_name, **arguments),
                operation=f"tool.{tool_name}.attempt_{attempt + 1}",
            )

            outcome, outcome_reason = classify_tool_result(tool_name, result)
            if outcome is not ToolResultOutcome.FAILED:
                if outcome is ToolResultOutcome.EMPTY_SUCCESS:
                    logger.info(
                        "工具 [%s] provider 成功应答但零命中，不重试不降级: %s",
                        tool_name,
                        outcome_reason,
                    )
                result = _attach_freshness_metadata(tool_name, result)
                envelope = build_tool_execution_envelope(
                    tool_name=tool_name,
                    arguments=arguments,
                    result=result,
                    status=ToolExecutionStatus.SUCCESS.value,
                    source=str(main_meta.get("source") or "unknown"),
                    server_name=main_meta.get("server_name"),
                    category=main_manifest.category,
                    retrieved_at=result.get("retrieved_at"),
                    freshness_hint=result.get("freshness_hint"),
                    activation_source=activation_source,
                )
                if outcome is ToolResultOutcome.EMPTY_SUCCESS:
                    envelope["metadata"][PROVIDER_RESULT_OUTCOME_METADATA_KEY] = (
                        ToolResultOutcome.EMPTY_SUCCESS.value
                    )
                if attempt > 0:
                    envelope["metadata"].update(
                        {
                            "retry_count": attempt,
                            "recovered_after_retry": True,
                        }
                    )
                return await gateway.after_call(
                    envelope,
                    manifest=main_manifest,
                    run_id=run_id,
                    audit_store=tool_audit_store,
                    post_policy_hook=persist_provider_snapshot,
                )
            else:
                last_error = outcome_reason

                logger.info(
                    "工具 [%s] 调用失败（attempt %d/%d）: %s",
                    tool_name,
                    attempt + 1,
                    max_retries + 1,
                    last_error,
                )
                is_retryable = _is_retryable_tool_error(last_error)
                if is_retryable and attempt < max_retries:
                    await record_retry_failure(last_error, attempt)
                    await await_model_operation(
                        asyncio.sleep(_tool_retry_backoff_seconds(attempt)),
                        operation=f"tool.{tool_name}.retry_backoff",
                    )
                    continue
                break
        except RunBudgetExhausted as exc:
            last_error = str(exc)
            budget_exhausted = exc.dimension
            break
        except ModelWindowClosed as exc:
            last_error = str(exc)
            research_window_closed = True
            break
        except (TimeoutError, ConnectionError, RuntimeError, OSError, ValueError) as e:
            err_str = str(e).lower()
            is_retryable = _is_retryable_tool_error(err_str)
            last_error = str(e)
            if is_retryable and attempt < max_retries:
                wait = _tool_retry_backoff_seconds(attempt)
                logger.warning(
                    f"工具 [{tool_name}] 可重试错误（attempt {attempt + 1}），{wait:.0f}s 后重试: {e}"
                )
                await record_retry_failure(last_error, attempt)
                try:
                    await await_model_operation(
                        asyncio.sleep(wait),
                        operation=f"tool.{tool_name}.retry_backoff",
                    )
                except ModelWindowClosed as closed:
                    last_error = str(closed)
                    research_window_closed = True
                    break
                continue
            elif attempt == max_retries:
                logger.error(
                    f"工具 [{tool_name}] 执行失败（已重试 {max_retries} 次）: {e}"
                )
            else:
                logger.error(f"工具 [{tool_name}] 不可重试错误: {e}")
                break

    blocked_fallback_to: Optional[str] = None
    try:
        from ..tools.fallback import build_fallback_args, get_fallback_tool

        fallback_info = get_fallback_tool(tool_name)
        if (
            not research_window_closed
            and budget_exhausted is None
            and allow_fallback
            and fallback_info
            and main_manifest.allow_offline_fallback
        ):
            fallback_name, adapter_key = fallback_info
            if registry.has_tool(fallback_name):
                if (
                    allowed_tool_names is not None
                    and fallback_name not in allowed_tool_names
                ):
                    blocked_fallback_to = fallback_name
                    boundary_reason = f"主工具失败后可降级到 {fallback_name}，但该备用工具不在当前 agent allowlist 中"
                    logger.warning(
                        "工具 [%s] 降级被 agent allowlist 阻止: fallback=%s node=%s",
                        tool_name,
                        fallback_name,
                        node_name,
                    )
                    last_error = f"{last_error or '主工具失败'}；{boundary_reason}"
                    raise PermissionError(boundary_reason)
                fallback_args = build_fallback_args(
                    tool_name, fallback_name, adapter_key, arguments
                )
                logger.info(
                    "工具 [%s] 降级到 [%s] | cause=%s args=%s",
                    tool_name,
                    fallback_name,
                    last_error or "主工具失败",
                    fallback_args,
                )
                try:
                    fallback_before = await gateway.before_call(
                        tool_name=fallback_name,
                        arguments=fallback_args,
                        registry=registry,
                        allowed_tool_names=allowed_tool_names,
                        run_id=run_id,
                        node_name=node_name,
                        audit_store=tool_audit_store,
                    )
                    if fallback_before.envelope is not None:
                        return fallback_before.envelope

                    if ledger is not None:
                        ledger.reserve_tool_call(f"tool.{fallback_name}", fallback_name)
                    fallback_result = await await_model_operation(
                        registry.execute(fallback_name, **fallback_args),
                        operation=f"tool.{fallback_name}.fallback",
                    )
                    fallback_outcome, fallback_reason = classify_tool_result(
                        fallback_name, fallback_result
                    )
                    if fallback_outcome is not ToolResultOutcome.FAILED:
                        if fallback_outcome is ToolResultOutcome.EMPTY_SUCCESS:
                            logger.info(
                                "备用工具 [%s] provider 成功应答但零命中: %s",
                                fallback_name,
                                fallback_reason,
                            )
                        fallback_result = _attach_freshness_metadata(
                            fallback_name, fallback_result
                        )
                        fallback_meta = registry.get_tool_metadata(fallback_name)
                        envelope = build_tool_execution_envelope(
                            tool_name=fallback_name,
                            arguments=fallback_args,
                            result=fallback_result,
                            status=ToolExecutionStatus.DEGRADED.value,
                            source=str(fallback_meta.get("source") or "unknown"),
                            server_name=fallback_meta.get("server_name"),
                            category=fallback_before.manifest.category,
                            fallback_from=tool_name,
                            fallback_to=fallback_name,
                            degradation_reason=last_error or "主工具失败后降级",
                            retrieved_at=fallback_result.get("retrieved_at"),
                            freshness_hint=fallback_result.get("freshness_hint"),
                            activation_source=activation_source,
                        )
                        if fallback_outcome is ToolResultOutcome.EMPTY_SUCCESS:
                            envelope["metadata"][
                                PROVIDER_RESULT_OUTCOME_METADATA_KEY
                            ] = ToolResultOutcome.EMPTY_SUCCESS.value
                        return await gateway.after_call(
                            envelope,
                            manifest=fallback_before.manifest,
                            run_id=run_id,
                            audit_store=tool_audit_store,
                            gateway_decision=ToolGatewayDecision.DEGRADE,
                        )
                    last_error = f"{last_error or '主工具失败'}；备用工具 {fallback_name} 失败: {fallback_reason}"
                    logger.info(
                        "备用工具 [%s] 也失败: %s", fallback_name, fallback_reason
                    )
                except ModelWindowClosed as closed:
                    research_window_closed = True
                    last_error = str(closed)
                except Exception as fe:
                    fallback_error = str(fe)
                    logger.warning(
                        f"备用工具 [{fallback_name}] 也失败: {fallback_error}"
                    )
                    last_error = (
                        f"{last_error or '主工具失败'}；备用工具失败: {fallback_error}"
                    )
            else:
                logger.warning(f"备用工具 [{fallback_name}] 未在注册表中，跳过降级")
                last_error = (
                    f"{last_error or '主工具失败'}；备用工具 {fallback_name} 未注册"
                )
    except PermissionError:
        pass
    except Exception as e:
        logger.debug(f"降级策略查找失败: {e}")

    envelope = build_tool_execution_envelope(
        tool_name=tool_name,
        arguments=arguments,
        status=ToolExecutionStatus.FAILED.value,
        error=last_error or "未知错误",
        source=str(main_meta.get("source") or "unknown"),
        server_name=main_meta.get("server_name"),
        category=main_manifest.category,
        fallback_to=blocked_fallback_to,
        degradation_reason=last_error,
        activation_source=activation_source,
    )
    if budget_exhausted is not None:
        envelope["metadata"]["run_budget_exhausted"] = budget_exhausted
    if research_window_closed:
        envelope["metadata"]["research_window_closed"] = True
    return await gateway.after_call(
        envelope,
        manifest=main_manifest,
        run_id=run_id,
        audit_store=tool_audit_store,
    )


def _tool_retry_backoff_seconds(attempt: int) -> float:
    """第 attempt 轮重试前的退避秒数（attempt 从 0 开始）。"""
    return _TOOL_RETRY_BASE_SECONDS * (_TOOL_RETRY_FACTOR**attempt)


def _is_retryable_tool_error(error: str) -> bool:
    lowered = str(error or "").lower()
    non_retryable = (
        "usage limit",
        "quota",
        "配额",
        "额度",
        "unauthorized",
        "forbidden",
        "invalid api key",
        "authentication",
        "http 400",
        "400 bad request",
        "http 401",
        "http 403",
    )
    if any(marker in lowered for marker in non_retryable):
        return False
    return any(
        marker in lowered
        for marker in (
            "timeout",
            "timed out",
            "connection",
            "network",
            "refused",
            "reset",
            "temporarily",
            "rate limit",
            "http 429",
            "http 502",
            "http 503",
            "http 504",
            "超时",
            "连接失败",
            "网络错误",
            "暂时不可用",
        )
    )


def _find_published_at_hint(result: Dict[str, Any]) -> str:
    candidates: List[Any] = []
    candidates.append(result.get("published_at"))
    nested = result.get("result")
    if isinstance(nested, dict):
        candidates.append(nested.get("published_at"))
        meta = nested.get("metadata")
        if isinstance(meta, dict):
            candidates.append(meta.get("published_at"))
    data = result.get("data")
    if isinstance(data, dict):
        candidates.append(data.get("published_at"))
        meta = data.get("metadata")
        if isinstance(meta, dict):
            candidates.append(meta.get("published_at"))
    meta = result.get("metadata")
    if isinstance(meta, dict):
        candidates.append(meta.get("published_at"))

    for v in candidates:
        if v is None:
            continue
        text = str(v).strip()
        if text:
            return text
    return ""


def _attach_freshness_metadata(
    tool_name: str, result: Dict[str, Any]
) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {"success": False, "error": f"{tool_name} 返回格式异常"}
    if not result.get("success", True):
        return result

    retrieved_at = str(result.get("retrieved_at") or "").strip()
    if not retrieved_at:
        retrieved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        result["retrieved_at"] = retrieved_at

    published_at = _find_published_at_hint(result)
    if published_at and not str(result.get("published_at") or "").strip():
        result["published_at"] = published_at

    if "source_type" not in result:
        result["source_type"] = "tool"
    result["freshness_hint"] = {
        "tool_name": tool_name,
        "source_type": str(result.get("source_type") or "tool"),
        "published_at": str(result.get("published_at") or ""),
        "retrieved_at": retrieved_at,
    }
    return result


_TOOL_RETRY_BASE_SECONDS = 1.0


_TOOL_RETRY_FACTOR = 2
