"""
FastAnswer Agent 节点 (Domain Layer)

快速模式：知识问答 + 少量低延迟只读事实工具。
特点：
- 基于 LLM 内置知识 + 轻量 RAG 快速回答
- 对常见高波动事实（如汇率）优先使用已接入的真实数据工具
- 边界自知机制：检测到需要深度调研时，主动提示用户切换模式
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import time
import uuid
from ...llm.task_routing import TaskKind, llm_for_task

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from travel_agent.planning.state import TravelAgentState
from ...llm.router import get_model_router
from travel_agent.conversation.answer_presentation import OutputGuard
from ...tools.governance import tool_envelope_to_evidence_candidate
from travel_agent.tools.knowledge_results import knowledge_tool_documents, knowledge_tool_summaries
from ...memory.context_builder import ContextBuilder, ContextBudget
from ...panels.constraint import (
    format_constraint_pack_for_prompt,
    referenced_context_sections,
)
from ..scope.constraint_normalizer import build_run_constraint_pack
from travel_agent.planning.tool_context import build_tool_context_from_state
from travel_agent.tools.access import filter_tools_for_agent, get_available_tools
from travel_agent.conversation.history import session_history_for_context_builder
from travel_agent.tools.react import streaming_react_loop
from .prompts import DISCOVERY_OBJECTIVE_INSTRUCTION, SYSTEM_PROMPT

if TYPE_CHECKING:
    from travel_agent.runtime.events import EventBuffer

logger = logging.getLogger(__name__)

_NODE_NAME = "fast_answer_agent"

_CURRENCY_TOOL_NAME = "latest_exchange_rates"
_CURRENCY_CODES = {
    "AUD",
    "CAD",
    "CHF",
    "CNY",
    "EUR",
    "GBP",
    "HKD",
    "JPY",
    "KRW",
    "SGD",
    "THB",
    "USD",
}
_CURRENCY_ALIASES = {
    "CNY": ("人民币", "rmb", "cny", "cnh"),
    "JPY": ("日元", "日币", "日圓", "日圆", "yen", "jpy"),
    "USD": ("美元", "美金", "美刀", "usd", "dollar", "dollars"),
    "EUR": ("欧元", "eur", "euro", "euros"),
    "GBP": ("英镑", "gbp", "pound", "pounds"),
    "HKD": ("港币", "港元", "hkd"),
    "KRW": ("韩元", "krw"),
    "SGD": ("新币", "新加坡元", "sgd"),
    "THB": ("泰铢", "thb"),
    "AUD": ("澳元", "aud"),
    "CAD": ("加元", "cad"),
    "CHF": ("瑞郎", "瑞士法郎", "chf"),
}
_EXCHANGE_RATE_QUERY_RE = re.compile(
    r"(汇率|兑换|换算|兑|exchange\s*rate|currency|convert|conversion)",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_CN_DATE_RE = re.compile(r"(?<!\d)(\d{4})年(\d{1,2})月(\d{1,2})日")


def _detect_currency_pair(query: str) -> Optional[tuple[str, str]]:
    """Return (base, target) for common exchange-rate wording, or None."""
    if not query or not _EXCHANGE_RATE_QUERY_RE.search(query):
        return None

    hits: List[tuple[int, str]] = []
    upper_query = query.upper()
    for match in re.finditer(r"\b[A-Z]{3}\b", upper_query):
        code = match.group(0)
        if code in _CURRENCY_CODES:
            hits.append((match.start(), code))

    lowered = query.lower()
    for code, aliases in _CURRENCY_ALIASES.items():
        for alias in aliases:
            start = lowered.find(alias.lower())
            if start >= 0:
                hits.append((start, code))
                break

    ordered: List[str] = []
    for _, code in sorted(hits, key=lambda item: item[0]):
        if code not in ordered:
            ordered.append(code)
    if len(ordered) < 2:
        return None
    return ordered[0], ordered[1]


def _extract_requested_currency_date(query: str) -> Optional[str]:
    """Extract an explicit user date so latest FX cannot answer a dated query."""

    match = _ISO_DATE_RE.search(query) or _CN_DATE_RE.search(query)
    if match is None:
        return None
    try:
        return datetime.date(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        ).isoformat()
    except ValueError:
        return None


def _extract_mcp_text_payload(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("content"), list):
            for item in value["content"]:
                text = _extract_mcp_text_payload(item)
                if text:
                    return text
        if "result" in value:
            return _extract_mcp_text_payload(value["result"])
    if isinstance(value, list):
        for item in value:
            text = _extract_mcp_text_payload(item)
            if text:
                return text
    return ""


def _exchange_payload_from_envelope(envelope: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sanitized = envelope.get("sanitized_result") if isinstance(envelope, dict) else None
    text = _extract_mcp_text_payload(sanitized)
    if not text:
        text = _extract_mcp_text_payload(envelope.get("result") if isinstance(envelope, dict) else None)
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _format_rate(value: float) -> str:
    if value >= 100:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if value >= 10:
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _build_exchange_realtime_context(
    *,
    query: str,
    base: str,
    target: str,
    envelope: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not envelope:
        return {
            "prompt": (
                "实时汇率工具不可用。用户询问当前汇率时，不要编造具体数字；"
                "只能说明暂时无法读取实时汇率，并建议以银行或支付渠道实时牌价为准。"
            ),
            "evidence": None,
        }

    status = str(envelope.get("status") or "")
    if status != "success":
        error = envelope.get("error") or envelope.get("result_summary") or "unknown error"
        if status in {"not_applicable", "reference_only"}:
            return {
                "prompt": (
                    f"该日期不适用于当前 latest 汇率工具（{error}）。"
                    "不要使用工具失败式措辞，也不要用最新汇率冒充指定日期事实；"
                    "直接说明当前工具只支持最新数据。"
                ),
                "evidence": None,
            }
        return {
            "prompt": (
                f"实时汇率工具调用失败（{error}）。用户询问当前汇率时，不要编造具体数字；"
                "只能说明暂时无法读取实时汇率，并建议以银行或支付渠道实时牌价为准。"
            ),
            "evidence": None,
        }

    data = _exchange_payload_from_envelope(envelope)
    rates = data.get("rates") if isinstance(data, dict) else None
    amount = data.get("amount", 1) if isinstance(data, dict) else 1
    rate_value = None
    if isinstance(rates, dict) and target in rates:
        try:
            rate_value = float(rates[target]) / float(amount or 1)
        except (TypeError, ValueError, ZeroDivisionError):
            rate_value = None
    if rate_value is None:
        return {
            "prompt": (
                "实时汇率工具返回了不可解析结果。用户询问当前汇率时，不要编造具体数字；"
                "只能说明暂时无法读取实时汇率，并建议以银行或支付渠道实时牌价为准。"
            ),
            "evidence": None,
        }

    date = str(data.get("date") or "").strip()
    retrieved_at = str(envelope.get("retrieved_at") or "").strip()
    source = "Frankfurter public exchange-rate API"
    rate_text = f"1 {base} = {_format_rate(rate_value)} {target}"
    evidence_id = f"ev_{envelope.get('audit_id') or uuid.uuid4().hex[:12]}"
    evidence = {
        "evidence_id": evidence_id,
        "source_type": "tool",
        "source_name": source,
        "tool_name": _CURRENCY_TOOL_NAME,
        "title": f"{rate_text} ({date or 'latest'})",
        "snippet": f"{rate_text}; date={date or 'latest'}; query={query}",
        "retrieved_at": retrieved_at,
        "freshness_status": "fresh",
        "authority_score": 0.82,
        "metadata": {
            "tool_audit_id": envelope.get("audit_id"),
            "tool_status": status,
            "untrusted_content": False,
            "trust_level": envelope.get("trust_level"),
        },
    }
    prompt = (
        "实时汇率工具结果（优先级高，请基于它回答）：\n"
        f"- 查询：{base} -> {target}\n"
        f"- 汇率：{rate_text}\n"
        f"- 数据日期：{date or 'latest'}\n"
        f"- 检索时间：{retrieved_at or 'unknown'}\n"
        f"- 来源：{source} via `{_CURRENCY_TOOL_NAME}`\n"
        "回答必须说明来源和日期；不要要求用户切换任何内部模式。"
    )
    return {"prompt": prompt, "evidence": evidence}


async def _build_realtime_tool_context(
    *,
    state: TravelAgentState,
    stream_queue: Optional["EventBuffer"],
) -> Dict[str, Any]:
    pair = _detect_currency_pair(state.user_query or "")
    if not pair:
        return {"prompt": "", "evidence_records": []}

    base, target = pair
    tool_call_id = f"fast_currency_{uuid.uuid4().hex[:8]}"
    args = {"base_currency": base, "to_currencies": target}
    requested_date = _extract_requested_currency_date(state.user_query or "")
    if requested_date is not None:
        args["requested_date"] = requested_date

    try:
        from travel_agent.tools.execution import execute_tool
        from ...builders import get_components
        from ...tools.registry import get_tool_registry
        from travel_agent.runtime.events import run_ts_ms

        registry = get_tool_registry()
        if not registry.has_tool(_CURRENCY_TOOL_NAME):
            context = _build_exchange_realtime_context(
                query=state.user_query or "",
                base=base,
                target=target,
                envelope=None,
            )
            return {"prompt": context["prompt"], "evidence_records": []}

        if stream_queue is not None:
            await stream_queue.put(("tool_start", _NODE_NAME, {
                "name": _CURRENCY_TOOL_NAME,
                "tool_call_id": tool_call_id,
                "args_summary": f"base_currency={base}, to_currencies={target}",
                "category": "data",
                "ts_ms": run_ts_ms(),
            }))

        components = get_components()
        started = time.perf_counter()
        envelope = await execute_tool(
            _CURRENCY_TOOL_NAME,
            args,
            allowed_tool_names={_CURRENCY_TOOL_NAME},
            max_retries=1,
            run_id=state.run_id,
            node_name=_NODE_NAME,
            tool_audit_store=getattr(components, "tool_audit_store", None),
            activation_source="fast_realtime_preflight",
        )
        context = _build_exchange_realtime_context(
            query=state.user_query or "",
            base=base,
            target=target,
            envelope=envelope,
        )

        if stream_queue is not None:
            evidence = context.get("evidence")
            summary = evidence.get("title") if isinstance(evidence, dict) else str(envelope.get("result_summary") or "实时汇率读取失败")
            status = str(envelope.get("status") or "")
            await stream_queue.put(("tool_done", _NODE_NAME, {
                "name": _CURRENCY_TOOL_NAME,
                "tool_call_id": tool_call_id,
                "summary": summary,
                # ``status``（ToolExecutionStatus）是工具轮次结论的唯一权威：
                # 「该日期不适用于 latest 汇率工具」是能力判定，不是调用失败，
                # 布尔 success 无法表达这个第三态，已从合同中删除。
                "status": status,
                "audit_id": envelope.get("audit_id"),
                "degraded": status == "degraded",
                "category": "data",
                "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "ts_ms": run_ts_ms(),
            }))

        evidence_records = [context["evidence"]] if isinstance(context.get("evidence"), dict) else []
        return {"prompt": context["prompt"], "evidence_records": evidence_records}
    except Exception as exc:
        logger.warning("FastAnswer 实时汇率工具预检失败: %s", exc)
        context = _build_exchange_realtime_context(
            query=state.user_query or "",
            base=base,
            target=target,
            envelope={"status": "failed", "error": str(exc)},
        )
        return {"prompt": context["prompt"], "evidence_records": []}


async def fast_answer_node(state: TravelAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """
    快速回答 Agent 节点。
    轻量知识问答；仅对已接入的低延迟事实类型调用工具。
    检测到超出能力边界时，用任务语言引导到旅行规划或目的地比较。
    """
    router = get_model_router()

    stream_queue: Optional["EventBuffer"] = config.get("configurable", {}).get("stream_queue")

    llm = llm_for_task(router, TaskKind.QUICK_ANSWER)
    user_query = state.user_query or ""
    current_time = state.current_time or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    preset_suffix = ""
    if state.preset_context:
        from ...preset.injector import PresetInjector
        preset_suffix = PresetInjector.format_for_agent(state.preset_context)

    # Constraint Pack：**这条路径上偏好 / 画像 / 记忆 / preset 的节奏与预算抵达模型的
    # 唯一通道**，而且与深度路径同一个装配函数（``build_run_constraint_pack``）。
    # 快路径此前没有 pack：preset 里的节奏与预算档位没有结构化装配，在这条路上
    # 一个字都到不了模型，那两项只有 ``UserProfile`` 那条平行通道说话
    # —— 同一个用户问一句话和做一份规划，对「快还是慢、省还是贵」拿到两个不同的答案。
    # 代价是每轮多一次 Fast 模型调用（自由文本抽取那一步），这是明确接受的取舍：
    # 不做那一步，两条路径的装配就不同源，而不同源正是这条缺陷的形状。
    constraint_pack = await build_run_constraint_pack(state)
    constraint_text = format_constraint_pack_for_prompt(constraint_pack)

    base_system = SYSTEM_PROMPT.format(current_time=current_time)
    if preset_suffix:
        base_system += preset_suffix
    if constraint_text:
        base_system += "\n\n" + constraint_text

    # 将 LangGraph messages 转为 dict 格式（供 ContextBuilder 使用）。
    # 不在这里设条数上限：裁剪与压缩判断都是预算层的职责。
    raw_history = session_history_for_context_builder(state)

    # 解析 Anchor 摘要（若存在）
    from ...memory.compressor import AnchorSummary
    session_anchor_obj = None
    if state.session_anchor:
        try:
            session_anchor_obj = AnchorSummary.from_dict(state.session_anchor)
        except Exception as e:
            logger.debug(f"FastAnswer: Anchor 解析失败: {e}")

    # 会话轴的预算与压缩检测。**它不再装配任何记忆层，这是刻意的**（与深度路径那侧的
    # ``agents/scope/node.py::_measure_session_size`` 同一个理由）：偏好、画像、手写
    # 记忆、检索记忆现在全部经 Constraint Pack 抵达模型 —— 让这一层也装一份，同一条
    # 手写记忆就会在【本轮统一约束】与【用户明确要求】两节里各印一遍，而那两节的
    # 强制力措辞还不一样。``ContextBuilder`` 上已经没有记忆层入参了。
    from ...config import get_settings
    ctx_builder = ContextBuilder(ContextBudget(response_reserve=get_settings().fast_model.max_tokens))
    built_ctx = await ctx_builder.build_context(
        session_id=state.session_id or "",
        system_prompt=base_system,
        recent_messages=raw_history,
        session_anchor=session_anchor_obj,
        session_compressed=state.session_compressed,
    )

    # ── 压缩信号处理 ──────────────────────────────────────────────────────
    # 一次请求最多压一轮（``ContextBudget.max_compaction_rounds_per_request``）：
    # 压完立刻用新 Anchor 重装一次上下文，不再回头看还需不需要压。
    context_compaction: Dict[str, Any] = {"triggered": False}
    if built_ctx.needs_compaction and stream_queue is not None:
        from ...memory.compaction import CompactionBusy, get_compaction_service

        try:
            result = await get_compaction_service().compact(
                user_id=state.user_id or "",
                session_id=state.session_id or "",
                source="automatic",
            )
        except CompactionBusy:
            # 已经有一次在跑（或提交时被抢先）。这是正常跳过，不是失败。
            logger.info("FastAnswer: 会话已有压缩在进行，本轮沿用原上下文")
            result = None
        except Exception as e:
            # 压缩失败就照原上下文继续，不额外发事件：这条路径上没有「压缩进度」这
            # 一类事件了（见 ``chat_stream_handlers`` 里那段说明），而本轮压缩没成，
            # 下面的 ``context_report`` 自然报 triggered=False。
            logger.error(f"FastAnswer: 自动压缩失败，继续使用原始上下文: {e}")
            result = None
        if result is not None:
            anchor = result.anchor
            session_anchor_obj = anchor
            context_compaction = {
                "triggered": True,
                "tokens_before": anchor.tokens_before,
                "tokens_after": anchor.tokens_after,
                "messages_compressed": anchor.messages_compressed,
                "summary_preview": anchor.summary[:200]
                + ("..." if len(anchor.summary) > 200 else ""),
            }
            await stream_queue.put(("context_compaction", _NODE_NAME, result.event))
            built_ctx = await ctx_builder.build_context(
                session_id=state.session_id or "",
                system_prompt=base_system,
                recent_messages=raw_history,
                session_anchor=session_anchor_obj,
                session_compressed=True,
            )

    # context_report：压缩结论出来之后随流下发一次。
    # 列的是 ``referenced_context_sections(pack)`` —— 与 ``format_constraint_pack_for_prompt``
    # 同一个产地（``panels/constraint.py::_constraint_prompt_sections``），所以「屏幕上说
    # 参考了」与「模型真的读到了」在这条路上也不可能各自漂移。深度路径那侧同一份报告由
    # 深度路径由 Request Contract 归一化节点发。
    #
    # 这一轮什么都没参考（没有条目进 prompt，也没压缩）时 ``build_context_report``
    # 返回 None，这个事件就不发 —— 印记的出现本身要能证明数据存在。
    if stream_queue is not None:
        from ...memory.context_builder import build_context_report
        report = build_context_report(
            referenced_sections=referenced_context_sections(constraint_pack),
            compaction=context_compaction,
        )
        if report is not None:
            await stream_queue.put(("context_report", _NODE_NAME, report))

    messages: List[Dict[str, Any]] = [{"role": "system", "content": built_ctx.system_prompt}]
    messages.extend(built_ctx.messages)
    if str((state.route_decision or {}).get("route") or "") == "destination_discovery":
        messages.append({"role": "system", "content": DISCOVERY_OBJECTIVE_INSTRUCTION})

    # 这里**没有**「向 state 回写压缩状态」那一段。它写的 ``needs_compaction`` 全仓
    # 没有读取方，而它的条件读的是**重建之后**的 ``built_ctx``：压缩成功那一支已经用
    # ``session_compressed=True`` 重新装配过，``needs_compaction`` 必然是 False，
    # 于是「成功不写、失败反而可能写」。压缩这件事在这条路径上的出口只有一个 ——
    # 下面已经发过的 ``context_report``（连同持久化用的 ``context_compaction`` 事件），
    # 新 Anchor 本身由 ``CompactionService`` 落库，下一轮由载入器读回来。

    realtime_context = await _build_realtime_tool_context(state=state, stream_queue=stream_queue)
    realtime_prompt = str(realtime_context.get("prompt") or "")
    realtime_evidence = [
        item for item in (realtime_context.get("evidence_records") or []) if isinstance(item, dict)
    ]
    wire_tail = []
    if str((state.route_decision or {}).get("route") or "") == "destination_discovery":
        wire_tail.append({"role": "system", "content": DISCOVERY_OBJECTIVE_INSTRUCTION})
    if realtime_prompt:
        wire_tail.append({"role": "user", "content": realtime_prompt})
    wire_tail.append({"role": "user", "content": f"用户问题：{user_query}"})
    # Measure the next wire request after tool context is known. Cumulative
    # billed tokens never decide whether a context window needs compaction.
    built_ctx = await ctx_builder.build_context(
        session_id=state.session_id or "", system_prompt=base_system,
        recent_messages=raw_history, session_anchor=session_anchor_obj,
        session_compressed=state.session_compressed, runtime_messages=wire_tail,
    )
    messages = [{"role": "system", "content": built_ctx.system_prompt}, *built_ctx.messages, *wire_tail]

    try:
        available_tools = filter_tools_for_agent(
            await get_available_tools(state.selected_mcp_servers or []), _NODE_NAME,
        )
        react = await streaming_react_loop(
            llm=llm, messages=messages, available_tools=available_tools,
            stream_queue=stream_queue, node_name=_NODE_NAME, max_iterations=3,
            tool_context=build_tool_context_from_state(state),
        )
        response = react.require_final_answer()
        tool_results = react.tool_results
        docs = knowledge_tool_documents(tool_results)
        logger.info(f"FastAnswer 生成回答，长度: {len(response)}")
        tool_evidence = []
        for envelope in tool_results:
            candidate = tool_envelope_to_evidence_candidate(envelope)
            if candidate is not None:
                candidate["source_type"] = envelope.get("source_type") or "tool"
                tool_evidence.append(candidate)
        grounding = OutputGuard().check(
            output_text=response,
            retrieved_docs=docs,
            evidence_records=[*realtime_evidence, *tool_evidence],
        )
        response = grounding.processed_output
        if not response.strip():
            raise RuntimeError("FastAnswer final answer is empty after output validation")
        if stream_queue is not None:
            await stream_queue.put(("token", _NODE_NAME, response))
        retrieval_summaries = knowledge_tool_summaries(tool_results)
        if realtime_evidence:
            retrieval_summaries.append({
                "query": user_query,
                "mode": "fast_realtime_tool",
                "selected_count": len(realtime_evidence),
                "sources": [
                    {
                        "source_name": ev.get("source_name"),
                        "tool_name": ev.get("tool_name"),
                        "title": ev.get("title"),
                        "retrieved_at": ev.get("retrieved_at"),
                    }
                    for ev in realtime_evidence
                ],
            })
        return {
            # pack 回写进 state：本轮到底装了哪些约束，trace 与快照要看得见同一份
            # 东西，而不是只看得见它的投影。
            "constraint_pack": constraint_pack,
            "constraint_pack_revision": state.constraint_pack_revision + 1,
            "messages": [AIMessage(content=response)],
            "is_completed": True,
            "output_confidence": grounding.confidence.value,
            "final_grounding": grounding.final_grounding,
            "retrieval_summaries": retrieval_summaries,
            "synthesis_mode": "fast",
        }

    except Exception as e:
        logger.error(f"FastAnswer 执行失败: {e}")
        raise
