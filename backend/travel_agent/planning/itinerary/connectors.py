from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Literal, Mapping, Optional

from pydantic import Field, model_validator

from travel_agent.planning.itinerary.adjacency import (
    _chain_endpoint,
    day_chain_node_pairs,
    day_connector_adjacencies,
)
from travel_agent.planning.itinerary.draft import (
    AuthoredRoute,
    ChainNode,
    CompositionPlacement,
    DayComposition,
    ItineraryCompositionDraft,
    ItineraryCompositionError,
    LodgingBoundary,
    TransportPlacement,
    _stable_id,
    placement_occurrence_key,
)
from travel_agent.planning.research.candidates import (
    ResearchCandidate,
    TransportCandidate,
)
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.transport import TransportEndpoint
from travel_agent.schema import StrictModel


logger = logging.getLogger(__name__)


FlexibleRouteMode = Literal["walk", "bike", "drive", "taxi", "ride_hailing"]


_FLEXIBLE_ROUTE_MODES = {"walk", "bike", "drive", "taxi", "ride_hailing"}


class LocalConnectorGap(StrictModel):
    """相邻两个实体落位之间需要补的一段市内路线。"""

    gap_id: str = Field(min_length=1)
    day_id: str = Field(min_length=1)
    day_date: date
    destination_id: str = Field(min_length=1)
    from_entry_key: str = Field(min_length=1)
    from_place_id: str = Field(min_length=1)
    to_entry_key: str = Field(min_length=1)
    to_place_id: str = Field(min_length=1)
    departure_time: datetime
    latest_arrival_time: datetime
    allowed_transport_classes: list[Literal["public_transit", "flexible"]] = Field(
        min_length=1, max_length=2
    )
    requested_flexible_modes: list[FlexibleRouteMode] = Field(default_factory=list)
    preferred_transport_class: Literal["public_transit", "flexible"]
    weather_data_revision: int = Field(ge=0)
    from_endpoint: Optional[TransportEndpoint] = None
    to_endpoint: Optional[TransportEndpoint] = None

    @model_validator(mode="after")
    def validate_gap(self) -> "LocalConnectorGap":
        if self.from_entry_key == self.to_entry_key:
            raise ValueError("connector gap requires two distinct entries")
        if self.from_place_id == self.to_place_id:
            raise ValueError("connector gap requires two distinct place ids")
        if len(self.allowed_transport_classes) != len(
            set(self.allowed_transport_classes)
        ):
            raise ValueError("connector gap transport classes must be unique")
        if self.preferred_transport_class not in self.allowed_transport_classes:
            raise ValueError("preferred connector class must be allowed")
        if (
            "flexible" in self.allowed_transport_classes
            and not self.requested_flexible_modes
        ):
            raise ValueError("flexible connector requires an explicit requested mode")
        if (
            "flexible" not in self.allowed_transport_classes
            and self.requested_flexible_modes
        ):
            raise ValueError("flexible modes require the flexible transport class")
        if (
            self.departure_time.utcoffset() is None
            or self.latest_arrival_time.utcoffset() is None
        ):
            raise ValueError(
                "connector gap times must include the destination UTC offset"
            )
        if (
            self.departure_time.date() != self.day_date
            or self.latest_arrival_time.date() != self.day_date
            or self.latest_arrival_time <= self.departure_time
        ):
            raise ValueError("connector gap window must be ordered within its Day")
        return self


def extract_local_connector_gaps(
    skeleton: ItineraryCompositionDraft,
    catalog: RecommendationCatalog,
    *,
    weather_data_revision: int,
    flexible_mode_requests: Optional[
        dict[tuple[str, str], list[FlexibleRouteMode]]
    ] = None,
    required_flexible_mode_pairs: Optional[set[tuple[str, str]]] = None,
) -> list[LocalConnectorGap]:
    """按落位顺序推导每个相邻实体之间需要补的市内路线。"""
    candidates = catalog.candidate_index()
    requests = flexible_mode_requests or {}
    required_pairs = required_flexible_mode_pairs or set()
    gaps: list[LocalConnectorGap] = []
    for day in skeleton.days:
        for (
            left,
            right,
            from_place_id,
            to_place_id,
            departure_time,
            latest_arrival_time,
        ) in day_connector_adjacencies(day, candidates, skeleton):
            left_key = placement_occurrence_key(day.day_id, left)
            right_key = placement_occurrence_key(day.day_id, right)
            if latest_arrival_time <= departure_time:
                raise ItineraryCompositionError(
                    f"day {day.day_id} connector gap {left_key} -> {right_key} leaves "
                    f"{(latest_arrival_time - departure_time).total_seconds() / 60:.0f}min "
                    f"between {departure_time.isoformat()} and "
                    f"{latest_arrival_time.isoformat()}; "
                    "a positive transfer window is required"
                )
            requested_modes = list(
                dict.fromkeys(requests.get((left_key, right_key), []))
            )
            pair = (left_key, right_key)
            flexible_required = pair in required_pairs
            if flexible_required and not requested_modes:
                raise ItineraryCompositionError(
                    f"day {day.day_id} requires an explicit flexible mode"
                )
            allowed_classes: list[Literal["public_transit", "flexible"]] = (
                [] if flexible_required else ["public_transit"]
            )
            if requested_modes:
                allowed_classes.append("flexible")
            gap_id = _stable_id(
                "connector_gap",
                day.day_id,
                left_key,
                right_key,
            )
            gaps.append(
                LocalConnectorGap(
                    gap_id=gap_id,
                    day_id=day.day_id,
                    day_date=day.date,
                    destination_id=candidates[left.candidate_id].destination_id
                    if isinstance(left, LodgingBoundary)
                    else candidates[right.candidate_id].destination_id
                    if isinstance(right, LodgingBoundary)
                    else day.destination_id,
                    from_entry_key=left_key,
                    from_place_id=from_place_id,
                    from_endpoint=_chain_endpoint(left, candidates, leaving=True),
                    to_endpoint=_chain_endpoint(right, candidates, leaving=False),
                    to_entry_key=right_key,
                    to_place_id=to_place_id,
                    departure_time=departure_time,
                    latest_arrival_time=latest_arrival_time,
                    allowed_transport_classes=allowed_classes,
                    requested_flexible_modes=requested_modes,
                    preferred_transport_class=(
                        "flexible" if requested_modes else "public_transit"
                    ),
                    weather_data_revision=weather_data_revision,
                )
            )
    return gaps


def connector_mode_requests_from_constraint_pack(
    skeleton: ItineraryCompositionDraft,
    constraint_pack: Mapping[str, Any] | None,
    catalog: Optional[RecommendationCatalog] = None,
) -> tuple[
    dict[tuple[str, str], list[FlexibleRouteMode]],
    set[tuple[str, str]],
]:
    """只把规范化的显式用户意图投影到实际骨架相邻关系上。"""
    adjacent_resources = {}
    for day in skeleton.days:
        adjacent_resources.update(
            (
                (
                    placement_occurrence_key(day.day_id, left),
                    placement_occurrence_key(day.day_id, right),
                ),
                (
                    getattr(left, "candidate_id", None),
                    getattr(right, "candidate_id", None),
                ),
            )
            for left, right in day_chain_node_pairs(
                day,
                catalog.candidate_index() if catalog is not None else None,
                skeleton if catalog is not None else None,
            )
        )
    actual_pairs = list(adjacent_resources)
    if not actual_pairs or not isinstance(constraint_pack, Mapping):
        return {}, set()
    items = [
        item
        for key in ("soft_preferences", "hard_constraints")
        for item in constraint_pack.get(key) or []
        if isinstance(item, Mapping)
        and item.get("status") == "active"
        and item.get("visibility") == "user_visible"
        and item.get("category") == "transport_constraint"
        # 记忆条目只能表达偏好，不能作为要求路线的授权。
        and any(
            isinstance(ref, Mapping)
            and ref.get("source")
            in {"memory_fact", "manual_profile", "session_anchor", "current_query"}
            for ref in item.get("source_refs") or []
        )
    ]
    # 优先级更高的来源最后应用，与约束规范化顺序一致。
    source_priority = {
        "memory_fact": 0,
        "manual_profile": 1,
        "session_anchor": 2,
        "current_query": 3,
    }

    def item_source_priority(item: Mapping[str, Any]) -> int:
        return max(
            (
                source_priority.get(str(ref.get("source")), -1)
                for ref in item.get("source_refs") or []
                if isinstance(ref, Mapping)
            ),
            default=-1,
        )

    items.sort(
        key=lambda item: (item_source_priority(item), str(item.get("updated_at") or ""))
    )
    requested: dict[tuple[str, str], list[FlexibleRouteMode]] = {}
    required: set[tuple[str, str]] = set()
    locked_by_pair: dict[tuple[str, str], str] = {}
    excluded: dict[tuple[str, str], set[str]] = {pair: set() for pair in actual_pairs}
    for item in items:
        params = item.get("params")
        if not isinstance(params, Mapping):
            continue
        raw_pair = (
            str(params.get("from_candidate_id") or ""),
            str(params.get("to_candidate_id") or ""),
        )
        # 端点不完整时不能匹配完整的相邻关系。
        target_pairs = (
            [
                pair
                for pair, resources in adjacent_resources.items()
                if resources == raw_pair
            ]
            if all(raw_pair)
            else actual_pairs
            if not any(raw_pair)
            else []
        )
        raw_preferred_modes = params.get("preferred_local_modes")
        if not isinstance(raw_preferred_modes, list):
            raw_preferred_modes = []
        raw_excluded_modes = params.get("excluded_local_modes")
        if not isinstance(raw_excluded_modes, list):
            raw_excluded_modes = []
        preferred_modes = [
            mode for mode in raw_preferred_modes if mode in _FLEXIBLE_ROUTE_MODES
        ]
        excluded_modes = {
            mode for mode in raw_excluded_modes if mode in _FLEXIBLE_ROUTE_MODES
        }
        locked_mode = str(params.get("locked_local_mode") or "")
        if locked_mode not in _FLEXIBLE_ROUTE_MODES:
            locked_mode = ""
        for pair in target_pairs:
            if excluded_modes:
                excluded[pair].update(excluded_modes)
                requested[pair] = [
                    mode
                    for mode in requested.get(pair, [])
                    if mode not in excluded[pair]
                ]
                if locked_by_pair.get(pair) in excluded[pair]:
                    required.discard(pair)
                    locked_by_pair.pop(pair, None)
            if locked_mode and locked_mode not in excluded[pair]:
                requested[pair] = [locked_mode]
                required.add(pair)
                locked_by_pair[pair] = locked_mode
            elif pair not in required:
                requested[pair] = list(
                    dict.fromkeys(
                        [
                            *[
                                mode
                                for mode in preferred_modes
                                if mode not in excluded[pair]
                            ],
                            *requested.get(pair, []),
                        ]
                    )
                )
    return (
        {pair: modes for pair, modes in requested.items() if modes},
        required,
    )


def _connector_options(
    candidates: Mapping[str, ResearchCandidate],
    gap: LocalConnectorGap,
) -> list[TransportCandidate]:
    """列出端点、类型与用户指定方式都匹配这段相邻关系的实测路线。"""
    options = []
    for candidate in candidates.values():
        if not isinstance(candidate, TransportCandidate):
            continue
        if candidate.transport_class == "long_distance":
            continue
        if candidate.transport_class not in gap.allowed_transport_classes:
            continue
        if candidate.destination_id != gap.destination_id:
            continue
        if (
            candidate.from_endpoint.place_id != gap.from_place_id
            or candidate.to_endpoint.place_id != gap.to_place_id
        ):
            continue
        if (
            candidate.transport_class == "flexible"
            and candidate.selected_mode.value not in set(gap.requested_flexible_modes)
        ):
            continue
        options.append(candidate)
    return options


def unfilled_connector_gaps(
    catalog: RecommendationCatalog,
    gaps: list[LocalConnectorGap],
) -> list[LocalConnectorGap]:
    """返回没有实测 provider 路线可用、需要撰写估算的相邻关系。"""
    candidates = catalog.candidate_index()
    unfilled: list[LocalConnectorGap] = []
    for gap in gaps:
        if _connector_options(candidates, gap):
            continue
        unfilled.append(gap)
        logger.info(
            "[connector] gap %s (%s -> %s) 没有匹配的实测路线，改用估算",
            gap.gap_id,
            gap.from_place_id,
            gap.to_place_id,
        )
    return unfilled


def materialize_skeleton_connectors(
    skeleton: ItineraryCompositionDraft,
    catalog: RecommendationCatalog,
    gaps: list[LocalConnectorGap],
    authored_routes: Mapping[str, AuthoredRoute],
) -> ItineraryCompositionDraft:
    candidates = catalog.candidate_index()
    gaps_by_pair = {
        (gap.day_id, gap.from_entry_key, gap.to_entry_key): gap for gap in gaps
    }
    if len(gaps_by_pair) != len(gaps):
        raise ItineraryCompositionError(
            "connector gaps must be unique per Day adjacency"
        )
    selected: dict[str, TransportCandidate | AuthoredRoute] = {}
    for gap in gaps:
        options = _connector_options(candidates, gap)
        if not options:
            authored = authored_routes.get(gap.gap_id)
            if authored is None:
                raise ItineraryCompositionError(
                    f"connector gap {gap.gap_id} has neither a Provider route nor an authored route"
                )
            selected[gap.gap_id] = authored
            continue
        options.sort(
            key=lambda candidate: (
                candidate.transport_class != gap.preferred_transport_class,
                candidate.duration_minutes,
                candidate.total_cost_cny is None,
                candidate.total_cost_cny or 0,
                candidate.candidate_id,
            )
        )
        selected[gap.gap_id] = options[0]

    updated_days: list[DayComposition] = []
    consumed: set[str] = set()
    for day in skeleton.days:
        adjacencies = day_connector_adjacencies(day, candidates, skeleton)
        successor = {
            placement_occurrence_key(day.day_id, left): right
            for left, right, *_endpoints in adjacencies
        }
        updated: list[CompositionPlacement] = []

        def append_connector(left: ChainNode, right: ChainNode) -> None:
            gap = gaps_by_pair.get(
                (
                    day.day_id,
                    placement_occurrence_key(day.day_id, left),
                    placement_occurrence_key(day.day_id, right),
                )
            )
            if gap is None:
                raise ItineraryCompositionError(
                    f"day {day.day_id} adjacency has no connector gap"
                )
            route = selected[gap.gap_id]
            updated.append(
                TransportPlacement(authored_route=route, connector_gap_id=gap.gap_id)
                if isinstance(route, AuthoredRoute)
                else TransportPlacement(
                    candidate_id=route.candidate_id, connector_gap_id=gap.gap_id
                )
            )
            consumed.add(gap.gap_id)

        for left, right, *_endpoints in adjacencies:
            if isinstance(left, LodgingBoundary):
                append_connector(left, right)
        for placement in day.placements:
            updated.append(placement)
            next_node = successor.get(placement_occurrence_key(day.day_id, placement))
            if next_node is None:
                continue
            append_connector(placement, next_node)
        updated_days.append(day.model_copy(update={"placements": updated}))
    if consumed != set(selected):
        raise ItineraryCompositionError("connector gaps do not match the skeleton")
    return skeleton.model_copy(update={"days": updated_days})
