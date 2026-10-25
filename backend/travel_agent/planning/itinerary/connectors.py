from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, Mapping, Optional

from pydantic import Field, model_validator

from travel_agent.entities.transport_semantics import nominal_service_day_conflict
from travel_agent.planning.itinerary.adjacency import (
    _chain_endpoint,
    day_chain_node_pairs,
    day_connector_adjacencies,
)
from travel_agent.planning.itinerary.bindings import _passed_candidates
from travel_agent.planning.itinerary.checks import (
    validate_itinerary_transport_topology,
    validate_placement_skeleton,
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

if TYPE_CHECKING:
    from travel_agent.entities.provider_evidence import ProviderRouteLegScope


logger = logging.getLogger(__name__)


FlexibleRouteMode = Literal["walk", "bike", "drive", "taxi", "ride_hailing"]


_FLEXIBLE_ROUTE_MODES = {"walk", "bike", "drive", "taxi", "ride_hailing"}


class LocalConnectorGap(StrictModel):
    """One exact missing route between adjacent physical skeleton placements."""

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
    compare_default_walk: bool = False
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
    required_candidate_kinds: Optional[set[str]] = None,
    required_long_distance_legs: Optional[list["ProviderRouteLegScope"]] = None,
    required_leg_scope_ids: Optional[dict[str, str]] = None,
    default_walk_day_ids: Optional[set[str]] = None,
) -> list[LocalConnectorGap]:
    """Derive exact ordered adjacency gaps from a validated placement skeleton."""
    validate_placement_skeleton(
        skeleton,
        catalog,
        required_candidate_kinds=required_candidate_kinds,
        required_long_distance_legs=required_long_distance_legs,
        required_leg_scope_ids=required_leg_scope_ids,
    )
    candidates = _passed_candidates(catalog)
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
            compare_walk = (
                day.day_id in (default_walk_day_ids or set())
                and not requested_modes
                and (left_key, right_key) not in required_pairs
            )
            if compare_walk:
                requested_modes = ["walk"]
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
                        "flexible"
                        if requested_modes and not compare_walk
                        else "public_transit"
                    ),
                    weather_data_revision=weather_data_revision,
                    compare_default_walk=compare_walk,
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
    """Project normalized explicit user intent onto actual skeleton adjacency only."""
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
                _passed_candidates(catalog) if catalog is not None else None,
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
        # Manual memory is a preference, not authorization to require a route.
        and any(
            isinstance(ref, Mapping)
            and ref.get("source")
            in {"memory_fact", "manual_profile", "session_anchor", "current_query"}
            for ref in item.get("source_refs") or []
        )
    ]
    # Apply higher-priority sources last, consistent with constraint normalization.
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
        # A partial endpoint is not a complete adjacency scope.
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


def connector_route_arrival(
    candidate: TransportCandidate,
    gap: LocalConnectorGap,
) -> datetime:
    # An explicit timetable wins; duration-only provider routes remain usable.
    if candidate.arrival_at is not None:
        return candidate.arrival_at
    return gap.departure_time + timedelta(minutes=candidate.duration_minutes)


def connector_candidate_quality_error(
    candidate: TransportCandidate,
    gap: LocalConnectorGap,
) -> Optional[str]:
    """Return a deterministic rejection reason for a route that cannot fill a gap."""
    if candidate.transport_class not in gap.allowed_transport_classes:
        return "transport_class_not_requested"
    if candidate.destination_id != gap.destination_id:
        return "destination_mismatch"
    if nominal_service_day_conflict(
        (segment.line_name for segment in candidate.segments), gap.departure_time.date()
    ):
        return "route_service_day_unverified"
    if (
        candidate.from_endpoint.place_id != gap.from_place_id
        or candidate.to_endpoint.place_id != gap.to_place_id
    ):
        return "endpoint_mismatch"
    if (
        candidate.transport_class == "flexible"
        and candidate.selected_mode.value not in set(gap.requested_flexible_modes)
    ):
        return "flexible_mode_not_requested"
    if (
        gap.compare_default_walk
        and candidate.selected_mode.value == "walk"
        and (
            candidate.distance_meters is None
            or not 0 < candidate.distance_meters <= 1000
            or not 0 < candidate.duration_minutes <= 15
        )
    ):
        return "outside_default_short_walk_limits"
    # Only intrinsically credible routes can establish a planning-window conflict.
    if candidate.duration_minutes <= 0 or candidate.duration_minutes > 360:
        return "local_route_duration_implausible"
    if candidate.distance_meters is not None:
        if candidate.distance_meters <= 0 or candidate.distance_meters > 150_000:
            return "local_route_distance_implausible"
        speed_kmh = candidate.distance_meters / 1000 / (candidate.duration_minutes / 60)
        speed_limits = {
            "walk": 12,
            "bike": 45,
            "drive": 180,
            "taxi": 180,
            "ride_hailing": 180,
        }
        limit = speed_limits.get(candidate.selected_mode.value, 220)
        if speed_kmh > limit:
            return "local_route_speed_implausible"
    if (candidate.departure_at is None) != (candidate.arrival_at is None):
        return "route_half_scheduled"
    if candidate.departure_at is not None and candidate.arrival_at is not None:
        if (
            candidate.departure_at.utcoffset() is None
            or candidate.arrival_at.utcoffset() is None
        ):
            return "route_timezone_missing"
        if (
            candidate.departure_at.date() != gap.day_date
            or candidate.arrival_at.date() != gap.day_date
            or candidate.departure_at.utcoffset() != gap.departure_time.utcoffset()
            or candidate.arrival_at.utcoffset() != gap.latest_arrival_time.utcoffset()
        ):
            return "route_day_or_timezone_mismatch"
        if candidate.arrival_at <= candidate.departure_at:
            return "route_schedule_implausible"
        if candidate.departure_at < gap.departure_time:
            return "route_departs_before_preceding_stop"
    if connector_route_arrival(candidate, gap) > gap.latest_arrival_time:
        return "route_arrives_after_following_stop"
    return None


def connector_gap_rejection_reasons(
    catalog: RecommendationCatalog,
    gap: LocalConnectorGap,
) -> dict[str, str]:

    reasons: dict[str, str] = {}
    for candidate_id, candidate in _passed_candidates(catalog).items():
        if not isinstance(candidate, TransportCandidate):
            continue
        if candidate.transport_class == "long_distance":
            continue
        reason = connector_candidate_quality_error(candidate, gap)
        if reason is not None:
            reasons[candidate_id] = reason
    return reasons


def _connector_options(
    candidates: Mapping[str, ResearchCandidate],
    gap: LocalConnectorGap,
) -> list[TransportCandidate]:
    options = []
    conflicts = {}
    for candidate in candidates.values():
        if not isinstance(candidate, TransportCandidate):
            continue
        reason = connector_candidate_quality_error(candidate, gap)
        if reason is None:
            options.append(candidate)
        elif reason in {
            "route_departs_before_preceding_stop",
            "route_arrives_after_following_stop",
        }:
            conflicts[candidate.candidate_id] = (
                f"{reason}, duration={candidate.duration_minutes}min"
            )
    usable = [
        option
        for option in options
        if not gap.compare_default_walk or option.transport_class == "public_transit"
    ]
    if not usable and conflicts:
        raise ItineraryCompositionError(
            f"connector {gap.gap_id} {gap.from_place_id} -> {gap.to_place_id} "
            f"window {gap.departure_time.isoformat()} -> "
            f"{gap.latest_arrival_time.isoformat()} conflicts with Provider routes: {conflicts}"
        )
    return options


def unfilled_connector_gaps(
    catalog: RecommendationCatalog,
    gaps: list[LocalConnectorGap],
) -> list[LocalConnectorGap]:
    """Return the adjacencies no admitted Provider route can currently fill."""
    candidates = _passed_candidates(catalog)
    unfilled: list[LocalConnectorGap] = []
    for gap in gaps:
        if any(
            not gap.compare_default_walk
            or candidate.transport_class == "public_transit"
            for candidate in _connector_options(candidates, gap)
        ):
            continue
        unfilled.append(gap)
        reasons = connector_gap_rejection_reasons(catalog, gap)
        logger.info(
            "[connector] gap %s (%s -> %s) unfilled; local route verdicts: %s",
            gap.gap_id,
            gap.from_place_id,
            gap.to_place_id,
            reasons or "no admitted local route at all",
        )
    return unfilled


def materialize_skeleton_connectors(
    skeleton: ItineraryCompositionDraft,
    catalog: RecommendationCatalog,
    gaps: list[LocalConnectorGap],
    authored_routes: Mapping[str, AuthoredRoute],
    *,
    required_candidate_kinds: Optional[set[str]] = None,
    required_long_distance_legs: Optional[list["ProviderRouteLegScope"]] = None,
    required_leg_scope_ids: Optional[dict[str, str]] = None,
) -> ItineraryCompositionDraft:
    validate_placement_skeleton(
        skeleton,
        catalog,
        required_candidate_kinds=required_candidate_kinds,
        required_long_distance_legs=required_long_distance_legs,
        required_leg_scope_ids=required_leg_scope_ids,
    )
    candidates = _passed_candidates(catalog)
    gaps_by_pair = {
        (gap.day_id, gap.from_entry_key, gap.to_entry_key): gap for gap in gaps
    }
    if len(gaps_by_pair) != len(gaps):
        raise ItineraryCompositionError(
            "connector gaps must be unique per Day adjacency"
        )
    selected: dict[str, TransportCandidate | AuthoredRoute] = {}
    walking_minutes_by_day: dict[str, int] = {}
    for gap in gaps:
        options = _connector_options(candidates, gap)
        if gap.compare_default_walk:
            transit = [
                option
                for option in options
                if option.transport_class == "public_transit"
            ]
            fastest = min((option.duration_minutes for option in transit), default=None)
            options = [
                option
                for option in options
                if option.selected_mode.value != "walk"
                or (
                    fastest is not None
                    and option.duration_minutes <= fastest
                    and walking_minutes_by_day.get(gap.day_id, 0)
                    + option.duration_minutes
                    <= 30
                )
            ]
        if not options:
            authored = authored_routes.get(gap.gap_id)
            if authored is None:
                raise ItineraryCompositionError(
                    f"connector gap {gap.gap_id} has neither a Provider route nor an authored route"
                )
            if gap.compare_default_walk and authored.mode == "walk":
                raise ItineraryCompositionError(
                    f"connector {gap.gap_id} default walking requires measured walking and transit evidence"
                )
            if (
                gap.departure_time + timedelta(minutes=authored.duration_minutes)
                > gap.latest_arrival_time
            ):
                raise ItineraryCompositionError(
                    f"authored connector {gap.gap_id} cannot fit its planning window"
                )
            selected[gap.gap_id] = authored
            continue
        options.sort(
            key=lambda candidate: (
                (candidate.selected_mode.value != "walk")
                if gap.compare_default_walk
                else candidate.transport_class != gap.preferred_transport_class,
                candidate.duration_minutes,
                candidate.total_cost_cny is None,
                candidate.total_cost_cny or 0,
                candidate.candidate_id,
            )
        )
        selected[gap.gap_id] = options[0]
        if gap.compare_default_walk and options[0].selected_mode.value == "walk":
            walking_minutes_by_day[gap.day_id] = (
                walking_minutes_by_day.get(gap.day_id, 0) + options[0].duration_minutes
            )

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
    composition = skeleton.model_copy(update={"days": updated_days})
    validate_itinerary_transport_topology(
        composition,
        catalog,
        required_candidate_kinds=required_candidate_kinds,
        required_long_distance_legs=required_long_distance_legs,
        required_leg_scope_ids=required_leg_scope_ids,
    )
    return composition
