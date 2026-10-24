"""Pure, evidence-backed spatial and experience comparisons for selection.

Distances are geographic lower bounds, never route times. Relative comparisons
use this destination's candidate pool, without city-wide kilometre thresholds
or any provider calls. Missing coordinates remain an explicit uncertainty.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Iterable

from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.catalog import RecommendationCatalog

from ..entities.intent_spec import IntentKind, IntentSpec, IntentTarget
from .geo_dispersion import haversine_km, verified_coordinate_pair


def candidate_coordinates(
    catalog: RecommendationCatalog,
) -> dict[str, tuple[float, float] | None]:
    facts = {
        fact.fact_assertion_id: fact
        for packet in catalog.research_packets
        for fact in packet.fact_assertions
    }
    result = {}
    for candidate_id, candidate in catalog.candidate_index().items():
        latitude, longitude = verified_coordinate_pair(
            candidate.fact_assertion_ids, facts
        )
        result[candidate_id] = (
            (latitude, longitude)
            if latitude is not None and longitude is not None
            else None
        )
    return result


def experience_signature(candidate: ResearchCandidate) -> tuple[str, ...]:
    if candidate.candidate_kind == "visit":
        return (candidate.visit_type, candidate.provider_place_type.casefold())
    if candidate.candidate_kind == "dining":
        return tuple(
            sorted(cuisine.casefold() for cuisine in candidate.cuisine_types)
        ) or (candidate.provider_place_type.casefold(),)
    return (candidate.candidate_kind,)


def wants_diversity(intent_spec: IntentSpec, candidate: ResearchCandidate) -> bool:
    return any(
        intent.kind is IntentKind.DIVERSITY
        and intent.target.value
        in {
            candidate.candidate_kind,
            IntentTarget.TRIP.value,
            IntentTarget.ITINERARY.value,
        }
        for intent in intent_spec.active_items
    )


class CandidateCombinationContext:
    def __init__(
        self,
        catalog: RecommendationCatalog,
        intent_spec: IntentSpec,
        eligible_ids: Iterable[str],
    ):
        self.candidates = catalog.candidate_index()
        self.coordinates = candidate_coordinates(catalog)
        self.intent_spec = intent_spec
        eligible = set(eligible_ids)
        self.groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.anchors: dict[str, tuple[float, float]] = {}
        points: dict[str, list[tuple[float, float]]] = defaultdict(list)
        lodging: dict[str, list[tuple[float, float]]] = defaultdict(list)
        selected_lodging: dict[str, list[tuple[float, float]]] = defaultdict(list)
        selected_ids = {
            result.candidate_id
            for result in catalog.admission_results
            if result.status == "passed" and result.selection_slot_id is not None
        }
        for candidate_id in sorted(eligible):
            candidate = self.candidates[candidate_id]
            self.groups[(candidate.candidate_kind, candidate.destination_id)].append(
                candidate_id
            )
            point = self.coordinates[candidate_id]
            if point is not None and candidate.candidate_kind != "transport":
                if candidate.candidate_kind == "lodging":
                    lodging[candidate.destination_id].append(point)
                    if candidate_id in selected_ids:
                        selected_lodging[candidate.destination_id].append(point)
                else:
                    points[candidate.destination_id].append(point)
        for destination_id in points.keys() | lodging.keys():
            anchor_points = (
                selected_lodging.get(destination_id)
                or points.get(destination_id)
                or lodging[destination_id]
            )
            self.anchors[destination_id] = (
                median(p[0] for p in anchor_points),
                median(p[1] for p in anchor_points),
            )
        self.distances: dict[str, float | None] = {}
        self.signature_counts = {}
        self.place_counts = {}
        for group, candidate_ids in self.groups.items():
            self.signature_counts[group] = Counter(
                experience_signature(self.candidates[candidate_id])
                for candidate_id in candidate_ids
            )
            self.place_counts[group] = Counter(
                getattr(self.candidates[candidate_id], "place_id", None)
                for candidate_id in candidate_ids
            )
            for candidate_id in candidate_ids:
                point = self.coordinates[candidate_id]
                anchor = self.anchors.get(group[1])
                self.distances[candidate_id] = (
                    haversine_km(*point, *anchor)
                    if point is not None and anchor is not None
                    else None
                )

    def ranking_features(self, candidate_id: str) -> tuple[float, float, float, float]:
        candidate = self.candidates[candidate_id]
        group = (candidate.candidate_kind, candidate.destination_id)
        peers = self.groups.get(group, [])
        # Ranking also emits diagnostic scores for rejected candidates. They
        # must not enter the eligible pool's spatial or experience statistics,
        # even when eligible peers exist in the same destination/kind group.
        if candidate_id not in self.distances or not peers or candidate.candidate_kind == "transport":
            return 0.0, 0.0, 0.0, 0.0
        distance = self.distances[candidate_id]
        known = [
            self.distances[peer] for peer in peers if self.distances[peer] is not None
        ]
        # Strictly greater distances rank worse; ties remain ties. Unknown is
        # assigned the uncertainty ceiling rather than an invented zero cost.
        penalty = (
            sum(value < distance for value in known) / len(known)
            if distance is not None and known
            else 1.0
        )
        diversity = (
            1 / self.signature_counts[group][experience_signature(candidate)]
            if wants_diversity(self.intent_spec, candidate)
            else 0.0
        )
        duplicate_count = self.place_counts[group][candidate.place_id]
        redundancy = 1 - 1 / duplicate_count
        return 1 - penalty, diversity, redundancy, penalty

    def marginal_key(
        self, candidate_id: str, selected: Iterable[str]
    ) -> tuple[float, float, float]:
        candidate = self.candidates[candidate_id]
        peers = [
            self.candidates[peer]
            for peer in selected
            if self.candidates[peer].destination_id == candidate.destination_id
            and self.candidates[peer].candidate_kind != "transport"
        ]
        point = self.coordinates[candidate_id]
        located = [
            self.coordinates[peer.candidate_id]
            for peer in peers
            if self.coordinates[peer.candidate_id] is not None
        ]
        nearest = (
            min(haversine_km(*point, *other) for other in located)
            if point is not None and located
            else self.distances.get(candidate_id)
        )
        same_kind = [
            peer for peer in peers if peer.candidate_kind == candidate.candidate_kind
        ]
        repeated = any(
            experience_signature(peer) == experience_signature(candidate)
            for peer in same_kind
        )
        return (
            float(wants_diversity(self.intent_spec, candidate) and repeated),
            float(nearest is None),
            nearest if nearest is not None else 0.0,
        )

    def repeats_place(self, candidate_id: str, selected: Iterable[str]) -> bool:
        candidate = self.candidates[candidate_id]
        place_id = getattr(candidate, "place_id", None)
        return bool(place_id) and any(
            self.candidates[peer].candidate_kind == candidate.candidate_kind
            and getattr(self.candidates[peer], "place_id", None) == place_id
            for peer in selected
        )
