from __future__ import annotations

from typing import Any, Dict, Mapping

# Enforce only at write time: routing must not deny a just-granted revision.
MAXIMUM_COMPOSITION_REPAIR_ATTEMPTS = 3

_COMPOSITION_REPAIR = "composition_repair"


def composition_repair_attempts(state: Any) -> int:
    return int(getattr(state, "composition_repair_attempts", 0) or 0)


def composition_repair_budget_exhausted(state: Any) -> bool:
    return composition_repair_attempts(state) >= MAXIMUM_COMPOSITION_REPAIR_ATTEMPTS


def apply_composition_repair_budget(
    state: Any,
    update: Mapping[str, Any],
    *,
    route_key: str,
    exhausted_route: str,
) -> Dict[str, Any]:
    """Enforce the discrete composition_repair budget on a gate state update."""
    out: Dict[str, Any] = dict(update)
    if out.get(route_key) != _COMPOSITION_REPAIR:
        return out
    attempts = composition_repair_attempts(state)
    if attempts >= MAXIMUM_COMPOSITION_REPAIR_ATTEMPTS:
        out[route_key] = exhausted_route
        return out
    out["composition_repair_attempts"] = attempts + 1
    return out





REPAIR_CONTEXT_CHAR_LIMIT = 600


def bounded_repair_context(stage: str, detail: str) -> str:
    """One bounded line stating which composition stage failed and why."""
    text = f"{stage} 阶段失败 — {detail}".strip()
    if len(text) <= REPAIR_CONTEXT_CHAR_LIMIT:
        return text
    return text[: REPAIR_CONTEXT_CHAR_LIMIT - 1] + "…"
