"""SSE 事件的单一投影。

所有已授权客户端收到同一份脱敏事件流，是否默认展示由前端渐进披露决定，
传输层不区分产品与检视两套受众。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from travel_agent.conversation.intake_contracts import GuidedIntakeState, RouteDecision
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.planning.delivery.summary_card_contracts import TripSummaryCard
from travel_agent.planning.delivery.public.bundle import public_event_manifest
from .audit_projection import audit_safe_value
from travel_agent.tools.display import public_text, result_preview

# 产品生命周期与用户可见的运行边界事件。
_NORMAL_SSE_EVENT_TYPES = frozenset(
    {
        "chat_start",
        "chat_chunk",
        "route_confirmation",
        "guided_intake",
        "approval_gate_raised",
        "chat_complete",
        "delivery_ready",
        "run_terminal",
        "run_cancelled",
        "run_failed",
        "error",
    }
)

# 研究过程思考链（工具生命周期摘要与思考文本）。
_RESEARCH_TRACE_EVENT_TYPES = frozenset(
    {
        "thinking",
        "agent_thinking",
        "agent_progress",
        "tool_start",
        "tool_result",
    }
)

# 检视界面事件类型（脱敏后照常投影）。
#
# 不包含 ``trace_event`` / ``trace_summary``：工作流 trace 仅用于内部观测，
# 思考链已是对外可见的同源摘要；完整 trace 事件由 ``trip_run_events``
# 通过 ``_trace_event_payload`` 持久保存。
_INSPECT_SSE_EVENT_TYPES = frozenset(
    {
        "context_report",
        "context_compaction",
        "usage_update",
        "synthesis_start",
        "trip_summary_card",
    }
)


# ---------------------------------------------------------------------------
# 产品载荷构造函数。
#
# 这些载荷不要经过递归键名黑名单：字段均由已校验模型或上游显式投影产生，
# 递归过滤会误删合法字段（例如 ``GuidedIntakeState.raw_input`` 因含 ``raw_``
# 被丢弃，而 ``ConversationThread.tsx`` 依赖该字段初始化旅行规划）。
# 经所属模型重新校验可以明确字段形状，避免字段在投影中丢失。
# ---------------------------------------------------------------------------


def _project_route_decision(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return RouteDecision.model_validate(value).model_dump(mode="json")


def _project_guided_intake(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return GuidedIntakeState.model_validate(value).model_dump(mode="json")


def _project_summary_card(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return TripSummaryCard.model_validate(value).model_dump(mode="json")


def public_plan_gate_payload(payload: Any) -> Dict[str, Any]:
    """投影计划审批门的客户端载荷。

    实时 ``approval_gate_raised`` 帧与 ``pending_user_choice`` 回放共用此字段集合，
    避免同一 run 的实时门与恢复门字段不一致。

    不包含 ``type``：帧的 ``gate`` 字段已标明门的类型，外层持久信封另有
    ``type``（``"approval_gate"``），前端只读取 ``payload.gate``。
    """

    if not isinstance(payload, Mapping):
        return {}
    plan = payload.get("plan") if isinstance(payload.get("plan"), Mapping) else {}
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    return {
        "gate": payload.get("gate"),
        "revision": payload.get("revision"),
        "revision_limit": payload.get("revision_limit"),
        "revision_limit_reached": payload.get("revision_limit_reached"),
        "plan": {
            "steps": [
                {
                    "step": step.get("step"),
                    "agents": step.get("agents"),
                    # 下发完整任务文本：审批门需要用户确认各执行者收到的任务。
                    "tasks": step.get("tasks"),
                }
                for step in steps
                if isinstance(step, Mapping)
            ],
        },
        "plan_text": payload.get("plan_text"),
        "recognized_requirements": {
            key: [
                {
                    "requirement_id": item.get("requirement_id"),
                    "summary": item.get("summary"),
                }
                for item in (
                    payload.get("recognized_requirements", {}).get(key, [])
                    if isinstance(payload.get("recognized_requirements"), Mapping)
                    else []
                )
                if isinstance(item, Mapping)
            ]
            for key in ("hard", "preferences", "attention")
        },
        "decision_options": payload.get("decision_options"),
    }


def project_sse_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """返回单条 SSE 载荷的脱敏投影；需要丢弃时返回 None。"""
    event_type = str(payload.get("type") or "")
    if event_type == "agent_thinking":
        return None
    if event_type in _RESEARCH_TRACE_EVENT_TYPES:
        return _project_research_trace(event_type, payload)
    if event_type in _INSPECT_SSE_EVENT_TYPES:
        return _project_inspect_event(event_type, payload)
    if event_type not in _NORMAL_SSE_EVENT_TYPES:
        return None
    return _project_product_event(event_type, payload)


def _common_ids(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: payload[key]
        for key in ("type", "message_id", "run_id", "session_id", "ts_ms")
        if key in payload
    }


def _project_research_trace(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    projected: Dict[str, Any] = _common_ids(payload)
    for key in ("agent_name", "step_name"):
        if key in payload:
            projected[key] = payload[key]

    if event_type in {"thinking", "agent_thinking", "agent_progress"}:
        projected["content"] = public_text(payload.get("content", ""))
        if payload.get("progress_status") in {"running", "completed", "failed"}:
            projected["progress_status"] = payload["progress_status"]
        if event_type == "agent_progress":
            projected["result_preview"] = result_preview(payload.get("result_preview", []))
        return projected

    projected.update(
        {
            "tool_name": payload.get("tool_name", ""),
            "tool_call_id": payload.get("tool_call_id"),
            "category": payload.get("category", "other"),
            "from_cache": bool(payload.get("from_cache", False)),
        }
    )
    if event_type == "tool_start":
        projected["args_summary"] = payload.get("args_summary", "")
    else:
        # ``status`` 是本次工具调用结束方式的唯一字段。不下发 ``success`` 与
        # ``degraded``：前者把三态（成功 / 失败 / 已声明能力）压成布尔，
        # 后者等价于 ``status == 'degraded'``；前端由 ``status`` 推导两者。
        projected.update(
            {
                "summary": public_text(payload.get("summary", "")),
                "result_preview": result_preview(payload.get("result_preview", [])),
                "status": payload.get("status"),
                "duration_ms": payload.get("duration_ms"),
            }
        )
        # 不下发 ``audit_id``：它是内部标识，检视面板不展示标识符。
        for key in ("fallback_from", "fallback_to"):
            if payload.get(key) is not None and payload.get(key) != "":
                projected[key] = payload[key]
    return projected


# 只剔除明确的原始 I/O 键，保留有意提供的检视摘要。
_INSPECT_RAW_KEY_EXACT = frozenset(
    {
        "prompt",
        "prompts",
        "messages",
        "arguments",
        "argument",
        "args",
        "headers",
        "request_body",
        "response_body",
        "body",
    }
)


def _inspect_key_is_raw(key: str) -> bool:
    normalized = key.lower()
    if normalized in _INSPECT_RAW_KEY_EXACT or normalized.startswith("raw_"):
        return True
    return normalized.endswith(("_payload", "_body", "_headers")) or "message_content" in normalized


def _scrub_inspect_tree(value: Any) -> Any:
    """剔除原始 I/O 键，保留结构化检视摘要与计数。"""
    if isinstance(value, dict):
        return {
            str(k): _scrub_inspect_tree(v)
            for k, v in value.items()
            if not _inspect_key_is_raw(str(k))
        }
    if isinstance(value, (list, tuple, set)):
        return [_scrub_inspect_tree(item) for item in value]
    return value


def _project_inspect_event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """投影检视界面的上下文、用量、trace 与摘要卡事件。"""
    projected = _scrub_inspect_tree(payload)
    if not isinstance(projected, dict):
        projected = {}
    projected["type"] = event_type
    for key in ("message_id", "run_id", "session_id", "ts_ms"):
        if key in payload:
            projected[key] = payload[key]

    if event_type == "trip_summary_card" and "summary_card" in payload:
        projected["summary_card"] = _project_summary_card(payload.get("summary_card"))
    if event_type == "usage_update":
        # 按字段白名单投影。``tier`` / ``provider`` / ``model`` /
        # ``cached_input_tokens`` / ``latency_ms`` / ``ttft_ms`` 等按次归因字段
        # 仅写入 ``run_llm_calls``，不下发客户端。保留 ``node`` / ``agent``，
        # 用于标明当前消耗所属步骤；具体上屏字段由前端 ``costLedger.ts`` 决定。
        projected = {
            key: projected[key]
            for key in (
                "type",
                "call_id",
                "message_id",
                "run_id",
                "node",
                "agent",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "cost_usd",
                "estimated",
                "usage_complete",
            )
            if key in projected
        }
    if event_type == "context_compaction":
        # 按字段白名单投影。持久快照中的 ``messages_compressed`` /
        # ``tokens_before`` / ``tokens_after`` 只保留在运行记录中，
        # 客户端不展示 token 计数；此处下发摘要、保留的约束及事件有效性字段。
        projected = {
            key: projected[key]
            for key in ("type", "message_id", "event_id", "source", "occurred_at", "summary", "key_constraints")
            if key in projected
        }
    return projected


def _project_product_event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    common = _common_ids(payload)
    if event_type == "chat_start":
        # ``route_decision`` 是该帧对客户端的核心字段：它决定待处理状态文案，
        # 并初始化 ``lastRouteDecision`` 以驱动发现→收集的后续卡片。
        # ``mode`` / ``resumed`` / ``attempt`` / ``checkpoint_thread_id``
        # 属于运行记录，不下发。
        #
        # 没有路由决策时该键缺省而非空对象：前端会把 ``{}`` 当作有效决策读取。
        out: Dict[str, Any] = {**common}
        if isinstance(payload.get("route_decision"), Mapping):
            out["route_decision"] = _project_route_decision(payload["route_decision"])
        return out
    if event_type == "chat_chunk":
        # 不下发 ``role``：该值恒为 ``"assistant"``，前端不读取。
        return {
            **common,
            "content": payload.get("content", ""),
            "show_content": payload.get("show_content", payload.get("content", "")),
        }
    if event_type == "route_confirmation":
        return {
            **common,
            "route_decision": _project_route_decision(payload.get("route_decision")),
        }
    if event_type == "guided_intake":
        # 不下发 ``task_status``：表单展示内容由 ``guided_intake`` 本身决定。
        return {
            **common,
            "guided_intake": _project_guided_intake(payload.get("guided_intake")),
        }
    if event_type == "approval_gate_raised":
        # ``run_status`` 由后端统一给出并被客户端读取，前端不重复硬编码；
        # ``mode`` 不下发，该审批门只用于深度研究流程。
        return {
            **common,
            "gate": payload.get("gate"),
            "payload": public_plan_gate_payload(payload.get("payload")),
            "run_status": TripRunStatus.AWAITING_INPUT.value,
        }
    if event_type == "chat_complete":
        # ``run_status`` 用于决定审批门是否继续展示（不等于 ``awaiting_input``
        # 时清除）；``mode`` 不下发。
        out: Dict[str, Any] = {
            **common,
            "run_status": payload.get("run_status"),
            "final_content": payload.get("final_content", ""),
        }
        if payload.get("guard_blocked"):
            out["guard_blocked"] = True
        if isinstance(payload.get("run_cost_summary"), dict):
            # 整体下发成本汇总：哪些字段上屏统一由前端 ``costLedger.ts`` 决定，
            # 此处不重复筛选。
            out["run_cost_summary"] = audit_safe_value(payload["run_cost_summary"])
        return out
    if event_type == "delivery_ready":
        # 不下发 ``message`` / ``event_id``：提示文案由客户端生成，
        # 重放游标使用 ``event_seq``。
        return {
            **common,
            "event_seq": payload.get("event_seq"),
            "bundle_id": payload.get("bundle_id"),
            "manifest": public_event_manifest(payload.get("manifest")),
            # ``bundle`` 已是构造好的公开投影，无需再次过滤。
            "bundle": payload.get("bundle") or {},
        }
    if event_type == "run_terminal":
        # ``status`` / ``event_seq`` / ``bundle_id`` 是客户端校验
        # 两个投递帧原子性的契约字段；``message`` / ``event_id`` 不下发。
        out = {
            **common,
            "event_seq": payload.get("event_seq"),
            "status": payload.get("status"),
            "bundle_id": payload.get("bundle_id"),
        }
        if isinstance(payload.get("run_cost_summary"), dict):
            # 成功的深度研究 run 在此帧结束，已结算的成本汇总随该帧下发；
            # 具体上屏字段由前端 ``costLedger.ts`` 决定。
            out["run_cost_summary"] = audit_safe_value(payload["run_cost_summary"])
        return out
    if event_type == "run_cancelled":
        # 取消的 run 只下发已生成的正文与已结算成本；状态由帧名本身表达。
        out = {
            **common,
            "final_content": payload.get("final_content", ""),
        }
        if isinstance(payload.get("run_cost_summary"), dict):
            out["run_cost_summary"] = audit_safe_value(payload["run_cost_summary"])
        return out
    if event_type == "run_failed":
        # run_failed 帧只下发用户可读的失败提示；reason_code / error_code
        # 属内部归因字段，仅保留在运行记录里供操作侧查阅，不下发客户端。
        out = {
            **common,
            "message": payload.get("message")
            or "旅行方案暂时无法生成，请稍后重试。",
        }
        if isinstance(payload.get("run_cost_summary"), dict):
            out["run_cost_summary"] = audit_safe_value(payload["run_cost_summary"])
        return out
    # error 及其他允许下发的产品错误：只下发固定提示，不透出供应商原始信息。
    return {
        **common,
        "message": payload.get("message")
        or "旅行方案暂时无法生成，请稍后重试。",
    }
