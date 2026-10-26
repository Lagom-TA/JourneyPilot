from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

from travel_agent.integrations.places.normalization import is_concrete_lodging_place
from travel_agent.integrations.places.taxonomy import (
    provider_place_type_matches_candidate_kind,
)
from travel_agent.planning.research.accommodation.scope import _NODE_NAME
from travel_agent.planning.research.output.failures import _merge_failed_tool_sources
from travel_agent.planning.research.output.identifiers import _provider_candidate_id
from travel_agent.planning.research.output.parsing import parse_research_packet_output
from travel_agent.planning.research.output.policy import (
    ResearchPacketOutputError,
    packet_candidate_limit,
)
from travel_agent.planning.research.output.transcript import (
    _successful_place_records,
    authoritative_tool_messages,
)
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.state import TravelAgentState
from travel_agent.utils.geography import distance_from_destination_km

logger = logging.getLogger(__name__)


_AUTHORED_TRADEOFF = (
    "位置由真实地图检索结果确定；价格与房型未经平台核实时需向酒店核对"
)


_AUTHORED_SELECTION_REASON = "由真实地图检索返回的住宿地点"


# 住宿是室内场所，天气敏感度取无影响，不据此生成额外的天气顾虑。
_LODGING_WEATHER_SENSITIVITY = {
    "exposure": "indoor",
    "rain_sensitivity": "none",
    "heat_sensitivity": "none",
    "cold_sensitivity": "none",
    "wind_sensitivity": "none",
    "requires_clear_visibility": False,
}


def _identity_date(value: Any) -> Optional[date]:
    """读取受控行程身份中的日期，兼容 date 与 ISO 字符串。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _identity_destinations(identity: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """提取可用作 candidate.destination_id 的受控目的地。"""
    destinations = identity.get("destinations")
    if not isinstance(destinations, list):
        return []
    result: List[Dict[str, Any]] = []
    for item in destinations:
        if not isinstance(item, Mapping):
            continue
        place_id = str(item.get("place_id") or "").strip()
        if not place_id:
            continue
        result.append(
            {
                "place_id": place_id,
                "latitude": item.get("latitude"),
                "longitude": item.get("longitude"),
            }
        )
    return result


def _lodging_places(
    authoritative_tool_results: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """按检索顺序返回可用作住宿候选的真实地点记录。"""
    records = _successful_place_records(
        authoritative_tool_messages(authoritative_tool_results)
    )
    places: List[Dict[str, Any]] = []
    for _envelope, provider_place, _result_index in records.values():
        record = dict(provider_place)
        if not provider_place_type_matches_candidate_kind(
            str(record.get("provider_place_type") or ""), "lodging"
        ):
            continue
        if not is_concrete_lodging_place(record):
            continue
        places.append(record)
    return places


def _destination_index(
    place: Mapping[str, Any], destinations: Sequence[Mapping[str, Any]]
) -> int:
    """按坐标距离把地点归入最近的目的地；无法计算距离时取第一个目的地。"""
    if len(destinations) == 1:
        return 0
    best_index = 0
    best_distance: Optional[float] = None
    for index, destination in enumerate(destinations):
        distance = distance_from_destination_km(
            place.get("latitude"),
            place.get("longitude"),
            destination.get("latitude"),
            destination.get("longitude"),
        )
        if distance is not None and (
            best_distance is None or distance < best_distance
        ):
            best_index, best_distance = index, distance
    return best_index


def _candidate_payload(
    place: Mapping[str, Any],
    destination: Mapping[str, Any],
    *,
    check_in: date,
    check_out: date,
    nights: int,
) -> Dict[str, Any]:
    """把一条 Provider 地点记录投影为 LodgingCandidate 的输入字段。"""
    place_id = str(place["place_id"])
    return {
        "candidate_kind": "lodging",
        "candidate_id": _provider_candidate_id("lodging", place_id),
        "destination_id": str(destination["place_id"]),
        "place_id": place_id,
        "provider_place_type": str(place["provider_place_type"]),
        "provider_country_code": str(place["provider_country_code"]),
        "property_name": str(place["name"]),
        "address": str(place["address"]),
        "check_in_date": check_in.isoformat(),
        "check_out_date": check_out.isoformat(),
        "nights": nights,
        "price_kind": "reference_estimate",
        "availability_status": "needs_confirmation",
        "freshness_status": "current",
        "selection_reasons": [_AUTHORED_SELECTION_REASON],
        "tradeoff": _AUTHORED_TRADEOFF,
        "weather_sensitivity": dict(_LODGING_WEATHER_SENSITIVITY),
    }


def deterministic_lodging_candidates(
    state: TravelAgentState,
    authoritative_tool_results: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """从已注入的真实住宿地点组装候选；每个目的地优先各占一个名额。

    日期取受控行程身份，未知价格与房型保持缺失。没有任何可用地点或行程不足
    一晚时返回空列表。
    """
    identity = state.controlled_trip_identity or {}
    if not isinstance(identity, Mapping):
        return []
    destinations = _identity_destinations(identity)
    if not destinations:
        return []
    check_in = _identity_date(identity.get("start_date"))
    check_out = _identity_date(identity.get("end_date"))
    if check_in is None or check_out is None:
        return []
    nights = (check_out - check_in).days
    if nights < 1:
        return []
    places = _lodging_places(authoritative_tool_results)
    if not places:
        return []
    grouped: List[List[Dict[str, Any]]] = [[] for _ in destinations]
    for place in places:
        grouped[_destination_index(place, destinations)].append(place)
    limit = packet_candidate_limit(_NODE_NAME)
    candidates: List[Dict[str, Any]] = []
    for offset in range(max(len(group) for group in grouped)):
        for index, group in enumerate(grouped):
            if offset >= len(group) or len(candidates) >= limit:
                continue
            candidates.append(
                _candidate_payload(
                    group[offset],
                    destinations[index],
                    check_in=check_in,
                    check_out=check_out,
                    nights=nights,
                )
            )
    return candidates


def assemble_lodging_fallback_packet(
    *,
    base_packet: Optional[ResearchPacket],
    candidates: Sequence[Mapping[str, Any]],
    authoritative_packet_metadata: Mapping[str, Any],
    authoritative_tool_results: Sequence[Mapping[str, Any]],
    expected_active_constraint_ids: Sequence[str] | None,
) -> Optional[ResearchPacket]:
    """用确定性候选补齐或重建 packet，身份、事实和来源仍由服务端绑定。

    以已解析的 packet 为底稿可以保留其中的来源记录；解析失败时用服务端元数据
    重建。组装结果无法通过契约校验时返回 None，由调用方沿用原有的失败处理。
    """
    if not candidates:
        return None
    payload: Dict[str, Any] = (
        base_packet.model_dump(mode="json")
        if base_packet is not None
        else {
            "candidates": [],
            "candidate_discovery_records": [],
            "source_records": [],
            "fact_assertions": [],
            "field_provenance": [],
        }
    )
    payload["candidates"] = [*(payload.get("candidates") or []), *candidates]
    try:
        packet = parse_research_packet_output(
            json.dumps(payload, ensure_ascii=False),
            expected_worker=_NODE_NAME,
            expected_run_id=str(authoritative_packet_metadata.get("run_id") or ""),
            authoritative_tool_results=authoritative_tool_results,
            expected_active_constraint_ids=expected_active_constraint_ids,
            authoritative_packet_metadata=authoritative_packet_metadata,
        )
    except ResearchPacketOutputError:
        logger.warning(
            "[%s] deterministic lodging fallback rejected by packet validation",
            _NODE_NAME,
            exc_info=True,
        )
        return None
    return _merge_failed_tool_sources(
        packet, authoritative_tool_messages(authoritative_tool_results)
    )
