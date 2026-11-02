"""约束组装。"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional

from travel_agent.planning.requirements.constraints.extraction import (
    _extract_free_text,
)
from travel_agent.planning.requirements.constraints.items import (
    _get,
    _make_item,
    _now_iso,
    _public_summary,
)
from travel_agent.planning.requirements.constraints.resolution import (
    _dedupe_constraints,
    _resolve_conflicts,
)
from travel_agent.planning.requirements.constraints.sources import (
    _auto_portrait_block,
    _map_manual_memory_facts,
    _map_manual_profile,
    _map_preset_constraints,
    constraint_free_text_sources,
)

logger = logging.getLogger(__name__)


_MAX_EXTRACTED_CONSTRAINT_CHARS = 60


async def build_constraint_pack(
    state: Any,
    fast_llm: Any,
    *,
    user_profile: Any = None,
    manual_memory_facts: Optional[List[Dict[str, Any]]] = None,
    manual_memory_truncated: bool = False,
    memory_facts: Optional[List[Dict[str, Any]]] = None,
    context_status: str = "unknown",
    missing_source_layers: Optional[List[str]] = None,
    partial_reasons: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """组装完整的个人约束包，供快问快答消费；规划只映射长期记忆和 preset。"""
    run_id = _get(state, "run_id") or ""
    now = _now_iso()
    constraints: List[Dict[str, Any]] = []
    source_layers: List[str] = []

    if user_profile is not None:
        mapped = _map_manual_profile(user_profile, now)
        if mapped:
            constraints.extend(mapped)
            source_layers.append("manual_profile")
        portrait = _auto_portrait_block(user_profile, now)
        if portrait is not None:
            constraints.append(portrait)
            source_layers.append("auto_portrait")

    manual_memory_items = _map_manual_memory_facts(manual_memory_facts, now)
    if manual_memory_items:
        constraints.extend(manual_memory_items)
        source_layers.append("manual_memory")

    preset_items = _map_preset_constraints(_get(state, "preset_pack_constraints"), now)
    if preset_items:
        constraints.extend(preset_items)
        source_layers.append("preset")

    free_items = constraint_free_text_sources(state, memory_facts)
    extraction = await _extract_free_text(fast_llm, free_items)
    seen_sources: set = set()
    for it in free_items:
        extracted = extraction.items_for(it["id"])
        if not extracted:
            continue
        source = it["source"]
        if source == "memory_fact":
            high = (
                it.get("category_meta") == "constraint" and it.get("importance", 0) >= 8
            )
            confidence = "high" if high else "medium"
            visibility = "user_visible" if high else "internal_only"
        else:
            confidence = "high"
            visibility = "user_visible"
        source_text = str(it.get("text") or "").strip()
        for ex in extracted:
            value = str(ex["value"] or "").strip()

            if (
                source_text
                and value == source_text
                and len(source_text) > _MAX_EXTRACTED_CONSTRAINT_CHARS
                and _public_summary(ex["category"], value, ex["params"]) == source_text
            ):
                logger.info(
                    "Constraint extraction returned its own input verbatim and it would "
                    "reach the screen, dropped | source=%s origin=%s category=%s chars=%d",
                    source,
                    it["id"],
                    ex["category"],
                    len(source_text),
                )
                continue
            constraints.append(
                _make_item(
                    category=ex["category"],
                    value=ex["value"],
                    params=ex["params"],
                    source=source,
                    confidence=confidence,
                    visibility=visibility,
                    updated_at=it["updated_at"],
                    origin_ref=it["id"],
                )
            )
        seen_sources.add(source)
    for s in seen_sources:
        if s not in source_layers:
            source_layers.append(s)

    # A later model response omitting a previously active constraint is not a
    # user-authorized revocation. Retain it until an explicit lifecycle decision.
    previous_pack = _get(state, "constraint_pack") or {}
    if isinstance(previous_pack, dict):
        for previous in previous_pack.get("constraints") or []:
            if not isinstance(previous, dict) or previous.get("status") not in (None, "active"):
                continue
            constraints.append(deepcopy(previous))
            for ref in previous.get("source_refs") or []:
                source = str(ref.get("source") or "") if isinstance(ref, dict) else ""
                if source and source not in source_layers:
                    source_layers.append(source)

    source_ids = list(dict.fromkeys([
        "query_main",
        *(str(item.get("id") or "") for item in free_items
          if item.get("source") in {"plan_gate_amendment", "run_supplement"}),
    ]))
    source_order = {source_id: index for index, source_id in enumerate(source_ids) if source_id}
    constraints = _resolve_conflicts(_dedupe_constraints(constraints), source_order=source_order)
    active = [c for c in constraints if c["status"] == "active"]
    free_text_sources_total = len(
        [it for it in free_items if str(it.get("text") or "").strip()]
    )
    extraction_status = {
        "free_text_sources_total": free_text_sources_total,
        "llm_extracted": extraction.llm_extracted,
        "fallback_extracted": extraction.fallback_extracted,
        "missing_sources": list(extraction.missing_sources),
        "partial_reasons": list(
            dict.fromkeys((partial_reasons or []) + extraction.partial_reasons)
        ),
    }

    return {
        "pack_meta": {
            "run_id": run_id,
            "user_id": _get(state, "user_id") or "",
            "session_id": _get(state, "session_id") or "",
            "built_at": now,
            "source_layers": source_layers,
            "constraint_context_status": context_status,
            "missing_source_layers": list(missing_source_layers or []),
            "manual_memory_truncated": bool(manual_memory_truncated),
            "extraction_status": extraction_status,
        },
        "constraints": constraints,
        "hard_constraints": [c for c in active if c["type"] == "hard"],
        "soft_preferences": [c for c in active if c["type"] == "soft"],
    }
