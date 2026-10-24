from __future__ import annotations

from typing import Any, Dict, List


def append_recent_history(
    messages: List[Dict[str, Any]],
    state: Any,
    limit: int = 8,
) -> None:
    "将 state.messages 末 limit 条转为 role/content dict, 就地追加到 messages 列表。"
    recent = (getattr(state, "messages", None) or [])[-limit:]
    for msg in recent:
        if hasattr(msg, "type"):
            role = "user" if msg.type == "human" else "assistant"
            content = (
                msg.content if isinstance(msg.content, str) else str(msg.content or "")
            )
            if content:
                messages.append({"role": role, "content": content})


def session_history_for_context_builder(state: Any) -> List[Dict[str, Any]]:
    "Convert all loaded history; ContextBuilder owns the context budget."

    history: List[Dict[str, Any]] = []
    for msg in getattr(state, "messages", None) or []:
        if hasattr(msg, "type"):
            role = "user" if msg.type == "human" else "assistant"
            history.append({"role": role, "content": msg.content or ""})
    return history
