from __future__ import annotations

from typing import Any, Dict


def build_tool_context_from_state(state: Any) -> Dict[str, Any]:
    "Build optional ToolGateway context from workflow state and app stores."
    context: Dict[str, Any] = {
        "run_id": getattr(state, "run_id", None),
    }
    try:
        from ..builders import get_components

        components = get_components()
        context["tool_audit_store"] = getattr(components, "tool_audit_store", None)
        context["provider_snapshot_cache"] = getattr(
            components,
            "provider_snapshot_cache",
            None,
        )
        context["trip_run_store"] = getattr(components, "trip_run_store", None)
    except Exception:
        pass
    return context
