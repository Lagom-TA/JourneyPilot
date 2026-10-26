from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlsplit

from pydantic import ValidationError

from travel_agent.planning.research.provider_contracts import TIMETABLED_TRANSPORT_CLASSES
from travel_agent.planning.transport import (
    TransportEndpoint,
    TransportMode,
    TransportSegment,
)
from travel_agent.tools.governance import ToolExecutionStatus


def _retrieved_source_snapshots(
    evidence_messages: Sequence[Mapping[str, Any]],
    *,
    page_specific: bool = False,
) -> dict[str, dict[str, Any]]:
    """本轮检索返回的每个页面，以及该页面对应的返回内容。"""
    countable = {
        ToolExecutionStatus.SUCCESS.value,
        ToolExecutionStatus.DEGRADED.value,
    }
    snapshots: dict[str, dict[str, Any]] = {}

    def walk(value: Any, whole_return: Mapping[str, Any]) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key).casefold() in {
                    "url",
                    "canonical_url",
                    "link",
                } and isinstance(item, str):
                    normalized = _normalized_source_url(item)
                    if normalized and normalized not in snapshots:
                        snapshots[normalized] = (
                            dict(value) if page_specific else dict(whole_return)
                        )
                else:
                    walk(item, whole_return)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item, whole_return)
        elif isinstance(value, str):
            blocks = (
                re.split(r"(?m)(?=^\s*\d{1,2}\.\s+)", value)
                if page_specific
                else [value]
            )
            for block in blocks:
                urls = re.findall(r"https?://[^\s<>\"\u3000]+", block)
                if page_specific and len(set(urls)) > 1:
                    continue
                for url in urls:
                    normalized = _normalized_source_url(url.rstrip(".,;，。；)）"))
                    if normalized and normalized not in snapshots:
                        snapshots[normalized] = (
                            {"url": url, "content": block}
                            if page_specific
                            else dict(whole_return)
                        )

    for message in evidence_messages:
        envelope = _parse_tool_envelope(message)
        if envelope is None or envelope.get("status") not in countable:
            continue
        result = envelope.get("sanitized_result")
        if isinstance(result, Mapping):
            walk(result, result)
    return snapshots


def _normalized_source_url(value: Any) -> Optional[str]:
    """按 scheme、host 与 path 比较 URL，这三部分用于定位页面。"""
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlsplit(text)
    if not parsed.scheme or not parsed.netloc:
        return None
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}{path}"


def _parse_tool_envelope(message: Mapping[str, Any]) -> dict[str, Any] | None:
    if message.get("role") != "tool":
        return None
    content = message.get("content")
    try:
        envelope = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        return None
    return envelope if isinstance(envelope, dict) else None


def authoritative_tool_messages(
    tool_results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """包装完整的 Gateway 结果，供确定性证据编译使用。"""
    return [
        {"role": "tool", "content": dict(result)}
        for result in tool_results
        if isinstance(result, Mapping)
    ]


def _successful_place_records(
    context_messages: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[dict[str, Any], dict[str, Any], int]]:
    """按稳定 place id 索引最近一次可用且完整的 Provider 信封。"""
    records: dict[str, tuple[dict[str, Any], dict[str, Any], int]] = {}
    for message in context_messages:
        envelope = _parse_tool_envelope(message)
        if (
            envelope is None
            or envelope.get("tool_name") != "global_place_search"
            or envelope.get("status") != "success"
        ):
            continue
        metadata = envelope.get("metadata")
        if (
            not isinstance(metadata, dict)
            or metadata.get("evidence_allowed") is not True
            or metadata.get("quarantine_result") is True
        ):
            continue
        result = envelope.get("sanitized_result")
        if not isinstance(result, dict) or result.get("success") is not True:
            continue
        provider_results = result.get("results")
        if not isinstance(provider_results, list):
            continue
        for index, item in enumerate(provider_results):
            if not isinstance(item, dict):
                continue
            values = (
                item.get("place_id"),
                item.get("provider_place_type"),
                item.get("provider_country_code"),
                item.get("name"),
                item.get("address"),
            )
            if not all(isinstance(value, str) and value.strip() for value in values):
                continue
            records[str(item["place_id"])] = (envelope, item, index)
    return records


def _successful_route_records(
    context_messages: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[dict[str, Any], dict[str, Any], int]]:
    """按稳定 route id 索引完整可用的 Provider 路线。"""
    records: dict[str, tuple[dict[str, Any], dict[str, Any], int]] = {}
    for message in context_messages:
        envelope = _parse_tool_envelope(message)
        if (
            envelope is None
            or envelope.get("tool_name")
            not in {"global_route_search", "search_flights", "domestic_rail_search"}
            or envelope.get("status") != "success"
        ):
            continue
        metadata = envelope.get("metadata")
        if (
            not isinstance(metadata, dict)
            or metadata.get("evidence_allowed") is not True
            or metadata.get("quarantine_result") is True
        ):
            continue
        result = envelope.get("sanitized_result")
        if not isinstance(result, dict) or result.get("success") is not True:
            continue
        routes = result.get("routes")
        if not isinstance(routes, list):
            continue
        for index, route in enumerate(routes):
            if not isinstance(route, dict):
                continue
            audit_id = str(envelope.get("audit_id") or "").strip()
            route_id = route.get("route_id")
            transport_class = route.get("transport_class")
            selected_mode = route.get("selected_mode")
            segments = route.get("segments")
            if (
                not audit_id
                or not isinstance(route_id, str)
                or not route_id.strip()
                or transport_class
                not in {"long_distance", "public_transit", "flexible"}
                or not isinstance(selected_mode, str)
                or not isinstance(segments, list)
                or not segments
                or not isinstance(route.get("duration_minutes"), int)
            ):
                continue
            if transport_class in TIMETABLED_TRANSPORT_CLASSES and (
                not isinstance(route.get("departure_at"), str)
                or not isinstance(route.get("arrival_at"), str)
            ):
                continue
            try:
                TransportMode(selected_mode)
                origin = TransportEndpoint.model_validate(route.get("from_endpoint"))
                destination = TransportEndpoint.model_validate(route.get("to_endpoint"))
                typed_segments = [
                    TransportSegment.model_validate(segment) for segment in segments
                ]
            except (TypeError, ValueError, ValidationError):
                continue
            if (
                typed_segments[0].from_endpoint != origin
                or typed_segments[-1].to_endpoint != destination
            ):
                continue
            records[route_id] = (envelope, route, index)
    return records
