from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Mapping, Optional

from travel_agent.integrations.place_identity import stable_place_id_12306
from travel_agent.planning.research.output.options import (
    has_required_provider_route_selection_options,
)
from travel_agent.planning.research.output.transcript import authoritative_tool_messages
from travel_agent.planning.research.provider_contracts import (
    ProviderEvidenceScope,
    ProviderRouteLegScope,
)
from travel_agent.planning.research.reference_service_contracts import (
    ProviderReferenceService,
)
from travel_agent.planning.research.transport.rail.parsing import (
    _builtin_station_telecode,
    _builtin_station_telecode_candidates,
    _extract_tool_text,
    _filter_rail_trains_by_station_scope,
    _normalize_cn_city_for_rail,
    _parse_station_codes,
    _rail_station_scope,
    _rail_train_records,
)
from travel_agent.planning.research.transport.rail.selection import (
    _HIGH_SPEED_PREFIXES,
    MIN_SAME_DAY_RETURN_STAY_MINUTES,
    _clock_plus_buffer,
    _filter_rail_trains,
    _rail_constraint_params,
    _rail_iso,
    _rail_time_to_minutes,
    _select_best_train,
)
from travel_agent.planning.research.transport.rail.stations import _locate_rail_station
from travel_agent.planning.research.transport.scope import _NODE_NAME
from travel_agent.planning.state import TravelAgentState
from travel_agent.tools.content import compact_tool_content_for_model
from travel_agent.tools.execution import execute_tool
from travel_agent.tools.registry import get_tool_registry
from travel_agent.tools.temporal import (
    TemporalPreflightStatus,
    evaluate_temporal_request,
)

logger = logging.getLogger(__name__)


_DOMESTIC_RAIL_TOOL_NAMES = frozenset({"get-tickets", "get-station-code-of-citys"})


def _build_rail_route_envelope(
    *,
    train: Mapping[str, Any],
    start_date: str,
    audit_id: str,
    retrieved_at: str,
    from_point: Optional[tuple[float, float]],
    to_point: Optional[tuple[float, float]],
) -> Dict[str, Any]:
    """把一条真实的 12306 班次包装成结构化的 Provider 路线信封。"""
    departure_at = _rail_iso(start_date, train["departure_time"])
    arrival_date = start_date
    if _rail_time_to_minutes(train["arrival_time"]) < _rail_time_to_minutes(
        train["departure_time"]
    ):
        arrival_date = (
            datetime.date.fromisoformat(start_date) + datetime.timedelta(days=1)
        ).isoformat()
    arrival_at = _rail_iso(arrival_date, train["arrival_time"])
    mode = (
        "high_speed_rail"
        if str(train["train_code"])[:1] in _HIGH_SPEED_PREFIXES
        else "train"
    )

    from_place_id = stable_place_id_12306(train["from_code"])
    to_place_id = stable_place_id_12306(train["to_code"])
    if from_place_id is None or to_place_id is None:
        raise ValueError("12306 train missing station telecode for stable place_id")
    from_endpoint = {
        "name": train["from_name"],
        "station_code": train["from_code"],
        "place_id": from_place_id,
    }
    to_endpoint = {
        "name": train["to_name"],
        "station_code": train["to_code"],
        "place_id": to_place_id,
    }

    if from_point is not None:
        from_endpoint["latitude"], from_endpoint["longitude"] = from_point
    if to_point is not None:
        to_endpoint["latitude"], to_endpoint["longitude"] = to_point

    cost = train.get("min_price_cny")
    segment: Dict[str, Any] = {
        "segment_id": f"seg_{train['train_code']}",
        "mode": mode,
        "from_endpoint": dict(from_endpoint),
        "to_endpoint": dict(to_endpoint),
        "departure_at": departure_at,
        "arrival_at": arrival_at,
        "duration_minutes": train["duration_minutes"],
        "service_number": train["train_code"],
        "operator_name": "中国铁路",
    }
    route: Dict[str, Any] = {
        "route_id": train["train_code"],
        "transport_class": "long_distance",
        "selected_mode": mode,
        "from_endpoint": dict(from_endpoint),
        "to_endpoint": dict(to_endpoint),
        "departure_at": departure_at,
        "arrival_at": arrival_at,
        "duration_minutes": train["duration_minutes"],
        "segments": [segment],
    }
    if cost is not None:
        segment["cost_cny"] = cost
        route["total_cost_cny"] = cost
    return {
        "tool_name": "domestic_rail_search",
        "server_name": "12306-train",
        "status": "success",
        "audit_id": audit_id,
        "retrieved_at": retrieved_at,
        "metadata": {"evidence_allowed": True},
        "sanitized_result": {"success": True, "provider": "12306", "routes": [route]},
    }


async def _bind_one_rail_leg(
    *,
    state: TravelAgentState,
    messages: List[Dict[str, Any]],
    tool_context: Dict[str, Any],
    authoritative_tool_results: List[Dict[str, Any]],
    reference_services: List[ProviderReferenceService],
    scoped_leg: ProviderRouteLegScope,
    identity_by_place_id: Mapping[str, Mapping[str, Any]],
    station_code_cache: Dict[str, str],
    station_point_cache: Dict[str, Optional[tuple[float, float]]],
    now: Optional[datetime.datetime],
    depart_after: Optional[str] = None,
    same_day_roundtrip: bool = False,
    bound_arrivals: Optional[Dict[str, Optional[str]]] = None,
) -> bool:
    """用真实 12306 数据为一条指定长途腿确定班次。"""
    route_origin = identity_by_place_id.get(scoped_leg.from_place_id)
    route_destination = identity_by_place_id.get(scoped_leg.to_place_id)
    if route_origin is None or route_destination is None:
        logger.warning(
            "[transport_researcher] skip domestic rail: exact route endpoints are uncontrolled"
        )
        return False
    if (
        str(route_origin.get("country_code") or "").lower() != "cn"
        or str(route_destination.get("country_code") or "").lower() != "cn"
    ):
        logger.info("[transport_researcher] skip domestic rail: not a CN↔CN trip")
        return False
    origin_name = str(route_origin.get("name") or "").strip()
    dest_name = str(route_destination.get("name") or "").strip()
    dest_place_id = str(route_destination.get("place_id") or "").strip()
    start_date = scoped_leg.service_date.isoformat()
    if (
        not origin_name
        or not dest_name
        or origin_name == dest_name
        or not start_date
        or not dest_place_id
    ):
        logger.warning(
            "[transport_researcher] skip domestic rail: incomplete identity "
            "origin=%r dest=%r date=%r place_id=%r",
            origin_name,
            dest_name,
            start_date,
            bool(dest_place_id),
        )
        return False
    temporal = evaluate_temporal_request(
        tool_name="get-tickets",
        server_name="12306-train",
        arguments={"date": start_date},
        now=now,
    )
    temporal_envelope: Optional[Dict[str, Any]] = None
    if temporal.status != TemporalPreflightStatus.EXECUTABLE:
        temporal_result = await execute_tool(
            "get-tickets",
            {
                "date": start_date,
                "fromStation": "TEMPORAL_PREFLIGHT",
                "toStation": "TEMPORAL_PREFLIGHT",
            },
            allowed_tool_names=_DOMESTIC_RAIL_TOOL_NAMES,
            node_name=_NODE_NAME,
            activation_source="domestic_rail_temporal_preflight",
            allow_fallback=False,
            **tool_context,
        )
        if isinstance(temporal_result, dict):
            temporal_envelope = temporal_result
        if temporal.status == TemporalPreflightStatus.NOT_APPLICABLE:
            if temporal_envelope is not None:
                messages.append(
                    {
                        "role": "tool",
                        "content": compact_tool_content_for_model(temporal_envelope),
                    }
                )
                authoritative_tool_results.append(temporal_envelope)
            return False

    registry = get_tool_registry()
    if not registry.has_tool("get-tickets"):
        logger.warning(
            "[transport_researcher] skip domestic rail: get-tickets is not registered"
        )
        return False

    query_origin = _normalize_cn_city_for_rail(origin_name)
    query_dest = _normalize_cn_city_for_rail(dest_name)
    rail_constraint_params = _rail_constraint_params(state.constraint_pack)

    async def resolve_station_codes() -> tuple[Optional[str], Optional[str], str]:
        """返回 (from_code, to_code, source)；优先实时 MCP 结果，其次内置站码表。"""
        from_code: Optional[str] = None
        to_code: Optional[str] = None
        source = "none"
        cached_from = station_code_cache.get(query_origin)
        cached_to = station_code_cache.get(query_dest)
        if cached_from and cached_to:
            return cached_from, cached_to, "12306_mcp_cached"
        if registry.has_tool("get-station-code-of-citys"):
            try:
                code_env = await execute_tool(
                    "get-station-code-of-citys",
                    {"citys": f"{query_origin}|{query_dest}"},
                    allowed_tool_names=_DOMESTIC_RAIL_TOOL_NAMES,
                    node_name=_NODE_NAME,
                    activation_source="domestic_rail_station_code",
                    allow_fallback=False,
                    **tool_context,
                )
            except Exception:
                logger.warning(
                    "[transport_researcher] 12306 station-code tool raised",
                    exc_info=True,
                )
                code_env = None
            if isinstance(code_env, Mapping) and code_env.get("status") == "success":
                codes = _parse_station_codes(_extract_tool_text(code_env))
                from_code = codes.get(query_origin) or codes.get(origin_name)
                to_code = codes.get(query_dest) or codes.get(dest_name)
                if from_code and to_code:
                    station_code_cache[query_origin] = from_code
                    station_code_cache[query_dest] = to_code
                    return from_code, to_code, "12306_mcp"
                logger.warning(
                    "[transport_researcher] 12306 未返回站码: origin=%r dest=%r keys=%s",
                    query_origin,
                    query_dest,
                    list(codes.keys())[:8],
                )
            else:
                status = (
                    code_env.get("status") if isinstance(code_env, Mapping) else None
                )
                logger.warning(
                    "[transport_researcher] 12306 station-code status=%s (no web fallback)",
                    status,
                )
        else:
            logger.warning(
                "[transport_researcher] get-station-code-of-citys not registered; "
                "try builtin table"
            )

        from_code = from_code or _builtin_station_telecode(query_origin)
        to_code = to_code or _builtin_station_telecode(query_dest)
        if from_code and to_code:
            return from_code, to_code, "builtin_table"
        return from_code, to_code, source

    try:
        from_code, to_code, code_source = await resolve_station_codes()
        if not from_code or not to_code:
            logger.warning(
                "[transport_researcher] no station telecodes for %r → %r (source=%s)",
                query_origin,
                query_dest,
                code_source,
            )
            return False
        if code_source == "builtin_table":
            logger.info(
                "[transport_researcher] using builtin station telecodes %s/%s for %s→%s",
                from_code,
                to_code,
                query_origin,
                query_dest,
            )

        station_pairs: List[tuple[str, str]] = []
        for left in _builtin_station_telecode_candidates(query_origin) or [from_code]:
            for right in _builtin_station_telecode_candidates(query_dest) or [to_code]:
                pair = (left, right)
                if pair not in station_pairs:
                    station_pairs.append(pair)

        if (from_code, to_code) not in station_pairs:
            station_pairs.append((from_code, to_code))

        ticket_dates = [
            (
                temporal.reference_date.isoformat()
                if temporal.status == TemporalPreflightStatus.REFERENCE_ONLY
                and temporal.reference_date is not None
                else start_date
            )
        ]

        def compliant_rail_trains(
            env: Mapping[str, Any], pair: tuple[str, str]
        ) -> List[Dict[str, Any]]:
            """同时满足硬约束、且端点属于本次行程的班次。"""
            return _filter_rail_trains(
                _filter_rail_trains_by_station_scope(
                    _rail_train_records(env),
                    from_scope=_rail_station_scope(query_origin, pair[0]),
                    to_scope=_rail_station_scope(query_dest, pair[1]),
                ),
                rail_constraint_params,
            )

        ticket_env: Any = None
        used_pair: Optional[tuple[str, str]] = None
        used_query_date: Optional[str] = None
        for query_date in ticket_dates:
            for pair in station_pairs:
                env = await execute_tool(
                    "get-tickets",
                    {
                        "date": query_date,
                        "fromStation": pair[0],
                        "toStation": pair[1],
                    },
                    allowed_tool_names=_DOMESTIC_RAIL_TOOL_NAMES,
                    node_name=_NODE_NAME,
                    activation_source="domestic_rail_tickets",
                    allow_fallback=False,
                    **tool_context,
                )
                if not isinstance(env, Mapping) or env.get("status") != "success":
                    logger.warning(
                        "[transport_researcher] get-tickets status=%s from=%s to=%s "
                        "date=%s err=%s",
                        env.get("status") if isinstance(env, Mapping) else None,
                        pair[0],
                        pair[1],
                        query_date,
                        (env.get("error") if isinstance(env, Mapping) else None),
                    )
                    continue
                compliant_trains = compliant_rail_trains(env, pair)
                if (
                    _select_best_train(
                        compliant_trains,
                        requested_from=pair[0],
                        requested_to=pair[1],
                        leg_role=scoped_leg.leg_role,
                        depart_after=depart_after,
                        same_day_roundtrip=same_day_roundtrip,
                    )
                    is None
                ):
                    logger.warning(
                        "[transport_researcher] get-tickets empty trains from=%s to=%s date=%s",
                        pair[0],
                        pair[1],
                        query_date,
                    )
                    continue
                ticket_env = env
                used_pair = pair
                used_query_date = query_date
                break
            if ticket_env is not None:
                break
    except Exception:
        logger.warning(
            "[transport_researcher] deterministic 12306 rail discovery failed",
            exc_info=True,
        )
        return False
    if ticket_env is None or used_pair is None or used_query_date is None:
        if temporal_envelope is not None:
            messages.append(
                {
                    "role": "tool",
                    "content": compact_tool_content_for_model(temporal_envelope),
                }
            )
            authoritative_tool_results.append(temporal_envelope)
        logger.warning(
            "[transport_researcher] all get-tickets attempts failed for %s→%s on %s",
            query_origin,
            query_dest,
            start_date,
        )
        return False
    train = _select_best_train(
        compliant_rail_trains(ticket_env, used_pair),
        requested_from=used_pair[0],
        requested_to=used_pair[1],
        leg_role=scoped_leg.leg_role,
        depart_after=depart_after,
        same_day_roundtrip=same_day_roundtrip,
    )
    audit_id = str(ticket_env.get("audit_id") or "").strip()
    if train is None or not audit_id:
        logger.warning(
            "[transport_researcher] no parseable trains or audit_id for %s→%s",
            used_pair[0],
            used_pair[1],
        )
        return False
    if bound_arrivals is not None:
        bound_arrivals[scoped_leg.leg_role] = str(train.get("arrival_time") or "")
    logger.info(
        "[transport_researcher] bound %s depart_after=%s chosen=%s dep=%s arr=%s",
        scoped_leg.leg_role,
        depart_after,
        str(train.get("train_code") or ""),
        str(train.get("departure_time") or ""),
        str(train.get("arrival_time") or ""),
    )
    retrieved_at = str(
        ticket_env.get("retrieved_at")
        or datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    if temporal.status == TemporalPreflightStatus.REFERENCE_ONLY:
        if temporal_envelope is None:
            raise RuntimeError(
                "rail temporal reference decision omitted its audit envelope"
            )
        temporal_envelope["result_summary"] = temporal.user_message
        temporal_envelope["sanitized_result"] = {
            "success": True,
            "reference_kind": "latest_supported_day",
            "requested_date": start_date,
            "reference_date": used_query_date,
            "reference_train": {
                "train_no": train["train_code"],
                "from_name": train["from_name"],
                "to_name": train["to_name"],
                "departure_time": train["departure_time"],
                "arrival_time": train["arrival_time"],
                "duration_minutes": train["duration_minutes"],
                "lowest_observed_price_cny": train.get("min_price_cny"),
            },
            "claims_not_confirmed_for_requested_date": [
                "train_no",
                "departure_time",
                "arrival_time",
                "price",
                "inventory",
            ],
        }
        temporal_envelope.setdefault("metadata", {})
        temporal_envelope["metadata"].update(
            {
                "reference_tool_audit_id": audit_id,
                "requested_date": start_date,
                "reference_date": used_query_date,
                "reference_kind": "latest_supported_day",
                "evidence_allowed": False,
            }
        )
        messages.append(
            {
                "role": "tool",
                "content": compact_tool_content_for_model(temporal_envelope),
            }
        )
        authoritative_tool_results.append(temporal_envelope)

        reference_services.append(
            ProviderReferenceService(
                leg_role=scoped_leg.leg_role,
                from_name=train["from_name"],
                to_name=train["to_name"],
                service_number=train["train_code"],
                departure_time=train["departure_time"],
                arrival_time=train["arrival_time"],
                duration_minutes=train.get("duration_minutes"),
                lowest_observed_price_cny=train.get("min_price_cny"),
                requested_date=datetime.date.fromisoformat(start_date),
                reference_date=datetime.date.fromisoformat(used_query_date),
                unconfirmed_claims=list(
                    temporal_envelope["sanitized_result"][
                        "claims_not_confirmed_for_requested_date"
                    ]
                ),
            )
        )
        logger.info(
            "[transport_researcher] retained 12306 reference only: query_date=%s "
            "requested_date=%s train=%s",
            used_query_date,
            start_date,
            train["train_code"],
        )
        return False

    envelope = _build_rail_route_envelope(
        train=train,
        start_date=start_date,
        audit_id=audit_id,
        retrieved_at=retrieved_at,
        from_point=await _locate_rail_station(
            telecode=train["from_code"],
            station_name=train["from_name"],
            city=query_origin,
            city_identity=route_origin,
            tool_context=tool_context,
            point_cache=station_point_cache,
        ),
        to_point=await _locate_rail_station(
            telecode=train["to_code"],
            station_name=train["to_name"],
            city=query_dest,
            city_identity=route_destination,
            tool_context=tool_context,
            point_cache=station_point_cache,
        ),
    )
    messages.append(
        {"role": "tool", "content": compact_tool_content_for_model(envelope)}
    )
    authoritative_tool_results.append(envelope)
    logger.info(
        "[transport_researcher] deterministic 12306 rail bound: %s %s %s->%s %s "
        "(telecode_source=%s pair=%s query_date=%s)",
        scoped_leg.leg_role,
        train["train_code"],
        train["from_name"],
        train["to_name"],
        train["departure_time"],
        code_source,
        used_pair,
        used_query_date,
    )
    return True


async def discover_domestic_rail_route(
    *,
    state: TravelAgentState,
    messages: List[Dict[str, Any]],
    required_transport_classes: List[str] | None,
    connector_gaps: List[Dict[str, Any]] | None,
    tool_context: Dict[str, Any],
    authoritative_tool_results: List[Dict[str, Any]],
    reference_services: List[ProviderReferenceService],
    required_route_scopes: List[ProviderEvidenceScope],
    now: Optional[datetime.datetime] = None,
) -> bool:
    """为所有指定的国内城际铁路腿确定班次。"""
    classes = required_transport_classes or []

    if connector_gaps or (classes and "long_distance" not in classes):
        logger.info(
            "[transport_researcher] skip domestic rail: connector_gaps=%s classes=%s",
            bool(connector_gaps),
            classes,
        )
        return False
    identity = state.controlled_trip_identity or {}
    if not isinstance(identity, Mapping):
        logger.warning(
            "[transport_researcher] skip domestic rail: no controlled_trip_identity"
        )
        return False
    origin = identity.get("origin")
    destinations = identity.get("destinations")
    if (
        not isinstance(origin, Mapping)
        or not isinstance(destinations, list)
        or not destinations
    ):
        logger.warning(
            "[transport_researcher] skip domestic rail: missing origin/destinations"
        )
        return False
    scoped_legs = [
        scope.route_leg
        for scope in required_route_scopes
        if scope.transport_class == "long_distance" and scope.route_leg is not None
    ]
    if not scoped_legs:
        logger.warning(
            "[transport_researcher] skip domestic rail: no exact long-distance route scope"
        )
        return False
    identities = [item for item in [origin, *destinations] if isinstance(item, Mapping)]
    identity_by_place_id = {
        str(item.get("place_id") or "").strip(): item
        for item in identities
        if str(item.get("place_id") or "").strip()
    }

    station_code_cache: Dict[str, str] = {}

    station_point_cache: Dict[str, Optional[tuple[float, float]]] = {}
    bound_leg_roles: List[str] = []
    bound_arrivals: Dict[str, Optional[str]] = {}
    outbound_date = next(
        (leg.service_date for leg in scoped_legs if leg.leg_role == "outbound"),
        None,
    )
    same_day_roundtrip = outbound_date is not None and any(
        leg.leg_role == "return" and leg.service_date == outbound_date
        for leg in scoped_legs
    )
    for scoped_leg in scoped_legs:
        depart_after: Optional[str] = None
        if (
            scoped_leg.leg_role == "return"
            and outbound_date is not None
            and scoped_leg.service_date == outbound_date
        ):
            outbound_arrival = bound_arrivals.get("outbound")
            if outbound_arrival:
                depart_after = _clock_plus_buffer(
                    outbound_arrival, MIN_SAME_DAY_RETURN_STAY_MINUTES
                )
        if await _bind_one_rail_leg(
            state=state,
            messages=messages,
            tool_context=tool_context,
            authoritative_tool_results=authoritative_tool_results,
            reference_services=reference_services,
            scoped_leg=scoped_leg,
            identity_by_place_id=identity_by_place_id,
            station_code_cache=station_code_cache,
            station_point_cache=station_point_cache,
            now=now,
            depart_after=depart_after,
            same_day_roundtrip=same_day_roundtrip,
            bound_arrivals=bound_arrivals,
        ):
            bound_leg_roles.append(scoped_leg.leg_role)
    ready = has_required_provider_route_selection_options(
        authoritative_tool_messages(authoritative_tool_results),
        required_transport_classes=required_transport_classes,
        required_route_scopes=required_route_scopes,
    )
    logger.info(
        "[transport_researcher] domestic rail legs bound %d/%d (roles=%s ready=%s)",
        len(bound_leg_roles),
        len(scoped_legs),
        bound_leg_roles,
        ready,
    )
    return ready
