"""约束来源。"""

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
    seen_source_ids = {str(item.get("id") or "") for item in free_items}
    for amendment in _get(state, "unresolved_intent_amendments") or []:
        content = str(getattr(amendment, "content", "") or "").strip()
        command_id = str(getattr(amendment, "command_id", "") or "").strip()
        if content and command_id and command_id not in seen_source_ids:
            free_items.append({
                "id": command_id, "source": amendment.source_kind, "text": content, "updated_at": now,
            })
            seen_source_ids.add(command_id)

    # Checkpoints retain ledger clauses even after an amendment is resolved.
    # The constraint pack is rebuilt every revision, so replay each prior user
    # amendment in full rather than losing its already accepted constraints.
    contract = _get(state, "request_contract") or _get(state, "request_contract_candidate")
    intent_spec = getattr(contract, "intent_spec", None)
    command_ids = set(getattr(intent_spec, "generated_from_command_ids", None) or [])
    ledger = list(getattr(contract, "clause_ledger", None) or [])
    recovered: Dict[str, List[Any]] = {}
    for clause in ledger:
        ref = str(getattr(clause, "source_ref_id", "") or "")
        if ref in command_ids and ref not in seen_source_ids:
            recovered.setdefault(ref, []).append(clause)
    for command_id, records in recovered.items():
        source = (
            "plan_gate_amendment"
            if command_id.startswith(("plan_gate_", "clarification_"))
            else "run_supplement"
        )
        free_items.append({
            "id": command_id, "source": source,
            "text": "；".join(item.source_text for item in records),
            "updated_at": now,
            "replayed_clauses": [(item.clause_id, item.source_text) for item in records],
        })
        seen_source_ids.add(command_id)
    for index, fact in enumerate(memory_facts or []):
        if isinstance(fact, dict) and fact.get("category") in {"preference", "constraint"}:
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


def structured_constraint_context(
    state: Any,
    *,
    user_profile: Any = None,
    manual_memory_facts: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """给同一次需求归一化调用提供已成立的约束，而不是只给自由文本。

    既有的 Constraint Pack 可能来自上一次归一化；用户画像、手写记忆和 preset
    则还没有进入 Pack。这里只做确定性映射与去重，不调用模型。
    """

    rows: List[Dict[str, Any]] = []
    now = _now_iso()
    if user_profile is not None:
        rows.extend(_map_manual_profile(user_profile, now))
    rows.extend(_map_manual_memory_facts(manual_memory_facts, now))
    rows.extend(_map_preset_constraints(_get(state, "preset_pack_constraints"), now))
    pack = _get(state, "constraint_pack") or {}
    if isinstance(pack, dict):
        for item in pack.get("constraints") or []:
            if (
                isinstance(item, dict)
                and item.get("status") in (None, "active")
                and item.get("visibility") != "internal_only"
            ):
                rows.append(item)

    compact: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "other")
        value = " ".join(str(item.get("value") or "").split())[:300]
        if not value:
            continue
        key = (category, value.casefold())
        if key in seen:
            continue
        seen.add(key)
        row: Dict[str, Any] = {"category": category, "value": value}
        params = item.get("params")
        if isinstance(params, dict) and params:
            row["params"] = params
        summary = " ".join(str(item.get("public_summary") or "").split())[:300]
        if summary:
            row["public_summary"] = summary
        ctype = str(item.get("type") or "").strip()
        if ctype:
            row["type"] = ctype
        source = str(item.get("source") or "").strip()
        if source:
            row["source"] = source
        compact.append(row)
        if len(compact) >= 40:
            break
    return compact
