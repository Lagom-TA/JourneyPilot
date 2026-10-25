"""Research packet choices responsibilities."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from travel_agent.planning.weather.models import WeatherSensitivity

from .lineage import _query_row_matches_provider_identity
from .metadata import _controlled_destination_ids
from .policy import (
    _WORKER_CANDIDATE_MODELS,
    ResearchPacketOutputError,
    ResearchWorkerKind,
)

logger = logging.getLogger(__name__)

_TRANSPORT_PROVIDER_SELECTION_LIMIT = 2


def _default_provider_place_selections(
    *,
    base_payload: Mapping[str, Any],
    scoped_options: Mapping[str, Sequence[Mapping[str, str]]],
    selection_limit: int | None = None,
) -> dict[str, Any]:
    "Safe selector when the bounded semantic planning call is unavailable."
    destinations = _controlled_destination_ids(base_payload)
    if not destinations:
        raise ResearchPacketOutputError(
            "provider default selection requires a controlled destination"
        )
    destination_id = destinations[0]
    query_context = base_payload.get("query_context")
    query_context = query_context if isinstance(query_context, Mapping) else {}
    selections: list[dict[str, Any]] = []
    query_rows = query_context.get("query_lineage")
    query_rows = [
        row
        for row in (query_rows or [])
        if isinstance(row, Mapping)
        and str(row.get("query_kind") or "") in {"intent_primary", "targeted_repair"}
        and row.get("intent_ids")
    ]
    ceiling = max(int(selection_limit or 0), 1)
    weather = {
        "exposure": "mixed",
        "rain_sensitivity": "low",
        "heat_sensitivity": "low",
        "cold_sensitivity": "low",
        "wind_sensitivity": "low",
        "requires_clear_visibility": False,
    }
    for candidate_kind, options in scoped_options.items():
        remaining = ceiling - len(selections)
        if not options or remaining <= 0:
            continue
        selected_options: list[Mapping[str, str]] = []
        for row in query_rows:
            domain = str(row.get("domain") or "")
            if domain != candidate_kind:
                continue
            match = next(
                (
                    option
                    for option in options
                    if option not in selected_options
                    and _query_row_matches_provider_identity(
                        row,
                        provider_query=str(option.get("provider_query") or ""),
                        candidate_name=str(option.get("name") or ""),
                    )
                ),
                None,
            )
            if match is not None:
                selected_options.append(match)
            if len(selected_options) >= remaining:
                break
        for option in options:
            if len(selected_options) >= remaining:
                break
            if option not in selected_options:
                selected_options.append(option)
        for option in selected_options:
            semantic_joined = any(
                _query_row_matches_provider_identity(
                    row,
                    provider_query=str(option.get("provider_query") or ""),
                    candidate_name=str(option.get("name") or ""),
                )
                for row in query_rows
                if str(row.get("domain") or "") == candidate_kind
            )
            common = {
                "candidate_kind": candidate_kind,
                "place_id": option["place_id"],
                "destination_id": destination_id,
                "weather_sensitivity": weather,
                "selection_reasons": [
                    (
                        "命中 LLM 结构化意图查询并完成 Provider 实体闭包"
                        if semantic_joined
                        else "Provider 实体身份闭包完整"
                    ),
                    "位于当前受控目的地范围",
                ],
                "tradeoff": "动态营业、库存与价格信息仍需临行确认",
            }
            if candidate_kind == "visit":
                common.update(
                    {
                        "visit_type": "attraction",
                        "recommended_duration_minutes": 90,
                        "highlights": [str(option.get("name") or "实体景点")],
                    }
                )
            elif candidate_kind == "dining":
                common.update(
                    {
                        "meal_types": ["lunch", "dinner"],
                        "cuisine_types": ["local"],
                        "recommended_dishes": ["按当日菜单与过敏要求现场选择"],
                        "availability_status": "needs_confirmation",
                    }
                )
            elif candidate_kind == "lodging":
                identity = query_context.get("controlled_trip_identity")
                identity = identity if isinstance(identity, Mapping) else {}
                check_in = str(
                    query_context.get("check_in_date")
                    or identity.get("start_date")
                    or ""
                )[:10]
                check_out = str(
                    query_context.get("check_out_date")
                    or identity.get("end_date")
                    or ""
                )[:10]
                try:
                    nights = (
                        datetime.fromisoformat(check_out).date()
                        - datetime.fromisoformat(check_in).date()
                    ).days
                except ValueError:
                    nights = 0
                if not check_in or not check_out or nights < 1:
                    raise ResearchPacketOutputError(
                        "provider default lodging selection requires an exact stay interval"
                    )
                common.update(
                    {
                        "check_in_date": check_in,
                        "check_out_date": check_out,
                        "nights": nights,
                        "availability_status": "needs_confirmation",
                    }
                )
            selections.append(common)
    if not selections:
        raise ResearchPacketOutputError(
            "provider default selection has no eligible option"
        )
    return {"selections": selections}


def _validate_provider_place_selections(
    selection_payload: Any,
    *,
    expected_worker: ResearchWorkerKind,
    scoped_options: Mapping[str, Sequence[Mapping[str, str]]],
    selection_schema: Mapping[str, Any],
) -> list[dict[str, Any]]:
    "Validate the model-owned part before Provider facts are materialized."
    selections = (
        selection_payload.get("selections")
        if isinstance(selection_payload, dict)
        else None
    )
    if not isinstance(selections, list) or not selections:
        raise ResearchPacketOutputError(
            "provider place selection requires at least one explicit choice"
        )
    selection_limit = int(selection_schema["properties"]["selections"]["maxItems"])
    if len(selections) > selection_limit:
        raise ResearchPacketOutputError(
            "provider place selection exceeds the bounded selection limit"
        )
    model_name_by_kind = dict(_WORKER_CANDIDATE_MODELS[expected_worker])
    allowed_properties = {
        candidate_kind: set(
            selection_schema["$defs"][model_name_by_kind[candidate_kind]]["properties"]
        )
        for candidate_kind in scoped_options
        if candidate_kind in model_name_by_kind
    }
    allowed_place_ids = {
        candidate_kind: {str(option.get("place_id") or "") for option in kind_options}
        for candidate_kind, kind_options in scoped_options.items()
    }
    validated: list[dict[str, Any]] = []
    selected_pairs: set[tuple[str, str]] = set()
    for selection in selections:
        if not isinstance(selection, dict):
            raise ResearchPacketOutputError(
                "provider place selection contains a non-object choice"
            )
        candidate_kind = str(selection.get("candidate_kind") or "")
        place_id = str(selection.get("place_id") or "")
        if (
            candidate_kind not in allowed_properties
            or not set(selection) <= allowed_properties[candidate_kind]
        ):
            raise ResearchPacketOutputError(
                "provider place selection contains fields outside its typed domain"
            )
        if place_id not in allowed_place_ids.get(candidate_kind, set()):
            raise ResearchPacketOutputError(
                "provider place selection contains an unavailable place"
            )
        pair = (candidate_kind, place_id)
        if pair in selected_pairs:
            raise ResearchPacketOutputError(
                "provider place selection contains a duplicate place"
            )
        try:
            WeatherSensitivity.model_validate(selection.get("weather_sensitivity"))
        except ValidationError as exc:
            raise ResearchPacketOutputError(
                "provider place selection contains invalid weather sensitivity"
            ) from exc
        selected_pairs.add(pair)
        validated.append(selection)
    return validated


def _provider_place_selections_or_default(
    selection_payload: Any,
    *,
    model_authored: bool,
    base_payload: Mapping[str, Any],
    expected_worker: ResearchWorkerKind,
    scoped_options: Mapping[str, Sequence[Mapping[str, str]]],
    selection_schema: Mapping[str, Any],
) -> list[dict[str, Any]]:
    "Use a semantic choice when valid, otherwise preserve verified supply."
    try:
        return _validate_provider_place_selections(
            selection_payload,
            expected_worker=expected_worker,
            scoped_options=scoped_options,
            selection_schema=selection_schema,
        )
    except ResearchPacketOutputError:
        if not model_authored:
            raise
        logger.warning(
            "provider place planning selection violated its typed contract; "
            "applying deterministic policy",
            exc_info=True,
        )
    fallback_payload = _default_provider_place_selections(
        base_payload=base_payload,
        scoped_options=scoped_options,
        selection_limit=int(selection_schema["properties"]["selections"]["maxItems"]),
    )
    return _validate_provider_place_selections(
        fallback_payload,
        expected_worker=expected_worker,
        scoped_options=scoped_options,
        selection_schema=selection_schema,
    )


def _provider_route_option_group_key(
    option: Mapping[str, Any],
) -> tuple[str, str, str]:
    "The exact journey responsibility represented by one route option."
    provider_scope_id = str(option.get("provider_evidence_scope_id") or "")
    if provider_scope_id and option.get("transport_class") == "long_distance":
        return ("provider_scope", provider_scope_id, "")

    def endpoint_identity(value: Any) -> str:
        endpoint = value if isinstance(value, Mapping) else {}
        return str(
            endpoint.get("place_id")
            or endpoint.get("station_code")
            or endpoint.get("name")
            or ""
        )

    from_identity = endpoint_identity(option.get("from_endpoint"))
    to_identity = endpoint_identity(option.get("to_endpoint"))
    if from_identity and to_identity:
        mode = (
            str(option.get("selected_mode") or "")
            if option.get("transport_class") == "flexible"
            else str(option.get("transport_class") or "")
        )
        return ("endpoint_pair_mode", from_identity, f"{to_identity}|{mode}")
    return ("route", str(option.get("route_id") or ""), "")


def _default_provider_route_selection(
    eligible_route_options: Sequence[Mapping[str, Any]],
    destination_ids: Sequence[str],
    *,
    selection_limit: int | None = None,
) -> dict[str, Any]:
    if not eligible_route_options or not destination_ids:
        raise ResearchPacketOutputError(
            "provider default route selection requires options and destination"
        )
    options_by_scope: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for option in eligible_route_options:
        scope_key = _provider_route_option_group_key(option)
        options_by_scope.setdefault(scope_key, []).append(option)
    selections: list[dict[str, Any]] = []
    for scoped_options in options_by_scope.values():
        if selection_limit is not None and len(selections) >= selection_limit:
            break
        option = min(
            scoped_options,
            key=lambda item: (
                int(item.get("duration_minutes") or 10**9),
                str(item.get("route_id") or ""),
            ),
        )
        transport_class = str(option["transport_class"])
        selected_mode = str(option["selected_mode"])
        exposed = transport_class == "flexible" and selected_mode in {"walk", "bike"}
        selections.append(
            {
                "route_id": option["route_id"],
                "destination_id": destination_ids[0],
                "selection_reasons": [
                    "Provider 路线闭包完整",
                    "按总时长与稳定路线标识排序",
                ],
                "tradeoff": "动态班次、库存或道路状况仍需出发前确认",
                "booking_status": "recommended"
                if transport_class == "long_distance"
                else "not_required",
                "weather_sensitivity": {
                    "exposure": "outdoor" if exposed else "mixed",
                    "rain_sensitivity": "high" if exposed else "low",
                    "heat_sensitivity": "high" if exposed else "low",
                    "cold_sensitivity": "low",
                    "wind_sensitivity": "high" if exposed else "low",
                    "requires_clear_visibility": False,
                },
            }
        )
    return {"selections": selections}


def _provider_route_selection_limit(
    eligible_route_options: Sequence[Mapping[str, Any]],
    *,
    required_transport_classes: Sequence[str] | None,
) -> int:
    "Bound one selection per exact Provider scope or local adjacency."
    represented_responsibilities = {
        _provider_route_option_group_key(option) for option in eligible_route_options
    }
    if represented_responsibilities:
        return len(represented_responsibilities)
    return _TRANSPORT_PROVIDER_SELECTION_LIMIT


def _validate_provider_route_selections(
    selection_payload: Any,
    *,
    eligible_route_options: Sequence[Mapping[str, Any]],
    destination_ids: Sequence[str],
    maximum_selections: int,
) -> list[dict[str, Any]]:
    selections = (
        selection_payload.get("selections")
        if isinstance(selection_payload, dict)
        else None
    )
    if not isinstance(selections, list) or not selections:
        raise ResearchPacketOutputError(
            "provider route selection requires at least one explicit choice"
        )
    if len(selections) > maximum_selections:
        raise ResearchPacketOutputError(
            "provider route selection exceeds the bounded selection limit"
        )
    option_by_id = {
        str(option["route_id"]): option for option in eligible_route_options
    }
    selected_ids: list[str] = []
    selected_responsibilities: set[tuple[str, str, str]] = set()
    for selection in selections:
        if not isinstance(selection, dict) or set(selection) != {
            "route_id",
            "destination_id",
            "selection_reasons",
            "tradeoff",
            "booking_status",
            "weather_sensitivity",
        }:
            raise ResearchPacketOutputError(
                "provider route selection contains fields outside its typed domain"
            )
        route_id = str(selection.get("route_id") or "")
        if route_id not in option_by_id or route_id in selected_ids:
            raise ResearchPacketOutputError(
                "provider route selection contains an unavailable or duplicate route"
            )
        if str(selection.get("destination_id") or "") not in destination_ids:
            raise ResearchPacketOutputError(
                "provider route selection contains an uncontrolled destination"
            )
        try:
            WeatherSensitivity.model_validate(selection.get("weather_sensitivity"))
        except ValidationError as exc:
            raise ResearchPacketOutputError(
                "provider route selection contains invalid weather sensitivity"
            ) from exc
        responsibility = _provider_route_option_group_key(option_by_id[route_id])
        if responsibility in selected_responsibilities:
            raise ResearchPacketOutputError(
                "provider route selection repeated an exact journey responsibility"
            )
        selected_responsibilities.add(responsibility)
        selected_ids.append(route_id)
    return selections


def _provider_route_selections_or_default(
    selection_payload: Any,
    *,
    model_authored: bool,
    eligible_route_options: Sequence[Mapping[str, Any]],
    destination_ids: Sequence[str],
    maximum_selections: int,
) -> list[dict[str, Any]]:
    try:
        return _validate_provider_route_selections(
            selection_payload,
            eligible_route_options=eligible_route_options,
            destination_ids=destination_ids,
            maximum_selections=maximum_selections,
        )
    except ResearchPacketOutputError:
        if not model_authored:
            raise
        logger.warning(
            "provider route planning selection violated its typed contract; "
            "applying deterministic policy",
            exc_info=True,
        )
    fallback_payload = _default_provider_route_selection(
        eligible_route_options,
        destination_ids,
        selection_limit=maximum_selections,
    )
    return _validate_provider_route_selections(
        fallback_payload,
        eligible_route_options=eligible_route_options,
        destination_ids=destination_ids,
        maximum_selections=maximum_selections,
    )


def _provider_route_constraint_evaluation(
    constraint: Mapping[str, Any],
    route: Mapping[str, Any],
    fact_ids_by_field: Mapping[str, str],
) -> dict[str, Any]:
    "Evaluate canonical route constraints from server-bound Provider facts."
    params = (
        constraint.get("params")
        if isinstance(constraint.get("params"), Mapping)
        else {}
    )
    checks: list[bool | None] = []
    evidence_fields: list[str] = []
    try:
        departure = datetime.fromisoformat(
            str(route.get("departure_at") or "").replace("Z", "+00:00")
        )
    except ValueError:
        departure = None
    try:
        arrival = datetime.fromisoformat(
            str(route.get("arrival_at") or "").replace("Z", "+00:00")
        )
    except ValueError:
        arrival = None
    if params.get("avoid_overnight"):
        checks.append(
            departure.date() == arrival.date()
            if departure is not None and arrival is not None
            else None
        )
        evidence_fields.extend(["departure_at", "arrival_at"])
    earliest = str(params.get("earliest_departure_local") or "")
    if earliest:
        checks.append(
            departure.strftime("%H:%M") >= earliest if departure is not None else None
        )
        evidence_fields.append("departure_at")
    latest = str(params.get("latest_arrival_local") or "")
    if latest:
        checks.append(
            arrival.strftime("%H:%M") <= latest if arrival is not None else None
        )
        evidence_fields.append("arrival_at")
    unsupported_avoid = [
        item
        for item in params.get("avoid") or []
        if item not in {"night_bus", "red_eye_flight"}
    ]
    if unsupported_avoid:
        checks.append(None)
    fact_ids = list(
        dict.fromkeys(
            fact_ids_by_field[field]
            for field in evidence_fields
            if field in fact_ids_by_field
        )
    )
    if False in checks:
        status, reason_code = "failed", "route_time_constraint_failed"
    elif checks and None not in checks:
        status, reason_code = "passed", None
    else:
        status, reason_code = "unknown", "route_constraint_evidence_missing"
        fact_ids = []
    return {
        "constraint_id": str(constraint["constraint_id"]),
        "status": status,
        "fact_assertion_ids": fact_ids,
        "reason_code": reason_code,
    }
