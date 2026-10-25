"""Research packet route selection responsibilities."""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping, Sequence

from travel_agent.entities.provider_evidence import ProviderEvidenceScope
from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.planning.research.evidence import (
    FactAssertion,
    FactSourceLink,
    FieldProvenance,
    SourceRecord,
)
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.runtime.operations import ModelWindowClosed

from .choices import (
    _default_provider_route_selection,
    _provider_route_constraint_evaluation,
    _provider_route_selection_limit,
    _provider_route_selections_or_default,
)
from .identifiers import (
    _canonical_snapshot_hash,
    _provider_candidate_id,
    _provider_fact_id,
    _provider_route_source_id,
)
from .model_calls import _bounded_packet_model_call
from .parsing import parse_research_packet_output
from .policy import ResearchPacketOutputError
from .schemas import _provider_route_selection_response_schema
from .sources import _provider_snapshot_source_fields
from .transcript import _parse_tool_envelope, _successful_route_records

logger = logging.getLogger(__name__)


async def _repair_from_provider_route_selection(
    *,
    base_payload: Mapping[str, Any],
    expected_run_id: str,
    llm: Any,
    context_messages: Sequence[Mapping[str, Any]],
    evidence_messages: Sequence[Mapping[str, Any]],
    eligible_route_options: Sequence[Mapping[str, Any]],
    destination_ids: Sequence[str],
    required_transport_classes: Sequence[str] | None,
    excluded_candidate_ids: Sequence[str] | None,
    require_current_candidate: bool,
    authoritative_packet_metadata: Mapping[str, Any] | None,
    expected_active_constraints: Sequence[Mapping[str, Any]] | None,
    required_route_scopes: Sequence[ProviderEvidenceScope],
) -> ResearchPacket:
    "Select route ids once, then materialize the complete Provider closure."
    maximum_selections = _provider_route_selection_limit(
        eligible_route_options,
        required_transport_classes=required_transport_classes,
    )
    model_authored = False
    # Retain local pair/mode measurements for the composer's later comparison.
    if eligible_route_options and all(
        option.get("transport_class") != "long_distance"
        for option in eligible_route_options
    ):
        selection_payload = _default_provider_route_selection(
            eligible_route_options,
            destination_ids,
            selection_limit=maximum_selections,
        )
    elif (
        required_transport_classes
        and len(eligible_route_options) == 1
        and len(destination_ids) == 1
    ):
        option = eligible_route_options[0]
        transport_class = str(option["transport_class"])
        selected_mode = str(option["selected_mode"])
        is_exposed_flexible = transport_class == "flexible" and selected_mode in {
            "walk",
            "bike",
        }
        selection_payload = {
            "selections": [
                {
                    "route_id": option["route_id"],
                    "destination_id": destination_ids[0],
                    "selection_reasons": [
                        "路线端点均绑定已准入实体",
                        f"满足 {transport_class} 交通类别",
                    ],
                    "tradeoff": "当前作用域仅有这一条完整的 Provider 可执行路线",
                    "booking_status": (
                        "recommended"
                        if transport_class == "long_distance"
                        else "not_required"
                    ),
                    "weather_sensitivity": {
                        "exposure": "outdoor" if is_exposed_flexible else "mixed",
                        "rain_sensitivity": "high" if is_exposed_flexible else "low",
                        "heat_sensitivity": "high" if is_exposed_flexible else "low",
                        "cold_sensitivity": "low",
                        "wind_sensitivity": "high" if is_exposed_flexible else "low",
                        "requires_clear_visibility": False,
                    },
                }
            ]
        }
    else:
        selection_schema = _provider_route_selection_response_schema(
            eligible_route_options,
            destination_ids,
            maximum_selections=maximum_selections,
        )
        selection_messages = [
            dict(message)
            for message in context_messages
            if message.get("role") == "system"
        ]
        selection_messages.append(
            {
                "role": "user",
                "content": (
                    "你现在只做一次强类型交通方案选择，不复制路线字段、segments、SourceRecord、"
                    "FactAssertion 或 provenance。从 eligible_route_options 中根据当前任务、端点、"
                    f"天气和规划质量选择 1 至 {maximum_selections} 条真实路线；"
                    "每个 exact Provider scope 最多一条；route_id 必须逐字来自 option，"
                    "禁止按 Provider 排名自动入选。只填写选择理由、真实取舍、预订状态、天气敏感度和"
                    "受控 destination_id；不要新增现实事实。只输出一个可由 json.loads 解析的 JSON 对象。"
                    f"run_id={expected_run_id}，"
                    f"query_context={json.dumps(base_payload.get('query_context') or {}, ensure_ascii=False, separators=(',', ':'))}，"
                    f"eligible_route_options={json.dumps(eligible_route_options, ensure_ascii=False, separators=(',', ':'))}。"
                    f"必须满足此 JSON Schema：{json.dumps(selection_schema, ensure_ascii=False, separators=(',', ':'))}"
                ),
            }
        )
        model_authored = True
        try:
            selected_raw = await _bounded_packet_model_call(
                llm,
                selection_messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "provider_route_selection",
                        "strict": True,
                        "schema": selection_schema,
                    },
                },
                temperature=0,
            )
            selection_payload = json.loads(selected_raw)
        except (
            ResearchPacketOutputError,
            TypeError,
            json.JSONDecodeError,
            ModelWindowClosed,
        ):
            logger.warning(
                "provider route planning selection unavailable; applying deterministic policy",
                exc_info=True,
            )
            selection_payload = _default_provider_route_selection(
                eligible_route_options,
                destination_ids,
                selection_limit=maximum_selections,
            )
            model_authored = False
    selections = _provider_route_selections_or_default(
        selection_payload,
        model_authored=model_authored,
        eligible_route_options=eligible_route_options,
        destination_ids=destination_ids,
        maximum_selections=maximum_selections,
    )
    option_by_id = {
        str(option["route_id"]): option for option in eligible_route_options
    }
    records = _successful_route_records(evidence_messages)
    generated_at = base_payload.get("generated_at")
    sources: dict[str, dict[str, Any]] = {}
    facts: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for selection in selections:
        route_id = str(selection["route_id"])
        envelope, route, route_index = records[route_id]
        audit_id = str(envelope["audit_id"])
        candidate_id = _provider_candidate_id("transport", route_id)
        source_id = _provider_route_source_id(audit_id, route_id)
        result = envelope.get("sanitized_result") or {}
        (
            snapshot,
            cache_provenance,
            observed_at,
            retrieved_at,
            provider_valid_until,
        ) = _provider_snapshot_source_fields(
            envelope,
            fallback_observed_at=generated_at,
        )
        provider_name = str(
            result.get("provider")
            or envelope.get("server_name")
            or "global_route_search"
        )
        sources[source_id] = {
            "source_record_id": source_id,
            "source_kind": "external_tool",
            "title": f"{provider_name} route: {route_id}",
            "provider_name": provider_name,
            "public_excerpt": (
                f"{route['from_endpoint']['name']} → {route['to_endpoint']['name']} · "
                f"{route['duration_minutes']} min"
            )[:900],
            "retrieved_at": retrieved_at,
            "observed_at": observed_at,
            "provider_valid_until": provider_valid_until,
            "content_hash": (
                cache_provenance.content_hash
                if cache_provenance is not None
                else _canonical_snapshot_hash(snapshot)
            ),
            "snapshot": snapshot,
            "lifecycle_status": "active",
            "tool_audit_id": audit_id,
            "cache_provenance": (
                cache_provenance.model_dump(mode="json")
                if cache_provenance is not None
                else None
            ),
        }
        provider_fields = [
            "route_id",
            "transport_class",
            "selected_mode",
            "from_endpoint",
            "to_endpoint",
            "departure_at",
            "arrival_at",
            "duration_minutes",
            "distance_meters",
            "total_cost_cny",
            "segments",
        ]
        fact_ids: list[str] = []
        field_paths: list[str] = []
        entity_ref = EntityRef(
            entity_type=EntityType.TRANSPORT_LEG,
            entity_id=candidate_id,
        )
        for field_path in provider_fields:
            asserted_value = route.get(field_path)
            if asserted_value is None:
                continue
            fact_id = _provider_fact_id(audit_id, candidate_id, field_path)
            fact_ids.append(fact_id)
            field_paths.append(field_path)
            facts.append(
                FactAssertion(
                    fact_assertion_id=fact_id,
                    entity_ref=entity_ref,
                    field_path=field_path,
                    asserted_value=asserted_value,
                    criticality="execution_critical",
                    status="verified",
                    observed_at=observed_at,
                    source_links=[
                        FactSourceLink(
                            source_record_id=source_id,
                            relation="supports",
                            source_locator=(
                                f"routes[{route_index}].{field_path}"
                                if cache_provenance is not None
                                else f"sanitized_result.routes[{route_index}].{field_path}"
                            ),
                        )
                    ],
                ).model_dump(mode="python")
            )
            provenance.append(
                FieldProvenance(
                    origin="external_fact",
                    entity_ref=entity_ref,
                    field_path=field_path,
                    reference_ids=[fact_id],
                ).model_dump(mode="python")
            )
        fact_ids_by_field = dict(zip(field_paths, fact_ids))
        evaluations = [
            _provider_route_constraint_evaluation(
                constraint,
                route,
                fact_ids_by_field,
            )
            for constraint in expected_active_constraints or ()
        ]
        active_constraint_ids = [
            str(constraint["constraint_id"])
            for constraint in expected_active_constraints or ()
        ]
        candidates.append(
            {
                "candidate_id": candidate_id,
                "research_packet_id": base_payload["research_packet_id"],
                "destination_id": selection["destination_id"],
                "fact_assertion_ids": fact_ids,
                "source_record_ids": [source_id],
                "field_paths": field_paths,
                "active_constraint_ids": active_constraint_ids,
                "constraint_evaluations": evaluations,
                "weather_sensitivity": selection["weather_sensitivity"],
                "selection_reasons": selection["selection_reasons"],
                "tradeoff": selection["tradeoff"],
                "planning_decision_ids": [],
                "weather_impact_ids": [],
                "personalization_influence_ids": [],
                "freshness_status": "current",
                "observed_at": observed_at,
                "candidate_kind": "transport",
                "route_id": route_id,
                "transport_class": route["transport_class"],
                "provider_evidence_scope_id": option_by_id[route_id].get(
                    "provider_evidence_scope_id"
                ),
                "selected_mode": route["selected_mode"],
                "from_endpoint": route["from_endpoint"],
                "to_endpoint": route["to_endpoint"],
                "departure_at": route.get("departure_at"),
                "arrival_at": route.get("arrival_at"),
                "duration_minutes": route["duration_minutes"],
                "distance_meters": route.get("distance_meters"),
                "total_cost_cny": route.get("total_cost_cny"),
                "segments": route["segments"],
                "booking_status": selection["booking_status"],
            }
        )
    repaired_payload = {
        **base_payload,
        "candidates": candidates,
        "source_records": list(sources.values()),
        "fact_assertions": facts,
        "field_provenance": provenance,
    }
    return parse_research_packet_output(
        json.dumps(repaired_payload, ensure_ascii=False, default=str),
        expected_worker="transport_researcher",
        expected_run_id=expected_run_id,
        required_transport_classes=required_transport_classes,
        excluded_candidate_ids=excluded_candidate_ids,
        require_current_candidate=require_current_candidate,
        expected_active_constraint_ids=tuple(
            str(constraint["constraint_id"])
            for constraint in expected_active_constraints or ()
        ),
        context_messages=context_messages,
        authoritative_tool_results=[
            envelope
            for message in evidence_messages
            if (envelope := _parse_tool_envelope(message)) is not None
        ],
        authoritative_packet_metadata=authoritative_packet_metadata,
        authoritative_source_records=[
            SourceRecord.model_validate(source) for source in sources.values()
        ],
        required_route_scopes=required_route_scopes,
        server_composed_candidate_limit=maximum_selections,
    )
