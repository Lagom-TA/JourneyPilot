"""上下文压缩器（Application Layer）。

将对话历史压缩为结构化 Anchor Summary，供 ContextBuilder 注入。只压缩 user 与
assistant 消息，不压缩 system prompt、画像或 memory_facts；工具原始结果不保留，
使用 fast 模型执行压缩。
"""

from __future__ import annotations

import logging
from ..llm.task_routing import TaskKind, llm_for_task

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..utils.json_helpers import safe_parse_json

logger = logging.getLogger(__name__)

# 压缩提示词
_COMPRESS_SYSTEM_PROMPT = """\
你是一个对话摘要专家，专门为旅行规划助手场景压缩对话历史。

你的任务是将对话历史压缩为一个结构化摘要，供后续对话继续使用。

要求：
1. 提取**用户本人明确说出**的所有约束和限制条件（如预算、人员构成、特殊需求、不能接受/必须遵守的事项、硬约束），放入 key_constraints 数组。**只从用户（user 角色）写下的内容里提取**，助手（assistant 角色）自己建议的话、推荐的措辞、推测的偏好**一律不算作**用户的约束，不得写进 key_constraints。**早先几条消息里的用户约束也要保留，不得因为被后来的内容盖过而丢弃**。每条约束独立成一个字符串，尽可能用用户的原话措辞（如「不吃香菜」「每天住西湖边」），不要改写稀释。
2. 用自然语言摘要覆盖以下内容（summary 字段）：
   - 用户的核心旅行意图（去哪里、几天、什么时候）
   - 双方已达成的重要决策（如选定的目的地、住宿类型、行程框架）
   - 助手已提供的关键信息结论（无需保留工具调用原始数据，只保留结论）
   - **用户明确点名的专属信息（人物、地点、具体偏好等）必须在摘要里保留**（如「朋友老周推荐去良渚博物院」），不得丢失
   - 当前对话尚未解决的待讨论问题
3. 摘要应简洁但不遗漏任何对后续规划有影响的信息；**在有疑问时以完整保留用户约束与用户亲口事实为准，宁可多写一行也不要丢**
4. 不需要保留工具调用的原始数据或中间推理过程，只保留最终结论
5. 如果已有之前的压缩摘要（existing_anchor），请将新信息合并进去，保持完整性

仅输出 JSON 格式，不要有任何额外文字：
{
  "key_constraints": ["用户约束1", "用户约束2", ...],
  "summary": "自然语言摘要..."
}
"""

_COMPRESS_USER_TEMPLATE = """\
请将以下对话历史压缩为结构化摘要。

{existing_anchor_section}对话历史（{message_count} 条消息）：
{conversation_text}
"""


@dataclass
class AnchorSummary:
    """对话历史的压缩锚点摘要。"""
    compressed_at: str
    messages_compressed: int
    tokens_before: int
    tokens_after: int
    key_constraints: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compressed_at": self.compressed_at,
            "messages_compressed": self.messages_compressed,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "key_constraints": self.key_constraints,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnchorSummary":
        return cls(
            compressed_at=data.get("compressed_at", ""),
            messages_compressed=data.get("messages_compressed", 0),
            tokens_before=data.get("tokens_before", 0),
            tokens_after=data.get("tokens_after", 0),
            key_constraints=data.get("key_constraints", []),
            summary=data.get("summary", ""),
        )

    def format_for_prompt(self) -> str:
        """将 Anchor 格式化为可注入 system prompt 的文本块。"""
        parts = []
        if self.summary:
            parts.append(f"对话摘要：\n{self.summary}")
        if self.key_constraints:
            constraints_text = "\n".join(f"- {c}" for c in self.key_constraints)
            parts.append(f"用户明确约束（必须严格遵守）：\n{constraints_text}")
        return "\n\n".join(parts)

def build_context_compaction_event(
    anchor: AnchorSummary,
    *,
    source: str,
) -> Dict[str, Any]:
    """把已保存的 Anchor 投影为不可变的会话时间线事件。

    事件快照完整摘要与全部约束；后续压缩可以替换会话当前 Anchor，但不能改写这条
    历史事件。
    """
    if source not in {"manual", "automatic"}:
        raise ValueError(f"Unsupported compaction event source: {source}")

    return {
        "event_id": f"ctxcmp_{uuid4().hex}",
        "source": source,
        "occurred_at": anchor.compressed_at or datetime.now(timezone.utc).isoformat(),
        "messages_compressed": max(0, int(anchor.messages_compressed)),
        "tokens_before": max(0, int(anchor.tokens_before)),
        "tokens_after": max(0, int(anchor.tokens_after)),
        "summary": str(anchor.summary or ""),
        "key_constraints": [
            str(constraint).strip()
            for constraint in (anchor.key_constraints or [])
            if str(constraint).strip()
        ],
    }




def _count_tokens(text: str, model: str = "gpt-4o") -> int:
    """离线 token 估算；计费口径以 API 返回的 usage 为准。"""
    from ..llm.token_counting import estimate_tokens

    return estimate_tokens(text, model)


def _format_messages_for_compression(
    messages: List[Dict[str, Any]],
) -> str:
    """将消息列表格式化为压缩提示词中的对话文本。"""
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        if role not in {"user", "assistant"}:
            continue
        role_label = "用户" if role == "user" else "助手"
        parts.append(f"{role_label}：{content}")
    return "\n\n".join(parts)


class ContextCompressor:
    """使用 Fast LLM 将对话历史压缩为 AnchorSummary。

    压缩后的 Anchor 由 ContextBuilder 注入 system prompt。
    """

    async def compress(
        self,
        messages: List[Dict[str, Any]],
        existing_anchor: Optional[AnchorSummary] = None,
        model: str = "gpt-4o",
    ) -> AnchorSummary:
        """调用 Fast LLM 将消息列表压缩为 AnchorSummary。

        messages: user 与 assistant 消息列表（不含工具结果）。
        existing_anchor: 已有摘要，传入后与新内容合并。
        model: 用于 token 计数的模型名。
        """
        from ..llm.router import get_model_router

        if not messages:
            if existing_anchor:
                return AnchorSummary.from_dict(existing_anchor.to_dict())
            return AnchorSummary(
                compressed_at=datetime.now(timezone.utc).isoformat(),
                messages_compressed=0,
                tokens_before=0,
                tokens_after=0,
            )

        conversation_text = _format_messages_for_compression(messages)
        tokens_before = _count_tokens(conversation_text, model)

        existing_anchor_section = ""
        if existing_anchor:
            existing_anchor_section = (
                f"已有的历史压缩摘要（请将新信息合并进去）：\n"
                f"{existing_anchor.format_for_prompt()}\n\n"
            )

        user_content = _COMPRESS_USER_TEMPLATE.format(
            existing_anchor_section=existing_anchor_section,
            message_count=len(messages),
            conversation_text=conversation_text,
        )

        compress_messages = [
            {"role": "system", "content": _COMPRESS_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        router = get_model_router()
        llm = llm_for_task(router, TaskKind.SUMMARY)

        try:
            response_text = await llm.ainvoke(compress_messages)
            parsed = safe_parse_json(response_text)
        except Exception as e:
            logger.error(f"ContextCompressor: LLM 调用失败: {e}")
            raise ValueError("compaction failed; retain original history and boundary") from e

        if not isinstance(parsed, dict) or not isinstance(parsed.get("summary"), str) or not parsed["summary"].strip():
            raise ValueError("invalid compaction output; retain original history and boundary")

        key_constraints = parsed.get("key_constraints", [])
        if not isinstance(key_constraints, list):
            key_constraints = []
        key_constraints = [
            value.strip()
            for value in key_constraints
            if isinstance(value, str) and value.strip()
        ]

        summary = parsed.get("summary", "")
        if not isinstance(summary, str):
            summary = str(summary)

        anchor = AnchorSummary(
            compressed_at=datetime.now(timezone.utc).isoformat(),
            messages_compressed=len(messages),
            tokens_before=tokens_before,
            tokens_after=_count_tokens(summary + " ".join(key_constraints), model),
            key_constraints=key_constraints,
            summary=summary,
        )

        logger.info(
            f"ContextCompressor: 压缩完成 {len(messages)} 条消息, "
            f"token {tokens_before} → {anchor.tokens_after} "
            f"({anchor.tokens_after / max(1, tokens_before) * 100:.0f}%)"
        )
        return anchor
