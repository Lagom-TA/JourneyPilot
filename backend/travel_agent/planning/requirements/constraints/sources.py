"""Planning requirements constraints sources."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from travel_agent.memory.preference_contracts import DIETARY_ALLERGY_OPTION
from travel_agent.planning.requirements.constraints.items import (
    _get,
    _iso,
    _make_item,
    _normalize_category,
    _now_iso,
)
from travel_agent.planning.requirements.constraints.parameters import (
    _ALLERGEN_DETAIL_UNKNOWN,
)


def _map_manual_profile(user_profile: Any, updated_at: str) -> List[Dict[str, Any]]:
    """将 TravelPreference 结构字段直接映射为约束，不调用模型。"""
    prefs = getattr(user_profile, "preferences", None)
    if prefs is None:
        return []
    items: List[Dict[str, Any]] = []

    for style in getattr(prefs, "travel_styles", None) or []:
        items.append(
            _make_item(
                category="other",
                value=f"旅行风格：{style}",
                params=None,
                source="manual_profile",
                confidence="high",
                visibility="user_visible",
                updated_at=updated_at,
                origin_ref="profile.travel_styles",
            )
        )

    for d in getattr(prefs, "dietary_restrictions", None) or []:
        if str(d) == DIETARY_ALLERGY_OPTION:
            items.append(
                _make_item(
                    category="food_allergy",
                    value=f"{DIETARY_ALLERGY_OPTION}（具体过敏原未知）",
                    params={"allergen_detail": _ALLERGEN_DETAIL_UNKNOWN},
                    source="manual_profile",
                    confidence="high",
                    visibility="user_visible",
                    updated_at=updated_at,
                    origin_ref="profile.dietary_restrictions",
                )
            )
            continue
        items.append(
            _make_item(
                category="dietary_restriction",
                value=str(d),
                params=None,
                source="manual_profile",
                confidence="high",
                visibility="user_visible",
                updated_at=updated_at,
                origin_ref="profile.dietary_restrictions",
            )
        )

    blvl = str(getattr(prefs, "typical_budget_level", "") or "").strip()
    if blvl:
        items.append(
            _make_item(
                category="budget_cap",
                value=f"预算档位：{blvl}",
                params=None,
                source="manual_profile",
                confidence="high",
                visibility="user_visible",
                updated_at=updated_at,
                origin_ref="profile.typical_budget_level",
            )
        )

    acc = str(getattr(prefs, "accommodation_type", "") or "").strip()
    if acc:
        items.append(
            _make_item(
                category="accommodation_preference",
                value=acc,
                params=None,
                source="manual_profile",
                confidence="high",
                visibility="user_visible",
                updated_at=updated_at,
                origin_ref="profile.accommodation_type",
            )
        )

    pace = str(getattr(prefs, "pace", "") or "").strip()
    if pace:
        items.append(
            _make_item(
                category="pace_preference",
                value=pace,
                params=None,
                source="manual_profile",
                confidence="high",
                visibility="user_visible",
                updated_at=updated_at,
                origin_ref="profile.pace",
            )
        )

    for t in getattr(prefs, "preferred_transport", None) or []:
        items.append(
            _make_item(
                category="transport_constraint",
                value=str(t),
                params=None,
                source="manual_profile",
                confidence="high",
                visibility="user_visible",
                updated_at=updated_at,
                origin_ref="profile.preferred_transport",
            )
        )

    return items


def _map_manual_memory_facts(
    manual_memory_facts: Any, updated_at: str
) -> List[Dict[str, Any]]:
    """manual_memory：用户在「个性记忆」里手写的每一条，**原文**直接映成一条 item。"""

    if not isinstance(manual_memory_facts, list):
        return []
    items: List[Dict[str, Any]] = []
    for fact in manual_memory_facts:
        if not isinstance(fact, dict):
            continue
        content = str(fact.get("content") or "").strip()
        if not content:
            continue
        fact_id = fact.get("fact_id")
        items.append(
            _make_item(
                category="other",
                value=content,
                params=None,
                source="manual_memory",
                confidence="high",
                visibility="user_visible",
                updated_at=_iso(fact.get("created_at")) or updated_at,
                origin_ref=f"memory_facts.{fact_id}"
                if fact_id is not None
                else "memory_facts",
            )
        )
    return items


def _map_preset_constraints(
    preset_pack_constraints: Any, updated_at: str
) -> List[Dict[str, Any]]:
    """preset：``category -> 原文`` 直接映射，无 LLM（与 manual_profile 同一形状）。"""

    if not isinstance(preset_pack_constraints, dict):
        return []
    items: List[Dict[str, Any]] = []
    for category, value in preset_pack_constraints.items():
        normalized_category = _normalize_category(category)
        text = str(value or "").strip()
        if not text:
            continue
        items.append(
            _make_item(
                category=normalized_category,
                value=text,
                params=None,
                source="preset",
                confidence="high",
                visibility="user_visible",
                updated_at=updated_at,
                origin_ref=f"preset.constraints.{normalized_category}",
            )
        )
    return items


def _auto_portrait_block(
    user_profile: Any, updated_at: str
) -> Optional[Dict[str, Any]]:
    """自动画像保持为单一内部参考块，不能提升为 hard。"""
    portrait = str(getattr(user_profile, "auto_portrait", "") or "").strip()
    if not portrait:
        return None
    return _make_item(
        category="other",
        value=portrait,
        params=None,
        source="auto_portrait",
        confidence="reference",
        visibility="internal_only",
        updated_at=updated_at,
        origin_ref="user_profiles.auto_portrait",
    )


def constraint_free_text_sources(
    state: Any,
    memory_facts: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    now = _now_iso()
    free_items: List[Dict[str, Any]] = []
    anchor = _get(state, "session_anchor") or {}
    if isinstance(anchor, dict):
        for index, value in enumerate(anchor.get("key_constraints") or []):
            free_items.append(
                {
                    "id": f"anchor_{index}",
                    "source": "session_anchor",
                    "text": str(value),
                    "updated_at": anchor.get("compressed_at") or now,
                }
            )
    user_query = str(_get(state, "user_query") or "").strip()
    if user_query:
        free_items.append(
            {
                "id": "query_main",
                "source": "current_query",
                "text": user_query,
                "updated_at": now,
            }
        )
    plan_amendment = _get(state, "plan_gate_amendment")
    if plan_amendment is not None:
        content = str(getattr(plan_amendment, "content", "") or "").strip()
        command_id = str(getattr(plan_amendment, "command_id", "plan_gate_amendment"))
        if content:
            free_items.append(
                {
                    "id": command_id,
                    "source": "plan_gate_amendment",
                    "text": content,
                    "updated_at": now,
                }
            )
    for amendment in _get(state, "pending_intent_amendments") or []:
        content = str(getattr(amendment, "content", "") or "").strip()
        command_id = str(getattr(amendment, "command_id", "") or "").strip()
        if content and command_id:
            free_items.append(
                {
                    "id": command_id,
                    "source": "run_supplement",
                    "text": content,
                    "updated_at": now,
                }
            )
    for index, fact in enumerate(memory_facts or []):
        if isinstance(fact, dict):
            free_items.append(
                {
                    "id": f"fact_{index}",
                    "source": "memory_fact",
                    "text": str(fact.get("content") or ""),
                    "updated_at": _iso(fact.get("created_at")) or now,
                    "category_meta": fact.get("category"),
                    "importance": int(fact.get("importance") or 0),
                }
            )
    return free_items
