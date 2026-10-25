"""Research packet options responsibilities."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from travel_agent.entities.provider_evidence import (
    ProviderEvidenceAssignment,
    ProviderEvidenceOutcome,
    ProviderEvidenceScope,
)
from travel_agent.knowledge.place_mentions import PlaceLookup, ProviderIdentity
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.services.candidate_admission import (
    provider_place_type_matches_candidate_kind,
)
from travel_agent.services.destination_scope import (
    DESTINATION_DISTANCE_KEY,
    MAX_DESTINATION_DISTANCE_KM,
)

from .identifiers import _provider_candidate_id
from .policy import _PLACE_IDENTITY_FIELDS, _WORKER_CANDIDATE_MODELS, ResearchWorkerKind
from .transcript import (
    _parse_tool_envelope,
    _successful_place_records,
    _successful_route_records,
)

logger = logging.getLogger(__name__)


def _eligible_route_selection_options(
    context_messages: Sequence[Mapping[str, Any]],
    *,
    required_transport_classes: Sequence[str] | None,
    excluded_candidate_ids: Sequence[str] | None,
    required_route_scopes: Sequence[ProviderEvidenceScope] = (),
) -> list[dict[str, Any]]:
    required = set(required_transport_classes or ())
    excluded = set(excluded_candidate_ids or ())
    scopes_by_date: dict[date, list[ProviderEvidenceScope]] = {}
    for scope in required_route_scopes:
        if scope.transport_class == "long_distance" and scope.route_leg is not None:
            scopes_by_date.setdefault(scope.route_leg.service_date, []).append(scope)
    date_route_index: dict[date, int] = {}
    options: list[dict[str, Any]] = []
    for route_id, (envelope, route, _) in _successful_route_records(
        context_messages
    ).items():
        transport_class = str(route["transport_class"])
        candidate_id = _provider_candidate_id("transport", route_id)
        if (required and transport_class not in required) or candidate_id in excluded:
            continue
        provider_scope_id: str | None = None
        if transport_class == "long_distance":
            departure_at = route.get("departure_at")
            try:
                service_date = datetime.fromisoformat(
                    str(departure_at).replace("Z", "+00:00")
                ).date()
            except (TypeError, ValueError):
                continue
            if required_route_scopes:
                scopes_today = scopes_by_date.get(service_date, [])
                if not scopes_today:
                    continue
                index = date_route_index.get(service_date, 0)
                date_route_index[service_date] = index + 1
                provider_scope_id = scopes_today[index % len(scopes_today)].scope_id
        options.append(
            {
                "route_id": route_id,
                "transport_class": transport_class,
                "selected_mode": str(route["selected_mode"]),
                "from_endpoint": route["from_endpoint"],
                "to_endpoint": route["to_endpoint"],
                "duration_minutes": route["duration_minutes"],
                "audit_id": str(envelope.get("audit_id") or ""),
                "provider_evidence_scope_id": provider_scope_id,
            }
        )
    return options


def has_provider_route_selection_option(
    context_messages: Sequence[Mapping[str, Any]],
    *,
    required_transport_classes: Sequence[str] | None,
    excluded_candidate_ids: Sequence[str] | None = None,
    required_route_scopes: Sequence[ProviderEvidenceScope] = (),
) -> bool:
    "Return whether one complete Provider route can close this scoped round."
    return bool(
        _eligible_route_selection_options(
            context_messages,
            required_transport_classes=required_transport_classes,
            excluded_candidate_ids=excluded_candidate_ids,
            required_route_scopes=required_route_scopes,
        )
    )


def has_required_provider_route_selection_options(
    context_messages: Sequence[Mapping[str, Any]],
    *,
    required_transport_classes: Sequence[str] | None,
    excluded_candidate_ids: Sequence[str] | None = None,
    required_route_scopes: Sequence[ProviderEvidenceScope] = (),
) -> bool:
    "Require one eligible Provider option for every assigned exact route leg."
    options = _eligible_route_selection_options(
        context_messages,
        required_transport_classes=required_transport_classes,
        excluded_candidate_ids=excluded_candidate_ids,
        required_route_scopes=required_route_scopes,
    )
    expected_scope_ids = {
        scope.scope_id
        for scope in required_route_scopes
        if scope.transport_class == "long_distance"
    }
    if not expected_scope_ids:
        return bool(options)
    option_scope_ids = {
        str(option.get("provider_evidence_scope_id") or "") for option in options
    }
    return expected_scope_ids <= option_scope_ids


def _eligible_place_selection_options(
    context_messages: Sequence[Mapping[str, Any]],
    expected_worker: ResearchWorkerKind,
    *,
    excluded_candidate_ids: Sequence[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    "Compile the bounded Provider result set the Worker may explicitly select."
    forbidden = set(excluded_candidate_ids or ())
    allowed_kinds = {
        candidate_kind
        for candidate_kind, _ in _WORKER_CANDIDATE_MODELS[expected_worker]
        if candidate_kind in _PLACE_IDENTITY_FIELDS
    }
    options: dict[str, list[dict[str, str]]] = {
        candidate_kind: [] for candidate_kind in allowed_kinds
    }
    seen: set[tuple[str, str]] = set()
    dropped_far: list[tuple[str, float]] = []
    for envelope, provider_place, _ in _successful_place_records(
        context_messages
    ).values():
        audit_id = str(envelope.get("audit_id") or "").strip()
        if not audit_id:
            continue
        distance = provider_place.get(DESTINATION_DISTANCE_KEY)
        if isinstance(distance, (int, float)) and not isinstance(distance, bool):
            if float(distance) > MAX_DESTINATION_DISTANCE_KM:
                dropped_far.append((str(provider_place["name"]), float(distance)))
                continue
        provider_type = str(provider_place["provider_place_type"])
        for candidate_kind in allowed_kinds:
            key = (candidate_kind, str(provider_place["place_id"]))
            if key in seen or not provider_place_type_matches_candidate_kind(
                provider_type,
                candidate_kind,
            ):
                continue
            if (
                _provider_candidate_id(candidate_kind, str(provider_place["place_id"]))
                in forbidden
            ):
                continue
            result = envelope.get("sanitized_result")
            provider_query = (
                str(result.get("query") or "").strip()
                if isinstance(result, Mapping)
                else ""
            )
            options[candidate_kind].append(
                {
                    "candidate_kind": candidate_kind,
                    "place_id": str(provider_place["place_id"]),
                    "name": str(provider_place["name"]),
                    "provider_place_type": provider_type,
                    "provider_country_code": str(
                        provider_place["provider_country_code"]
                    ),
                    "audit_id": audit_id,
                    "provider_query": provider_query,
                }
            )
            seen.add(key)
    if dropped_far:
        emptied = sorted(kind for kind in allowed_kinds if not options[kind])
        logger.info(
            "Place options outside destination | dropped=%s%s",
            ", ".join(f"{name}@{km:.1f}km" for name, km in dropped_far),
            f" emptied={emptied}" if emptied else "",
        )
    return options


def _has_eligible_place_selection(
    options: Mapping[str, Sequence[Mapping[str, str]]],
) -> bool:
    return any(options.values())


@dataclass(frozen=True)
class ObservedPlaceNominations:
    """Observed provider lookups and selectable identities for one research round."""

    lookups: tuple[PlaceLookup, ...]
    selectable_place_ids: tuple[str, ...]


def observed_place_nominations(
    context_messages: Sequence[Mapping[str, Any]],
    *,
    expected_worker: ResearchWorkerKind,
) -> ObservedPlaceNominations:
    "What this round asked the place Provider, got back, and may select from."
    lookups: list[PlaceLookup] = []
    for message in context_messages:
        envelope = _parse_tool_envelope(message)
        if envelope is None or envelope.get("tool_name") != "global_place_search":
            continue
        result = envelope.get("sanitized_result")
        if not isinstance(result, Mapping):
            continue
        query = result.get("query")
        if not isinstance(query, str) or not query.strip():
            continue
        identities: list[ProviderIdentity] = []
        provider_results = result.get("results")
        if isinstance(provider_results, Sequence) and not isinstance(
            provider_results, str
        ):
            for item in provider_results:
                if not isinstance(item, Mapping):
                    continue
                place_id, name = item.get("place_id"), item.get("name")
                if not (isinstance(place_id, str) and place_id.strip()):
                    continue
                identities.append(
                    ProviderIdentity(
                        place_id=place_id,
                        name=name
                        if isinstance(name, str) and name.strip()
                        else place_id,
                    )
                )
        lookups.append(PlaceLookup(query=query, identities=tuple(identities)))
    options = _eligible_place_selection_options(context_messages, expected_worker)
    return ObservedPlaceNominations(
        lookups=tuple(lookups),
        selectable_place_ids=tuple(
            dict.fromkeys(
                str(option["place_id"])
                for kind_options in options.values()
                for option in kind_options
                if option.get("place_id")
            )
        ),
    )


def has_required_provider_place_selection(
    context_messages: Sequence[Mapping[str, Any]],
    *,
    expected_worker: ResearchWorkerKind,
    required_candidate_kinds: Sequence[str],
) -> bool:
    "Return whether every requested place domain already has a Provider option."
    options = _eligible_place_selection_options(context_messages, expected_worker)
    return all(
        options.get(candidate_kind) for candidate_kind in required_candidate_kinds
    )


def provider_evidence_outcomes(
    context_messages: Sequence[Mapping[str, Any]],
    *,
    expected_worker: ResearchWorkerKind,
    packet: ResearchPacket | None,
    assignments: Sequence[ProviderEvidenceAssignment],
) -> dict[str, ProviderEvidenceOutcome]:
    "Project one worker attempt into independently resolvable scope outcomes."
    if any(
        assignment.scope.worker_kind != expected_worker for assignment in assignments
    ):
        raise ValueError("Provider evidence assignment belongs to another worker")
    place_options = (
        _eligible_place_selection_options(context_messages, expected_worker)
        if expected_worker != "transport_researcher"
        else {}
    )
    route_options = (
        _eligible_route_selection_options(
            context_messages,
            required_transport_classes=None,
            excluded_candidate_ids=None,
            required_route_scopes=[
                assignment.scope
                for assignment in assignments
                if assignment.scope.route_leg is not None
            ],
        )
        if expected_worker == "transport_researcher"
        else []
    )
    source_by_id = (
        {source.source_record_id: source for source in packet.source_records}
        if packet is not None
        else {}
    )

    def is_provider_materialized(candidate: Any) -> bool:
        return any(
            source_by_id.get(source_id) is not None
            and source_by_id[source_id].tool_audit_id
            for source_id in candidate.source_record_ids
        )

    outcomes: dict[str, ProviderEvidenceOutcome] = {}
    for assignment in assignments:
        scope = assignment.scope
        if scope.transport_class is not None:
            option_count = sum(
                option.get("transport_class") == scope.transport_class
                and (
                    scope.transport_class != "long_distance"
                    or option.get("provider_evidence_scope_id") == scope.scope_id
                )
                for option in route_options
            )
            materialized_count = sum(
                candidate.candidate_kind == "transport"
                and candidate.transport_class == scope.transport_class
                and (
                    scope.transport_class != "long_distance"
                    or candidate.provider_evidence_scope_id == scope.scope_id
                )
                and is_provider_materialized(candidate)
                for candidate in (packet.candidates if packet is not None else ())
            )
        else:
            candidate_kind = scope.candidate_kind
            option_count = len(place_options.get(candidate_kind or "", ()))
            materialized_count = sum(
                candidate.candidate_kind == candidate_kind
                and is_provider_materialized(candidate)
                for candidate in (packet.candidates if packet is not None else ())
            )
        if materialized_count:
            status = "materialized"
            unresolved_loss_count = 0
        elif option_count:
            status = "unresolved_loss"
            unresolved_loss_count = option_count
        else:
            status = "no_option"
            unresolved_loss_count = 0
        outcomes[scope.scope_id] = ProviderEvidenceOutcome(
            scope=scope,
            attempt_number=assignment.attempt_number,
            provider_option_count=option_count,
            provider_option_materialized_count=materialized_count,
            unresolved_loss_count=unresolved_loss_count,
            status=status,
        )
    return outcomes
