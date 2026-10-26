from __future__ import annotations

from typing import Any, Dict

from travel_agent.llm.strict_json_schema import as_strict_schema
from travel_agent.planning.itinerary.draft import (
    _SERVER_OWNED_PLACE_FIELDS,
    ItineraryCompositionDraft,
)
from travel_agent.planning.itinerary.supply import selected_ids_by_kind
from travel_agent.planning.research.catalog import RecommendationCatalog

_AUTHORED_PLACE_DEFS = ("AuthoredVisitPlace", "AuthoredDiningPlace")


def _composition_response_schema(
    catalog: RecommendationCatalog | None = None,
    *,
    skeleton_only: bool = False,
    strict_wire: bool = True,
) -> Dict[str, Any]:
    """把每种落位分支绑定到同类型的已选候选。"""
    schema = ItineraryCompositionDraft.model_json_schema()
    definitions = schema.get("$defs", {})

    def remove_branch(value: Any, ref: str, mapping_key: str) -> None:
        if isinstance(value, dict):
            for key in ("oneOf", "anyOf", "allOf"):
                branches = value.get(key)
                if isinstance(branches, list):
                    value[key] = [
                        branch
                        for branch in branches
                        if not (isinstance(branch, dict) and branch.get("$ref") == ref)
                    ]
            discriminator = value.get("discriminator")
            if isinstance(discriminator, dict) and isinstance(
                discriminator.get("mapping"), dict
            ):
                discriminator["mapping"].pop(mapping_key, None)
            for child in value.values():
                remove_branch(child, ref, mapping_key)
        elif isinstance(value, list):
            for child in value:
                remove_branch(child, ref, mapping_key)

    # 地点 Provider 解析步骤负责全部 ``resolved_*`` 字段，模型不能填写。
    for def_name in _AUTHORED_PLACE_DEFS + ("AuthoredRoute",):
        authored_schema = definitions.get(def_name)
        if not isinstance(authored_schema, dict):
            continue
        properties = authored_schema.get("properties", {})
        for field_name in _SERVER_OWNED_PLACE_FIELDS:
            properties.pop(field_name, None)
        if strict_wire:
            authored_schema["required"] = list(properties)

    ids_by_kind = (
        selected_ids_by_kind(catalog, skeleton_only=skeleton_only)
        if catalog is not None
        else None
    )
    for model_name, candidate_kind in (
        ("VisitPlacement", "visit"),
        ("DiningPlacement", "dining"),
        ("TransportPlacement", "transport"),
    ):
        placement_schema = definitions.get(model_name)
        if not isinstance(placement_schema, dict):
            continue
        if model_name == "TransportPlacement":
            placement_schema.get("properties", {}).pop("connector_gap_id", None)
        properties = placement_schema.get("properties", {})
        if candidate_kind == "transport" and skeleton_only:
            # 骨架不包含任何市内接驳。
            properties.pop("authored_route", None)
        if ids_by_kind is not None:
            selected = ids_by_kind[candidate_kind]
            may_author = (
                "authored_place" in properties or "authored_route" in properties
            )
            if selected:
                properties["candidate_id"] = {
                    "anyOf": [
                        {"type": "string", "enum": selected},
                        {"type": "null"},
                    ]
                }
            elif may_author:
                properties["candidate_id"] = {"type": "null"}
            else:
                remove_branch(schema, f"#/$defs/{model_name}", candidate_kind)
                continue
        if strict_wire:
            placement_schema["required"] = list(properties)
        else:
            # 必须保留判别字段，但互斥的来源字段保持可选。
            required = set(placement_schema.get("required") or [])
            required.add("placement_kind")
            placement_schema["required"] = [
                field_name for field_name in properties if field_name in required
            ]

    if ids_by_kind is not None:
        lodging_ids = ids_by_kind["lodging"]
        schema["properties"]["lodging_candidate_ids"] = (
            {"type": "array", "items": {"type": "string", "enum": lodging_ids}}
            if lodging_ids
            else {"type": "array", "items": {"type": "string"}, "maxItems": 0}
        )
    # 严格 JSON Schema 需要合法化的联合类型；解析阶段仍校验判别字段。
    return as_strict_schema(schema) if strict_wire else schema
