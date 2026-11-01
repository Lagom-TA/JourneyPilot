"""把长期画像、手写记忆和 preset 的明确字段带给规划角色。

用户自由文本由模型直接理解，这里不做分句或语义抽取。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from travel_agent.planning.requirements.constraints.items import _get
from travel_agent.planning.requirements.constraints.loading import load_constraint_sources
from travel_agent.planning.requirements.constraints.resolution import (
    _dedupe_constraints,
    _resolve_conflicts,
)
from travel_agent.planning.requirements.constraints.sources import (
    _auto_portrait_block,
    _map_manual_memory_facts,
    _map_manual_profile,
    _map_preset_constraints,
)


def _empty_pack(state: Any) -> Dict[str, Any]:
    return {
        "pack_meta": {
            "run_id": _get(state, "run_id") or "",
            "user_id": _get(state, "user_id") or "",
            "session_id": _get(state, "session_id") or "",
            "built_at": datetime.now(timezone.utc).isoformat(),
            "missing_source_layers": ["application_components_unavailable"],
            "partial_reasons": [],
        },
        "constraints": [],
        "hard_constraints": [],
        "soft_preferences": [],
    }


async def build_planning_constraint_pack(state: Any) -> Dict[str, Any]:
    try:
        from travel_agent.bootstrap.registry import get_components

        get_components()
    except RuntimeError:
        return _empty_pack(state)
    loaded = await load_constraint_sources(state)
    now = datetime.now(timezone.utc).isoformat()
    constraints: list[Dict[str, Any]] = []
    if loaded.user_profile is not None:
        constraints.extend(_map_manual_profile(loaded.user_profile, now))
        portrait = _auto_portrait_block(loaded.user_profile, now)
        if portrait is not None:
            constraints.append(portrait)
    constraints.extend(_map_manual_memory_facts(loaded.manual_memory_facts, now))
    constraints.extend(_map_preset_constraints(_get(state, "preset_pack_constraints"), now))
    constraints = _resolve_conflicts(_dedupe_constraints(constraints))
    active = [item for item in constraints if item["status"] == "active"]
    return {
        "pack_meta": {
            "run_id": _get(state, "run_id") or "",
            "user_id": _get(state, "user_id") or "",
            "session_id": _get(state, "session_id") or "",
            "built_at": now,
            "missing_source_layers": list(loaded.missing_layers),
            "partial_reasons": list(loaded.partial_reasons),
            "manual_memory_truncated": bool(loaded.manual_memory_truncated),
        },
        "constraints": constraints,
        "hard_constraints": [item for item in active if item["type"] == "hard"],
        "soft_preferences": [item for item in active if item["type"] == "soft"],
    }
