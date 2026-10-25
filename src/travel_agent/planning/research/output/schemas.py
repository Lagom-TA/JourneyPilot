"""Research packet schemas responsibilities."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from travel_agent.entities.provider_evidence import ProviderEvidenceScope
from travel_agent.llm.strict_json_schema import as_strict_schema
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.weather.models import WeatherSensitivity

from .options import _has_eligible_place_selection
from .policy import (
    _DESTINATION_IDENTITY_FACTS_PER_CANDIDATE,
    _WORKER_CANDIDATE_MODELS,
    ResearchPacketOutputError,
    ResearchWorkerKind,
    packet_candidate_limit,
)


def _drop_fields_the_model_must_not_author(schema: dict[str, Any]) -> None:
    "Remove server-owned fields from the model output contract."
    properties = schema.get("properties")
    server_fields = {
        "query_context",
        "intent_spec_revision",
        "research_query_plan_id",
        "executed_query_ids",
        "candidate_discovery_records",
    }
    if isinstance(properties, dict):
        for field_name in server_fields:
            properties.pop(field_name, None)
        required = schema.get("required")
        if isinstance(required, list):
            schema["required"] = [
                name for name in required if name not in server_fields
            ]
    definitions = schema.get("$defs", {})
    for definition_name, field_name in (
        ("LodgingCandidate", "anchor_travel_minutes"),
        ("SourceRecord", "snapshot"),
        ("RetrievedSourceRecord", "snapshot"),
        ("ExternalToolSourceRecord", "snapshot"),
    ):
        definition = definitions.get(definition_name)
        if not isinstance(definition, dict):
            continue
        definition_properties = definition.get("properties")
        if isinstance(definition_properties, dict):
            definition_properties.pop(field_name, None)
        required = definition.get("required")
        if isinstance(required, list):
            definition["required"] = [name for name in required if name != field_name]


_PROVIDER_SELECTION_SERVER_FIELDS = {
    "candidate_id",
    "research_packet_id",
    "fact_assertion_ids",
    "source_record_ids",
    "field_paths",
    "active_constraint_ids",
    "constraint_evaluations",
    "constraint_gate_attestation",
    "freshness_status",
    "observed_at",
    "expires_at",
    "provider_place_type",
    "provider_country_code",
    "name",
    "branch_name",
    "property_name",
    "address",
    "opening_window",
    "reservation_required",
}


def _bind_external_tool_source_registry(
    schema: dict[str, Any],
    authoritative_external_tool_source_ids: Sequence[str],
) -> None:
    "Pin ``external_tool`` source ids to the registry the parser will accept."
    definitions = schema["$defs"]
    base = definitions.pop("SourceRecord")
    definitions["RetrievedSourceRecord"] = {
        **base,
        "title": "Retrieved Source Record",
        "properties": {
            **base["properties"],
            "source_kind": {
                "enum": ["external_web", "rag_chunk"],
                "title": "Source Kind",
                "type": "string",
            },
        },
    }
    registry_ids = list(dict.fromkeys(authoritative_external_tool_source_ids))
    if not registry_ids:
        schema["properties"]["source_records"]["items"] = {
            "$ref": "#/$defs/RetrievedSourceRecord"
        }
        return
    definitions["ExternalToolSourceRecord"] = {
        **base,
        "title": "External Tool Source Record",
        "properties": {
            **base["properties"],
            "source_kind": {
                "const": "external_tool",
                "title": "Source Kind",
                "type": "string",
            },
            "source_record_id": {
                "enum": registry_ids,
                "title": "Source Record Id",
                "type": "string",
            },
        },
    }
    schema["properties"]["source_records"]["items"] = {
        "oneOf": [
            {"$ref": "#/$defs/ExternalToolSourceRecord"},
            {"$ref": "#/$defs/RetrievedSourceRecord"},
        ]
    }


def _research_packet_response_schema(
    expected_worker: ResearchWorkerKind,
    required_transport_classes: Sequence[str] | None = None,
    expected_active_constraint_ids: Sequence[str] | None = None,
    eligible_place_options: Mapping[
        str,
        Sequence[Mapping[str, str]],
    ]
    | None = None,
    required_candidate_kinds: Sequence[str] | None = None,
    required_route_scopes: Sequence[ProviderEvidenceScope] = (),
    authoritative_external_tool_source_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    "Require discriminators that Pydantic defaults omit from ``required``."
    schema = ResearchPacket.model_json_schema()
    definitions = schema.get("$defs", {})
    for model_name in (
        "VisitCandidate",
        "DiningCandidate",
        "LodgingCandidate",
        "TransportCandidate",
    ):
        candidate_schema = definitions.get(model_name)
        if not isinstance(candidate_schema, dict):
            continue
        required = candidate_schema.setdefault("required", [])
        if "candidate_kind" not in required:
            required.append("candidate_kind")
    allowed = _WORKER_CANDIDATE_MODELS[expected_worker]
    if required_candidate_kinds:
        required_kinds = set(required_candidate_kinds)
        allowed = tuple(
            (candidate_kind, model_name)
            for candidate_kind, model_name in allowed
            if candidate_kind in required_kinds
        )
    if eligible_place_options is not None and _has_eligible_place_selection(
        eligible_place_options
    ):
        allowed = tuple(
            (candidate_kind, model_name)
            for candidate_kind, model_name in allowed
            if eligible_place_options.get(candidate_kind)
        )
        schema["properties"]["candidates"]["minItems"] = 1
        for candidate_kind, model_name in allowed:
            definitions[model_name]["properties"]["place_id"] = {
                "enum": [
                    option["place_id"]
                    for option in eligible_place_options[candidate_kind]
                ],
                "title": "Place Id",
                "type": "string",
            }
    candidate_items = schema["properties"]["candidates"]["items"]
    scoped_transport = expected_worker == "transport_researcher" and bool(
        required_transport_classes
    )
    destination_repair = expected_worker == "destination_researcher"
    candidate_limit = packet_candidate_limit(
        expected_worker,
        required_transport_classes=required_transport_classes,
        required_route_scopes=required_route_scopes,
    )
    schema["properties"]["candidates"]["maxItems"] = candidate_limit
    if scoped_transport:
        schema["properties"]["fact_assertions"]["maxItems"] = 12
        schema["properties"]["field_provenance"]["maxItems"] = 12
    elif destination_repair:
        identity_fact_limit = (
            candidate_limit * _DESTINATION_IDENTITY_FACTS_PER_CANDIDATE
        )
        schema["properties"]["fact_assertions"]["maxItems"] = identity_fact_limit
        schema["properties"]["field_provenance"]["maxItems"] = identity_fact_limit
        schema["properties"]["source_records"]["maxItems"] = candidate_limit
    else:
        schema["properties"]["fact_assertions"]["maxItems"] = candidate_limit * 6
        schema["properties"]["field_provenance"]["maxItems"] = candidate_limit * 6
        schema["properties"]["source_records"]["maxItems"] = candidate_limit * 3
    candidate_items["oneOf"] = [
        {"$ref": f"#/$defs/{model_name}"} for _, model_name in allowed
    ]
    candidate_items["discriminator"]["mapping"] = {
        candidate_kind: f"#/$defs/{model_name}"
        for candidate_kind, model_name in allowed
    }
    schema["properties"]["worker_kind"] = {
        "const": expected_worker,
        "title": "Worker Kind",
        "type": "string",
    }
    if required_transport_classes:
        transport_schema = definitions.get("TransportCandidate")
        if isinstance(transport_schema, dict):
            transport_schema["properties"]["transport_class"] = {
                "enum": list(required_transport_classes),
                "title": "Transport Class",
                "type": "string",
            }
    if expected_active_constraint_ids is not None:
        constraint_ids = list(dict.fromkeys(expected_active_constraint_ids))
        constraint_count = len(constraint_ids)
        for _, model_name in allowed:
            candidate_schema = definitions.get(model_name)
            if not isinstance(candidate_schema, dict):
                continue
            candidate_schema["properties"]["active_constraint_ids"] = {
                "items": (
                    {"enum": constraint_ids, "type": "string"}
                    if constraint_ids
                    else {"type": "string"}
                ),
                "minItems": constraint_count,
                "maxItems": constraint_count,
                "type": "array",
            }
            evaluation_schema = candidate_schema["properties"]["constraint_evaluations"]
            evaluation_schema["minItems"] = constraint_count
            evaluation_schema["maxItems"] = constraint_count
        evaluation_model = definitions.get("CandidateConstraintEvaluation")
        if isinstance(evaluation_model, dict):
            evaluation_model["properties"]["constraint_id"] = (
                {"enum": constraint_ids, "type": "string"}
                if constraint_ids
                else {"type": "string"}
            )
    schema["properties"]["source_records"]["minItems"] = 0
    if authoritative_external_tool_source_ids is not None:
        _bind_external_tool_source_registry(
            schema,
            authoritative_external_tool_source_ids,
        )
    _drop_fields_the_model_must_not_author(schema)
    return as_strict_schema(schema)


_DEFINITION_REF_PREFIX = "#/$defs/"


def _referenced_definition_names(node: Any) -> set[str]:
    "Collect every ``$defs`` target a schema fragment can actually reach."
    names: set[str] = set()
    if isinstance(node, Mapping):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_DEFINITION_REF_PREFIX):
            names.add(ref[len(_DEFINITION_REF_PREFIX) :])
        for key, value in node.items():
            if key == "$defs":
                continue
            names |= _referenced_definition_names(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            names |= _referenced_definition_names(value)
    return names


def _closed_definitions(
    body: Mapping[str, Any],
    definitions: Mapping[str, Any],
) -> dict[str, Any]:
    "Return exactly the definitions ``body`` can reference, transitively."
    pending = _referenced_definition_names(body)
    closed: dict[str, Any] = {}
    while pending:
        name = pending.pop()
        if name in closed:
            continue
        definition = definitions.get(name)
        if not isinstance(definition, Mapping):
            raise ResearchPacketOutputError(
                f"provider selection contract references an undefined model: {name}"
            )
        closed[name] = definition
        pending |= _referenced_definition_names(definition)
    return {name: closed[name] for name in sorted(closed)}


def _provider_selection_response_schema(
    expected_worker: ResearchWorkerKind,
    eligible_place_options: Mapping[str, Sequence[Mapping[str, str]]],
) -> dict[str, Any]:
    "Build a small planning-only contract over the exact eligible place ids."
    packet_schema = ResearchPacket.model_json_schema()
    definitions = packet_schema["$defs"]
    allowed = tuple(
        (candidate_kind, model_name)
        for candidate_kind, model_name in _WORKER_CANDIDATE_MODELS[expected_worker]
        if eligible_place_options.get(candidate_kind)
    )
    for candidate_kind, model_name in allowed:
        candidate_schema = definitions[model_name]
        properties = candidate_schema["properties"]
        for field_name in _PROVIDER_SELECTION_SERVER_FIELDS:
            properties.pop(field_name, None)
        properties["candidate_kind"] = {
            "const": candidate_kind,
            "title": "Candidate Kind",
            "type": "string",
        }
        properties["place_id"] = {
            "enum": [
                option["place_id"] for option in eligible_place_options[candidate_kind]
            ],
            "title": "Place Id",
            "type": "string",
        }
        candidate_schema["required"] = [
            field_name
            for field_name in candidate_schema.get("required", [])
            if field_name not in _PROVIDER_SELECTION_SERVER_FIELDS
        ]
        if "candidate_kind" not in candidate_schema["required"]:
            candidate_schema["required"].append("candidate_kind")
    candidate_items = {
        "oneOf": [{"$ref": f"#/$defs/{model_name}"} for _, model_name in allowed],
        "discriminator": {
            "mapping": {
                candidate_kind: f"#/$defs/{model_name}"
                for candidate_kind, model_name in allowed
            },
            "propertyName": "candidate_kind",
        },
    }
    body = {
        "additionalProperties": False,
        "properties": {
            "selections": {
                "items": candidate_items,
                "maxItems": min(
                    packet_candidate_limit(expected_worker),
                    sum(len(options) for options in eligible_place_options.values()),
                ),
                "minItems": 1,
                "type": "array",
            },
            "operational_evidence": {
                "type": "array",
                "maxItems": packet_candidate_limit(expected_worker) * 2,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "place_id": {"type": "string"},
                        "field_path": {
                            "type": "string",
                            "enum": ["opening_window", "reservation_required"],
                        },
                        "value": {"anyOf": [{"type": "string"}, {"type": "boolean"}]},
                        "canonical_url": {"type": "string"},
                    },
                    "required": ["place_id", "field_path", "value", "canonical_url"],
                },
            },
        },
        "required": ["selections"],
        "type": "object",
    }
    selection_schema = {"$defs": _closed_definitions(body, definitions), **body}
    _drop_fields_the_model_must_not_author(selection_schema)
    return as_strict_schema(selection_schema)


def _provider_route_selection_response_schema(
    eligible_route_options: Sequence[Mapping[str, Any]],
    destination_ids: Sequence[str],
    *,
    maximum_selections: int,
) -> dict[str, Any]:
    return {
        "additionalProperties": False,
        "properties": {
            "selections": {
                "items": {
                    "additionalProperties": False,
                    "properties": {
                        "route_id": {
                            "enum": [
                                option["route_id"] for option in eligible_route_options
                            ],
                            "type": "string",
                        },
                        "destination_id": {
                            "enum": list(destination_ids),
                            "type": "string",
                        },
                        "selection_reasons": {
                            "items": {"minLength": 1, "type": "string"},
                            "minItems": 2,
                            "maxItems": 3,
                            "type": "array",
                        },
                        "tradeoff": {"minLength": 1, "type": "string"},
                        "booking_status": {
                            "enum": [
                                "not_required",
                                "recommended",
                                "required",
                                "booked",
                                "unknown",
                            ],
                            "type": "string",
                        },
                        "weather_sensitivity": WeatherSensitivity.model_json_schema(),
                    },
                    "required": [
                        "route_id",
                        "destination_id",
                        "selection_reasons",
                        "tradeoff",
                        "booking_status",
                        "weather_sensitivity",
                    ],
                    "type": "object",
                },
                "minItems": 1,
                "maxItems": min(
                    maximum_selections,
                    len(eligible_route_options),
                ),
                "type": "array",
            }
        },
        "required": ["selections"],
        "type": "object",
    }
