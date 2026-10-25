"""Planning requirements constraints resolution."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from travel_agent.planning.requirements.constraints.items import _public_summary
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


def _resolve_conflicts(constraints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """单值冲突先取较新记录，同一时刻按来源优先级仲裁。"""
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for c in constraints:
        by_cat.setdefault(c["category"], []).append(c)
    for cat, group in by_cat.items():
        if cat in _SINGULAR_CATEGORIES and len(group) > 1:
            ordered = sorted(
                group,
                key=lambda item: (
                    item.get("updated_at") or "",
                    _SINGULAR_SOURCE_PRECEDENCE.get(_item_source(item), -1),
                    1 if item.get("type") == "hard" else 0,
                ),
                reverse=True,
            )
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
        key = semantic_key(c)
        if key in index_by_key:
            merge_item(out[index_by_key[key]], c)
        else:
            index_by_key[key] = len(out)
            out.append(c)
    return out
