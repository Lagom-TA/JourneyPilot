from __future__ import annotations

from typing import Any, Dict, List


def session_history_for_context_builder(state: Any) -> List[Dict[str, Any]]:
    "转换已加载的全部历史；上下文预算由 ContextBuilder 负责。"

    history: List[Dict[str, Any]] = []
    for msg in getattr(state, "messages", None) or []:
        if hasattr(msg, "type"):
            role = "user" if msg.type == "human" else "assistant"
            history.append({"role": role, "content": msg.content or ""})
    return history
