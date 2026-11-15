"""约束优先级。"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional

from travel_agent.planning.requirements.constraints.items import (
    _priority_for,
    _public_summary,
    _source_is_current,
)
from travel_agent.planning.requirements.constraints.parameters import (
    _allergy_allergen_key,
    _canonical_accommodation_params,
    _canonical_allergy_params,
    _canonical_mobility_params,
    _canonical_transport_params,
    _positive_int_param,
)

_SINGULAR_CATEGORIES = {"budget_cap", "pace_preference"}


_SINGULAR_SOURCE_PRECEDENCE = {
    "current_query": 7,
    "plan_gate_amendment": 6,
    "run_supplement": 5,
    "preset": 4,
    "session_anchor": 3,
    "manual_memory": 2,
    "manual_profile": 1,
    "memory_fact": 0,
    "auto_portrait": 0,
}


def _merge_constraint_params(
    category: str, left: Optional[Dict[str, Any]], right: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """把同一条约束的两次抽取所得的 typed params 并成一份，取**更紧**的那一版。"""

    merged = dict(left or {})
    for key, value in (right or {}).items():
        if key == "max_continuous_walk_minutes":
            incoming_walk = _positive_int_param(value)
            if incoming_walk is None:
                continue
            existing_walk = _positive_int_param(merged.get(key))
            merged[key] = (
                min(existing_walk, incoming_walk)
                if existing_walk is not None
                else incoming_walk
            )
            continue
        if isinstance(value, list):
            merged[key] = list(dict.fromkeys([*(merged.get(key) or []), *value]))
        elif key == "earliest_departure_local" and merged.get(key):
            merged[key] = max(str(merged[key]), str(value))
        elif key == "latest_arrival_local" and merged.get(key):
            merged[key] = min(str(merged[key]), str(value))
        elif isinstance(value, bool):
            merged[key] = bool(merged.get(key)) or value
        elif value is not None:
            merged[key] = value
    if category == "transport_constraint":
        return _canonical_transport_params("", merged)
    if category == "accommodation_preference":
        return _canonical_accommodation_params("", merged)
    if category in {"elderly_mobility", "health_condition"}:
        return _canonical_mobility_params("", merged)
    if category == "food_allergy":
        return _canonical_allergy_params("", merged)
    return merged or None


def _item_source(item: Dict[str, Any]) -> str:
    """这条 item 的来源层（``source_refs`` 里第一条的 source）。"""
    for ref in item.get("source_refs") or []:
        if isinstance(ref, dict) and ref.get("source"):
            return str(ref["source"])
    return ""


def _item_is_current(item: Dict[str, Any]) -> bool:
    """混合来源或来源未明的条目保留为参考。"""
    refs = item.get("source_refs")
    return isinstance(refs, list) and bool(refs) and all(
        isinstance(ref, dict)
        and ref.get("scope") != "historical"
        and _source_is_current(str(ref.get("source") or ""))
        for ref in refs
    )


def _demote_reference_item(item: Dict[str, Any]) -> None:
    if not _item_is_current(item):
        item["type"] = "soft"
        item["priority"] = _priority_for("soft", str(item.get("confidence") or ""))
        item["enforcement_scope"] = ["advisory"]
        item["candidate_worker_kinds"] = []
        item.pop("unsupported_hard_category", None)


def normalize_constraint_pack(
    pack: Any, *, preset_pack_constraints: Any = None
) -> Dict[str, Any]:
    """按来源重建约束分组，且不改变传入的包。"""
    from travel_agent.planning.requirements.constraints.items import _now_iso
    from travel_agent.planning.requirements.constraints.sources import _map_preset_constraints

    normalized = deepcopy(pack) if isinstance(pack, dict) else {}
    existing = normalized.get("constraints")
    if not isinstance(existing, list) or not existing:
        existing = [
            item
            for key in ("hard_constraints", "soft_preferences")
            for item in (normalized.get(key) if isinstance(normalized.get(key), list) else [])
        ]
    constraints = [item for item in existing if isinstance(item, dict)]

    applied = _map_preset_constraints(preset_pack_constraints, _now_iso())
    if applied:
        applied_values = {(item["category"], item["value"]) for item in applied}
        for item in constraints:
            if (item.get("category"), item.get("value")) in applied_values:
                continue
            for ref in item.get("source_refs") or []:
                if isinstance(ref, dict) and ref.get("source") == "preset":
                    ref["scope"] = "historical"

    for item in constraints:
        if item.get("status") is None:
            item["status"] = "active"
        _demote_reference_item(item)

    if applied:
        present = {
            (item.get("category"), item.get("value"))
            for item in constraints
            if item.get("status") in (None, "active")
            and _item_is_current(item)
            and any(
                isinstance(ref, dict) and ref.get("source") == "preset"
                for ref in item.get("source_refs") or []
            )
        }
        constraints.extend(
            item for item in applied if (item["category"], item["value"]) not in present
        )

    active = [item for item in constraints if item.get("status") in (None, "active")]
    normalized["constraints"] = constraints
    normalized["hard_constraints"] = [item for item in active if item.get("type") == "hard"]
    normalized["soft_preferences"] = [item for item in active if item.get("type") == "soft"]
    return normalized


def _resolve_conflicts(
    constraints: List[Dict[str, Any]], *, source_order: Optional[Mapping[str, int]] = None
) -> List[Dict[str, Any]]:
    """单值冲突按用户请求的实际顺序仲裁；历史重放不能伪装成新输入。"""

    def rank(item: Dict[str, Any]) -> tuple[Any, ...]:
        refs = [ref for ref in item.get("source_refs") or [] if isinstance(ref, dict)]
        position = max(
            ((source_order or {}).get(str(ref.get("origin_ref") or ""), -1) for ref in refs),
            default=-1,
        )
        return (
            1 if position >= 0 else 0,
            position,
            item.get("updated_at") or "",
            _SINGULAR_SOURCE_PRECEDENCE.get(_item_source(item), -1),
            1 if item.get("type") == "hard" else 0,
        )

    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for c in constraints:
        if _item_is_current(c):
            by_cat.setdefault(c["category"], []).append(c)
    for cat, group in by_cat.items():
        if cat in _SINGULAR_CATEGORIES and len(group) > 1:
            ordered = sorted(group, key=rank, reverse=True)
            winner, older = ordered[0], ordered[1:]
            winner["supersedes"] = older[0]["constraint_id"] if older else None
            for o in older:
                o["status"] = "superseded"
    return constraints


def _dedupe_constraints(constraints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def semantic_family(item: Dict[str, Any]) -> str:
        category = str(item.get("category") or "")
        return (
            "mobility"
            if category in {"elderly_mobility", "health_condition"}
            else category
        )

    def semantic_key(item: Dict[str, Any]) -> tuple[Any, ...]:
        """两条 item 是「同一句话说了两遍」还是「两个互相冲突的答案」。"""

        family = semantic_family(item)
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        normalized_value = re.sub(
            r"[\s：:，,。；;、/\\\-_]", "", str(item.get("value") or "").lower()
        )
        if family == "food_allergy":
            return family, _allergy_allergen_key(item)
        if family == "mobility":
            return family, item.get("type")
        if family == "budget_cap":
            amount = params.get("amount")
            return (
                family,
                params.get("currency"),
                params.get("per"),
                amount if amount is not None else normalized_value,
            )
        return family, normalized_value

    def merge_item(
        existing: Dict[str, Any], incoming: Dict[str, Any]
    ) -> Dict[str, Any]:
        existing["params"] = _merge_constraint_params(
            str(existing.get("category") or ""),
            existing.get("params") or {},
            incoming.get("params") or {},
        )
        existing["source_refs"] = [
            *existing.get("source_refs", []),
            *[
                ref
                for ref in incoming.get("source_refs", [])
                if ref not in existing.get("source_refs", [])
            ],
        ]
        if incoming.get("type") == "hard":
            existing["type"] = "hard"
            existing["priority"] = "hard"
        if incoming.get("visibility") == "user_visible":
            existing["visibility"] = "user_visible"
        existing["candidate_worker_kinds"] = list(
            dict.fromkeys(
                [
                    *existing.get("candidate_worker_kinds", []),
                    *incoming.get("candidate_worker_kinds", []),
                ]
            )
        )
        existing["enforcement_scope"] = list(
            dict.fromkeys(
                [
                    *existing.get("enforcement_scope", []),
                    *incoming.get("enforcement_scope", []),
                ]
            )
        )
        existing["public_summary"] = _public_summary(
            str(existing.get("category") or ""),
            str(existing.get("value") or ""),
            existing.get("params"),
        )
        return existing

    index_by_key: Dict[tuple[Any, ...], int] = {}
    out: List[Dict[str, Any]] = []
    for c in constraints:
        _demote_reference_item(c)
        refs = c.get("source_refs")
        sources = tuple(
            sorted(
                {
                    (str(ref.get("source") or ""), str(ref.get("scope") or ""))
                    if isinstance(ref, dict) else ("", "")
                    for ref in refs
                }
            )
        ) if isinstance(refs, list) else ()
        key = (sources, semantic_key(c))
        if key in index_by_key:
            merge_item(out[index_by_key[key]], c)
        else:
            index_by_key[key] = len(out)
            out.append(c)
    return out
