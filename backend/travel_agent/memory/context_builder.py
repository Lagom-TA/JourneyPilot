from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..llm.token_counting import estimate_message_tokens

logger = logging.getLogger(__name__)

# 仅用于离线估算，账单以供应商 usage 为准。
_TOKEN_ESTIMATE_MODEL = "gpt-4o"
_TRIM_SAFETY_RATIO = 0.9


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    from ..llm.token_counting import estimate_tokens

    return estimate_tokens(text, model)


@dataclass
class ContextBudget:
    total_context_limit: int = 120_000
    response_reserve: int = 8_000
    system_prompt_budget: int = 600
    anchor_summary_budget: int = 2_000
    manual_memory_facts_limit: int = 20
    compaction_threshold: float = 0.50
    # 压缩只推进到实际进入摘要的消息，输入上限与触发阈值分开。
    compaction_input_tokens: int = 50_000
    max_messages_per_compaction: int = 500

    @property
    def compaction_trigger_tokens(self) -> int:
        return int(self.total_context_limit * self.compaction_threshold)


@dataclass
class BuiltContext:
    system_prompt: str
    messages: List[Dict[str, Any]]
    token_usage: Dict[str, int] = field(default_factory=dict)
    needs_compaction: bool = False


_LENS_SECTION_KEYS = ("hard", "preference", "reference")


def build_context_report(
    *,
    referenced_sections: List[Dict[str, Any]],
    compaction: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    sections = []
    for section in referenced_sections:
        key = str(section.get("key") or "")
        if key not in _LENS_SECTION_KEYS:
            raise ValueError(f"上下文透镜段名不在合同里: {key!r}")
        items = [str(item) for item in section.get("items") or []]
        if items:
            sections.append({"key": key, "items": items})
    triggered = bool((compaction or {}).get("triggered"))
    if not sections and not triggered:
        return None
    return {
        "referenced_sections": sections,
        "compaction": {"triggered": triggered},
    }


class ContextBuilder:
    def __init__(self, budget: Optional[ContextBudget] = None) -> None:
        self._budget = budget or ContextBudget()

    async def build_context(
        self,
        session_id: str,
        system_prompt: str,
        recent_messages: List[Dict[str, Any]],
        session_anchor: Optional[Any] = None,
        session_compressed: bool = False,
        runtime_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> BuiltContext:
        budget = self._budget
        model = _TOKEN_ESTIMATE_MODEL

        anchor_text = ""
        if session_anchor is not None:
            try:
                # 摘要可能含硬性要求，必须整体计入预算，不能直接截断。
                anchor_text = session_anchor.format_for_prompt()
            except Exception as e:
                logger.debug(f"ContextBuilder: Anchor 格式化失败: {e}")

        system_tokens = count_tokens(system_prompt, model)
        anchor_tokens = count_tokens(anchor_text, model)
        runtime_tokens = sum(estimate_message_tokens(m, model) for m in runtime_messages or [])
        all_messages_tokens = sum(estimate_message_tokens(m, model) for m in recent_messages)

        estimated_total = (
            system_tokens
            + anchor_tokens
            + all_messages_tokens
            + runtime_tokens
            + budget.response_reserve
        )

        needs_compaction = False

        if estimated_total >= budget.compaction_trigger_tokens:
            if not session_compressed:
                needs_compaction = True
                logger.info(
                    f"ContextBuilder v3: 触发压缩信号 "
                    f"估算 {estimated_total} tokens ≥ 阈值 {budget.compaction_trigger_tokens} tokens"
                )
            else:
                logger.warning(
                    f"ContextBuilder v3: 再次超阈值警告 "
                    f"估算 {estimated_total} tokens, 已压缩过，建议开新会话"
                )

        used_so_far = system_tokens + anchor_tokens + runtime_tokens
        available_for_messages = max(0, budget.total_context_limit - budget.response_reserve - used_so_far)
        if used_so_far + budget.response_reserve > budget.total_context_limit:
            raise ValueError("fixed context exceeds the model window; constraints cannot be truncated")

        trimmed_messages = self._trim_messages(recent_messages, available_for_messages, model)

        system_parts = [system_prompt]

        if anchor_text:
            system_parts.append(
                "\n\n【历史对话摘要 - 本次会话背景】\n"
                "以下是本次会话较早期对话的压缩摘要，请在此基础上继续协助用户：\n"
                f"{anchor_text}"
            )

        final_system = "".join(system_parts)

        total_used = count_tokens(final_system, model) + sum(
            estimate_message_tokens(m, model) for m in trimmed_messages
        ) + runtime_tokens

        logger.debug(
            f"ContextBuilder v3: anchor={anchor_tokens}t, "
            f"msgs={len(trimmed_messages)}条, "
            f"total≈{total_used}t / {budget.total_context_limit}t "
            f"(needs_compaction={needs_compaction})"
        )

        token_usage = {
            "system": system_tokens,
            "anchor_summary": anchor_tokens,
            "runtime": runtime_tokens,
            "messages": sum(
                estimate_message_tokens(m, model) for m in trimmed_messages
            ),
            "total_estimated": total_used,
            "all_messages_estimated": all_messages_tokens,
            "budget": budget.total_context_limit,
            "threshold": budget.compaction_trigger_tokens,
        }

        return BuiltContext(
            system_prompt=final_system,
            messages=trimmed_messages,
            token_usage=token_usage,
            needs_compaction=needs_compaction,
        )

    def _trim_messages(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        model: str,
    ) -> List[Dict[str, Any]]:
        if not messages:
            return []

        # 整轮保留，避免工具结果脱离调用或供应商回复被误当成用户陈述。
        groups = []
        for msg in messages:
            if msg.get("role") == "user" or not groups:
                groups.append([])
            groups[-1].append(msg)
        selected = []
        used_tokens = 0
        for group in reversed(groups):
            tokens = sum(estimate_message_tokens(m, model) for m in group)
            if used_tokens + tokens > max_tokens:
                break
            selected = group + selected
            used_tokens += tokens

        if len(selected) < len(messages):
            logger.info(
                f"ContextBuilder v3: 消息裁剪 {len(messages)} → {len(selected)} 条 "
                f"({used_tokens}/{max_tokens} tokens)"
            )

        return selected
