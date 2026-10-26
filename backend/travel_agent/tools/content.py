from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping

from ..knowledge.fragments import rag_chunk_source_id
from .governance import is_tool_execution_envelope

_TOOL_CONTENT_CHAR_LIMIT = 6000


_PLACE_RESULT_CAP = 12


_ROUTE_RESULT_CAP = 8


_GENERIC_LIST_CAP = 16


_STRING_FIELD_CAP = 400


_PLACE_IDENTITY_KEYS = (
    "place_id",
    "name",
    "address",
    "provider_place_type",
    "provider_country_code",
    "provider",
    "latitude",
    "longitude",
    "aliases",
    "station_code",
)


_ROUTE_IDENTITY_KEYS = (
    "route_id",
    "mode",
    "transport_class",
    "selected_mode",
    "from_endpoint",
    "to_endpoint",
    "from_place_id",
    "to_place_id",
    "departure_at",
    "arrival_at",
    "duration_minutes",
    "distance_meters",
    "cost",
    "segments",
    "provider",
    "train_no",
    "prices",
)


_ENVELOPE_TOP_KEYS = (
    "schema_version",
    "audit_id",
    "tool_name",
    "server_name",
    "category",
    "source_type",
    "trust_level",
    "status",
    "args_digest",
    "sanitized_args_summary",
    "result_summary",
    "untrusted_content",
    "retrieved_at",
    "freshness_hint",
    "fallback_from",
    "fallback_to",
    "degradation_reason",
    "error",
    "evidence_candidate",
)


_METADATA_KEEP_KEYS = (
    "evidence_allowed",
    "quarantine_result",
    "snapshot_cache",
    "provider_snapshot",
    "place_ids",
    "route_ids",
)


def _clip_str(value: str, limit: int = _STRING_FIELD_CAP) -> str:
    text = value if len(value) <= limit else value[: limit - 1].rstrip() + "…"
    return text


def _compact_mapping_fields(
    item: Mapping[str, Any],
    keys: tuple[str, ...],
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in keys:
        if key not in item:
            continue
        value = item[key]
        if isinstance(value, str):
            out[key] = _clip_str(value)
        elif isinstance(value, dict):
            nested = {
                nk: (_clip_str(nv) if isinstance(nv, str) else nv)
                for nk, nv in value.items()
                if nk in _PLACE_IDENTITY_KEYS
                or nk in {"name", "place_id", "latitude", "longitude", "station_code"}
            }
            out[key] = nested
        elif isinstance(value, list):
            out[key] = value[:_GENERIC_LIST_CAP]
        else:
            out[key] = value
    return out


def _compact_sanitized_result(result: Any) -> Any:
    if not isinstance(result, dict):
        if isinstance(result, str):
            return _clip_str(result, 800)
        if isinstance(result, list):
            return [
                _compact_sanitized_result(item) for item in result[:_GENERIC_LIST_CAP]
            ]
        return result

    compact: Dict[str, Any] = {}
    for key, value in result.items():
        if key == "documents" and isinstance(value, list):
            documents = []
            for item in value[:5]:
                if not isinstance(item, dict) or not item.get("content"):
                    continue
                doc = {
                    field: item[field]
                    for field in (
                        "content",
                        "source",
                        "collection",
                        "published_at",
                        "retrieved_at",
                        "retrieval_method",
                    )
                    if field in item
                }
                doc["source_record_id"] = rag_chunk_source_id(doc)
                documents.append(doc)
            compact[key] = documents
        elif key == "results" and isinstance(value, list):
            compact[key] = [
                _compact_sanitized_result(item) for item in value[:_PLACE_RESULT_CAP]
            ]
        elif key == "routes" and isinstance(value, list):
            routes: List[Any] = []
            for item in value[:_ROUTE_RESULT_CAP]:
                if isinstance(item, dict):
                    routes.append(_compact_mapping_fields(item, _ROUTE_IDENTITY_KEYS))
                else:
                    routes.append(item)
            compact[key] = routes
        elif key in {
            "success",
            "error",
            "message",
            "type",
            "question",
            "options",
            "selection_type",
            "allow_free_input",
            "provider",
        }:
            compact[key] = value
        elif isinstance(value, str):
            compact[key] = _clip_str(value)
        elif isinstance(value, (int, float, bool)) or value is None:
            compact[key] = value
        elif isinstance(value, list):
            if value and all(
                isinstance(item, (str, int, float, bool)) or item is None
                for item in value
            ):
                compact[key] = value[: max(_GENERIC_LIST_CAP, _PLACE_RESULT_CAP)]
            else:
                compact[key] = [
                    _compact_sanitized_result(item)
                    for item in value[:_GENERIC_LIST_CAP]
                ]
        elif isinstance(value, dict):
            compact[key] = _compact_sanitized_result(value)
    return compact


def _looks_like_tool_envelope(value: Mapping[str, Any]) -> bool:
    """True for full ToolExecutionEnvelope or worker-injected partial envelopes."""
    if is_tool_execution_envelope(value):
        return True
    return (
        "sanitized_result" in value
        and ("tool_name" in value or "audit_id" in value)
        and "status" in value
    )


def _compact_envelope_dict(envelope: Mapping[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {}
    for key in _ENVELOPE_TOP_KEYS:
        if key in envelope:
            value = envelope[key]
            compact[key] = _clip_str(value) if isinstance(value, str) else value

    for key in ("tool_name", "audit_id", "status"):
        if key in envelope and key not in compact:
            compact[key] = envelope[key]
    metadata = envelope.get("metadata")
    if isinstance(metadata, dict):
        meta_out: Dict[str, Any] = {}
        for key in _METADATA_KEEP_KEYS:
            if key in metadata:
                meta_out[key] = metadata[key]

        for key, value in metadata.items():
            if (
                key.endswith("_place_ids") or key.endswith("_ids")
            ) and key not in meta_out:
                meta_out[key] = value
            if key in {"evidence_allowed", "quarantine_result"} and key not in meta_out:
                meta_out[key] = value
        if meta_out:
            compact["metadata"] = meta_out
    if "sanitized_result" in envelope:
        compact["sanitized_result"] = _compact_sanitized_result(
            envelope.get("sanitized_result")
        )
    return compact


def compact_tool_content_for_model(tool_result: Any) -> str:
    "Serialize a tool result for LLM / packet-transcript messages."
    if tool_result is None:
        return "null"
    if isinstance(tool_result, dict) and _looks_like_tool_envelope(tool_result):
        compact: Any = _compact_envelope_dict(tool_result)
    elif isinstance(tool_result, dict):
        compact = _compact_sanitized_result(tool_result)
    else:
        compact = tool_result

    text = json.dumps(compact, ensure_ascii=False, default=str)
    if len(text) <= _TOOL_CONTENT_CHAR_LIMIT:
        return text

    if isinstance(compact, dict):
        payload = compact.get("sanitized_result", compact)
        if isinstance(payload, dict) and isinstance(payload.get("documents"), list):
            payload["truncated"] = True
            while payload["documents"] and len(text) > _TOOL_CONTENT_CHAR_LIMIT:
                payload["documents"].pop()
                text = json.dumps(compact, ensure_ascii=False, default=str)
            if len(text) <= _TOOL_CONTENT_CHAR_LIMIT:
                return text

    if isinstance(compact, dict):
        reduced = dict(compact)
        if "sanitized_result" in reduced:
            summary = (
                reduced.get("result_summary") or "result truncated for model budget"
            )

            prior = reduced.get("sanitized_result")
            identity_only: Dict[str, Any] = {
                "truncated": True,
                "note": _clip_str(str(summary), 240),
            }
            if isinstance(prior, dict):
                if isinstance(prior.get("results"), list):
                    identity_only["results"] = prior["results"][:_PLACE_RESULT_CAP]
                    identity_only["success"] = prior.get("success", True)
                if isinstance(prior.get("routes"), list):
                    identity_only["routes"] = prior["routes"][:_ROUTE_RESULT_CAP]
                    identity_only["success"] = prior.get("success", True)
            reduced["sanitized_result"] = identity_only
            text = json.dumps(reduced, ensure_ascii=False, default=str)
            if len(text) <= _TOOL_CONTENT_CHAR_LIMIT:
                return text

            ids: List[str] = []
            for item in identity_only.get("results") or []:
                if isinstance(item, dict) and item.get("place_id"):
                    ids.append(str(item["place_id"]))
            for item in identity_only.get("routes") or []:
                if isinstance(item, dict) and item.get("route_id"):
                    ids.append(str(item["route_id"]))
            reduced["sanitized_result"] = {
                "truncated": True,
                "success": True,
                "identity_ids": ids[:32],
                "note": _clip_str(str(summary), 160),
            }
            text = json.dumps(reduced, ensure_ascii=False, default=str)
            if len(text) <= _TOOL_CONTENT_CHAR_LIMIT:
                return text
        reduced.pop("evidence_candidate", None)
        reduced.pop("freshness_hint", None)
        text = json.dumps(reduced, ensure_ascii=False, default=str)
        if len(text) <= _TOOL_CONTENT_CHAR_LIMIT:
            return text
        minimal = {
            "audit_id": reduced.get("audit_id"),
            "tool_name": reduced.get("tool_name"),
            "status": reduced.get("status"),
            "result_summary": _clip_str(
                str(reduced.get("result_summary") or "truncated"), 200
            ),
            "error": reduced.get("error"),
            "degradation_reason": reduced.get("degradation_reason"),
            "fallback_from": reduced.get("fallback_from"),
            "fallback_to": reduced.get("fallback_to"),
            "metadata": reduced.get("metadata"),
            "truncated": True,
        }
        return json.dumps(minimal, ensure_ascii=False, default=str)

    return json.dumps(
        {"truncated": True, "note": _clip_str(text, 400)},
        ensure_ascii=False,
    )
