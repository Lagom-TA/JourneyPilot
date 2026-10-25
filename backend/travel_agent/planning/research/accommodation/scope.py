"""Planning research accommodation scope."""

from __future__ import annotations

from typing import Any, Dict, List

_NODE_NAME = "accommodation_researcher"


def scope_accommodation_gap_tools(
    available_tools: List[Dict[str, Any]],
    recommended_tools: List[str],
    *,
    scoped_retry: bool,
) -> List[Dict[str, Any]]:
    """Keep a scoped lodging retry on the Gate-selected search providers."""
    if not scoped_retry or not recommended_tools:
        return available_tools
    recommended_set = set(recommended_tools)
    scoped = [
        tool
        for tool in available_tools
        if tool.get("schema", {}).get("function", {}).get("name", "") in recommended_set
    ]
    return scoped or available_tools
