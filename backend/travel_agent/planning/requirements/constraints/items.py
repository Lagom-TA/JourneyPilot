"""约束条目。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from travel_agent.planning.requirements.constraints.parameters import (
    _budget_amount_param,
    _canonical_constraint_params,
)

_CORE_CATEGORIES = {
    "food_allergy",
    "budget_cap",
    "elderly_mobility",
    "child_friendly",
    "transport_constraint",
    "accommodation_preference",
    "pace_preference",
}


_EXTENSION_CATEGORIES = {
    "destination_preference",
    "dietary_restriction",
    "health_condition",
}


_ALL_CATEGORIES = _CORE_CATEGORIES | _EXTENSION_CATEGORIES | {"other"}


_HARD_CATEGORIES = {"elderly_mobility", "health_condition"}


_CONDITIONAL_HARD_CATEGORIES = {
    "budget_cap",
    "child_friendly",
    "transport_constraint",
    "accommodation_preference",
    "pace_preference",
}


_BUDGET_HARD_HINTS = (
    "上限",
    "不超过",
    "以内",
    "别超",
    "最多",
    "封顶",
    "no more than",
    "cap",
    "max",
)


_HARD_HINTS = _BUDGET_HARD_HINTS + (
    "必须",
    "务必",
    "不能",
    "不要",
    "别",
    "禁止",
    "不得",
    "不安排",
    "不早于",
    "不晚于",
    "要求",
    "禁烟",
    "避开",
    "避免",
    "坚持",
    "只能",
    "只坐",
    "只用",
    "avoid",
    "must",
    "never",
    "no ",
)


_EXPLICIT_SOURCES = {
    "manual_profile",
    "session_anchor",
    "current_query",
    "plan_gate_amendment",
    "run_supplement",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cid(*parts: Any) -> str:
    import hashlib

    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return f"c_{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:16]}"


def _get(state: Any, key: str, default: Any = None) -> Any:
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        return v.isoformat()
    except Exception:
        return None


def _normalize_category(cat: Any) -> str:
    c = str(cat or "").strip().lower()
    return c if c in _ALL_CATEGORIES else "other"


def _default_type(category: str, value: str, source: str) -> str:
    """按类别确定默认强度；预算仅在显式来源且有上限措辞时为 hard。"""
    if category in _HARD_CATEGORIES:
        return "hard"
    if category in _CONDITIONAL_HARD_CATEGORIES:
        v = (value or "").lower()
        hints = _BUDGET_HARD_HINTS if category == "budget_cap" else _HARD_HINTS
        if (source in _EXPLICIT_SOURCES or source == "memory_fact") and any(
            h in v for h in hints
        ):
            return "hard"
    return "soft"


def _priority_for(ctype: str, confidence: str) -> str:
    if ctype == "hard":
        return "hard"
    if confidence == "high":
        return "strong"
    if confidence == "medium":
        return "normal"
    return "weak"


def _enforcement_policy(
    category: str, params: Optional[Dict[str, Any]], ctype: str
) -> Dict[str, Any]:
    if ctype != "hard":
        return {"enforcement_scope": ["advisory"], "candidate_worker_kinds": []}
    if category == "budget_cap":
        return {"enforcement_scope": ["composition"], "candidate_worker_kinds": []}
    if category == "transport_constraint":
        candidate_local = bool(
            params
            and any(
                key in params
                for key in (
                    "avoid_overnight",
                    "earliest_departure_local",
                    "latest_arrival_local",
                    "avoid",
                )
            )
        )
        return {
            "enforcement_scope": ["candidate", "composition"]
            if candidate_local
            else ["composition"],
            "candidate_worker_kinds": ["transport_researcher"]
            if candidate_local
            else [],
        }
    if category == "accommodation_preference":
        return {
            "enforcement_scope": ["candidate"],
            "candidate_worker_kinds": ["accommodation_researcher"],
        }
    if category in {"elderly_mobility", "health_condition", "pace_preference"}:
        return {"enforcement_scope": ["composition"], "candidate_worker_kinds": []}
    if category in {"child_friendly", "dietary_restriction", "destination_preference"}:
        return {
            "enforcement_scope": ["candidate"],
            "candidate_worker_kinds": ["destination_researcher"],
        }
    return {
        "enforcement_scope": [],
        "candidate_worker_kinds": [],
        "unsupported_hard_category": True,
    }


def _public_summary(category: str, value: str, params: Optional[Dict[str, Any]]) -> str:
    params = params or {}
    if category == "budget_cap":
        amount = _budget_amount_param(params.get("amount"))
        if amount is not None:
            label = (
                "总预算"
                if params.get("per") == "total"
                else "每晚预算"
                if params.get("per") == "night"
                else "每日预算"
            )
            return f"{label}不超过 {amount:.0f} {params.get('currency', 'CNY')}"
    if category == "transport_constraint":
        parts = []
        if params.get("avoid_overnight"):
            parts.append("不安排过夜交通")
        if params.get("earliest_departure_local"):
            parts.append(f"不早于 {params['earliest_departure_local']} 出发")
        if params.get("latest_arrival_local"):
            parts.append(f"不晚于 {params['latest_arrival_local']} 抵达")
        return "；".join(parts) or value
    if category == "accommodation_preference":
        labels = {"non_smoking": "禁烟", "private_bath": "独立卫浴", "elevator": "电梯"}
        facilities = [
            labels.get(str(item), str(item))
            for item in params.get("required_facilities") or []
        ]
        return "住宿必须提供" + "、".join(facilities) if facilities else value
    if category in {"elderly_mobility", "health_condition"}:
        parts = []
        if params.get("max_continuous_walk_minutes"):
            parts.append(f"连续步行不超过 {params['max_continuous_walk_minutes']} 分钟")
        if params.get("avoid_long_stairs"):
            parts.append("避免长楼梯")
        parts.append("优先电梯、无障碍路线与休息安排")
        return "；".join(dict.fromkeys(parts))
    return value


def _make_item(
    *,
    category: str,
    value: str,
    params: Optional[Dict[str, Any]],
    source: str,
    confidence: str,
    visibility: str,
    updated_at: str,
    origin_ref: Any,
) -> Dict[str, Any]:
    """装配 ConstraintItem，并按来源限制 hard 强度。"""
    params = _canonical_constraint_params(category, value, params)
    ctype = _default_type(category, value, source)

    if (
        ctype == "hard"
        and source not in _EXPLICIT_SOURCES
        and not (source == "memory_fact" and confidence == "high")
    ):
        ctype = "soft"
    policy = _enforcement_policy(category, params, ctype)
    return {
        "constraint_id": _cid(category, value, params, source, origin_ref),
        "category": category,
        "value": value,
        "params": params or None,
        "type": ctype,
        "priority": _priority_for(ctype, confidence),
        "source_refs": [
            {
                "source": source,
                "origin_ref": origin_ref,
                "confidence": confidence,
                "updated_at": updated_at,
            }
        ],
        "confidence": confidence,
        "updated_at": updated_at,
        "recency": 0.0,
        "public_summary": _public_summary(category, value, params),
        "visibility": visibility,
        "status": "active",
        "supersedes": None,
        **policy,
    }
