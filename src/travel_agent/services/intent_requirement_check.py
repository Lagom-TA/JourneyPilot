from __future__ import annotations

import json
import logging
import re

from ..entities.candidate_intent import IntentMatchStatus
from ..entities.intent_check import EntityIntentCheck, IntentCheckObject
from ..entities.intent_spec import CategoryIntentValue, ScalarIntentValue, IntentKind, canonical_json_hash

logger = logging.getLogger(__name__)

_ATTRIBUTE_FIELDS = (
    "provider_place_type", "visit_type", "cuisine_types", "recommended_dishes",
    "meal_type", "selected_mode", "transport_class", "room_type",
    "reservation_required", "opening_window", "address",
)


def check_attributes(entity) -> dict:
    return {field: getattr(entity, field) for field in _ATTRIBUTE_FIELDS
            if getattr(entity, field, None) is not None}


def explicit_category_match(name: str, attributes: dict, intent) -> bool | None:
    if isinstance(intent.value, CategoryIntentValue):
        categories = intent.value.categories
    elif isinstance(intent.value, ScalarIntentValue):
        categories = [intent.value.value]
    else:
        return None
    if name.casefold().strip() in {category.casefold().strip() for category in categories}:
        return True
    aliases = {
        "博物馆": "museum", "博物院": "museum", "museums": "museum",
        "公园": "park", "parks": "park", "海鲜": "seafood",
    }
    categories = [re.sub(r"^(?:不要|不去|避开|禁止|排除|avoid\s+|no\s+)", "",
                         category.casefold().strip()).strip() for category in categories]
    terms = {aliases.get(term, term) for term in categories}
    values = {str(value).casefold().strip()
              for key, raw in attributes.items()
              if key in {"provider_place_type", "visit_type", "cuisine_types", "selected_mode"}
              for value in (raw if isinstance(raw, list) else [raw])}
    values = {aliases.get(value, value) for value in values}
    if terms & values:
        return True
    # Classifications from a place name are planning judgments, not provider facts.
    if not re.search(r"不|无|非|not\b|without\b|no\b", name, re.I):
        name_class = None
        if re.search(r"(?:博物馆|博物院|\bmuseum)\s*$", name, re.I):
            name_class = "museum"
        elif re.search(r"(?:公园|\bpark)\s*$", name, re.I):
            name_class = "park"
        if name_class in terms:
            return True
        if name_class is not None and terms <= {"museum", "park"}:
            return False
    if values & {"museum", "park"} and terms <= {"museum", "park"}:
        return False
    return None


def requirement_check_objects(workspace) -> list[IntentCheckObject]:
    catalog = workspace.recommendation_catalog
    candidate_index = catalog.candidate_index()
    fact_index = {fact.fact_assertion_id: fact for packet in catalog.research_packets
                  for fact in packet.fact_assertions if fact.status == "verified"}
    objects = []
    for kind, entities in (
        ("visit", workspace.itinerary.visit_stops),
        ("dining", workspace.itinerary.dining_stops),
        ("lodging", workspace.itinerary.lodging_stays),
        ("transport", workspace.itinerary.transport_legs),
    ):
        for entity in entities:
            candidate = candidate_index.get(entity.lineage.candidate_id)
            attributes = check_attributes(candidate) if candidate is not None else {}
            attributes.update(check_attributes(entity))
            place_id = getattr(entity, "place_id", None)
            fact_ids = set(entity.lineage.fact_assertion_ids)
            if place_id:
                for related in candidate_index.values():
                    if related.candidate_kind == kind and getattr(related, "place_id", None) == place_id:
                        fact_ids.update(related.fact_assertion_ids)
            objects.append(IntentCheckObject(
                entity_id=getattr(entity, "item_id", None) or getattr(entity, "stay_id", None)
                          or entity.transport_leg_id,
                kind=kind, transport_class=getattr(entity, "transport_class", None),
                candidate_id=entity.lineage.candidate_id,
                place_id=place_id,
                name=(getattr(entity, "name", None) or getattr(entity, "transport_leg_id", "")),
                attributes=attributes,
                facts=[{"fact_assertion_id": fact_id,
                        "field_path": fact_index[fact_id].field_path,
                        "asserted_value": fact_index[fact_id].asserted_value}
                       for fact_id in sorted(fact_ids) if fact_id in fact_index],
            ))
    return objects


def _target(obj):
    if obj.kind == "transport":
        return "long_distance_transport" if obj.transport_class == "long_distance" else "local_transport"
    return obj.kind


def _current_category_match(obj, intent) -> tuple[bool | None, list[str]]:
    decisions = {explicit_category_match(obj.name, obj.attributes, intent)} - {None}
    fact_ids = []
    for fact in obj.facts:
        field = fact["field_path"]
        value = fact["asserted_value"]
        if field in {"name", "branch_name", "property_name"} and isinstance(value, str):
            present = explicit_category_match(value, {}, intent)
        elif field in _ATTRIBUTE_FIELDS:
            present = explicit_category_match("", {field: value}, intent)
        else:
            continue
        if present is not None:
            decisions.add(present)
            fact_ids.append(fact["fact_assertion_id"])
    if len(decisions) != 1:
        return None, []
    return decisions.pop(), sorted(set(fact_ids))


def check_final_entities(workspace, intent_spec) -> list[EntityIntentCheck]:
    saved = {(check.entity_id, check.intent_id, check.input_hash): check
             for check in workspace.entity_intent_checks}
    results = []
    for obj in requirement_check_objects(workspace):
        for intent in intent_spec.active_items:
            if intent.kind is not IntentKind.MUST_EXCLUDE:
                continue
            input_hash = canonical_json_hash({
                "object": obj.model_dump(mode="json"),
                "intent": {key: getattr(intent, key) for key in (
                    "intent_id", "kind", "target", "value", "verification_mode", "public_summary")},
            })
            status = IntentMatchStatus.UNKNOWN
            basis = "unverified"
            reason = "没有足够的实体属性判断禁令"
            fact_ids = []
            if intent.target.value not in {_target(obj), "trip", "itinerary"}:
                status = IntentMatchStatus.NOT_APPLICABLE
                reason = "要求不适用于此实体类型"
            else:
                present, fact_ids = _current_category_match(obj, intent)
                if present is not None:
                    status = IntentMatchStatus.VIOLATED if present else IntentMatchStatus.NOT_MATCHED
                    basis = "planning_judgment"
                    reason = "依据当前实体的名称、明确类别和地点事实判断"
                elif (obj.entity_id, intent.intent_id, input_hash) in saved:
                    results.append(saved[(obj.entity_id, intent.intent_id, input_hash)])
                    continue
            results.append(EntityIntentCheck(
                entity_id=obj.entity_id, intent_id=intent.intent_id, input_hash=input_hash,
                status=status, evidence_basis=basis, reason=reason,
                supporting_fact_assertion_ids=fact_ids,
            ))
    return results


async def evaluate_final_entities(workspace, intent_spec, llm):
    checks = check_final_entities(workspace, intent_spec)
    unresolved = {(check.entity_id, check.intent_id): check for check in checks
                  if check.status is IntentMatchStatus.UNKNOWN}
    if not unresolved or llm is None:
        return checks
    objects = {obj.entity_id: obj for obj in requirement_check_objects(workspace)}
    intents = {intent.intent_id: intent for intent in intent_spec.active_items}
    batch = list(unresolved)[:128]
    payload = [{"entity": objects[entity_id].model_dump(mode="json"),
                "intent": {"intent_id": intent_id, "kind": intents[intent_id].kind.value,
                           "value": intents[intent_id].value.model_dump(mode="json"),
                           "summary": intents[intent_id].public_summary}}
               for entity_id, intent_id in batch]
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"checks": {"type": "array", "maxItems": len(batch), "items": {
                  "type": "object", "additionalProperties": False,
                  "properties": {"entity_id": {"type": "string"}, "intent_id": {"type": "string"},
                                 "status": {"type": "string", "enum": ["violated", "not_matched", "unknown"]},
                                 "reason": {"type": "string"}},
                  "required": ["entity_id", "intent_id", "status", "reason"]}}},
              "required": ["checks"]}
    try:
        response = await llm.ainvoke([
            {"role": "system", "content": (
                "批量检查最终实体是否违反用户禁令。只依据给定名称、结构化属性和事实，"
                "不补造事实。名称分类属于planning_judgment。缺乏判断依据必须unknown，"
                "不含海鲜等负向描述不是含海鲜的证据。逐对返回violated/not_matched/unknown。")},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            response_format={"type": "json_schema", "json_schema": {
                "name": "final_entity_intent_check", "strict": True, "schema": schema}}, temperature=0)
        parsed = json.loads(response.content if hasattr(response, "content") else response)
        rows = parsed["checks"]
        seen = set()
        duplicate = set()
        resolved = {}
        for row in rows:
            pair = (row["entity_id"], row["intent_id"])
            if pair not in batch:
                continue
            if pair in seen:
                duplicate.add(pair)
            seen.add(pair)
            status = IntentMatchStatus(row["status"])
            if status not in {IntentMatchStatus.VIOLATED, IntentMatchStatus.NOT_MATCHED, IntentMatchStatus.UNKNOWN}:
                continue
            resolved[pair] = EntityIntentCheck.model_validate({
                **unresolved[pair].model_dump(), "status": status, "reason": row["reason"],
                "evidence_basis": "unverified" if status is IntentMatchStatus.UNKNOWN else "planning_judgment"})
        return [resolved.get((check.entity_id, check.intent_id), check)
                if (check.entity_id, check.intent_id) not in duplicate else check for check in checks]
    except Exception as exc:
        logger.warning("final entity intent batch failed: %s: %s", type(exc).__name__, exc)
        return checks
