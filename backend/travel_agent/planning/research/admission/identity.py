"""Planning research admission identity."""

from __future__ import annotations

from datetime import datetime
from travel_agent.integrations.places.taxonomy import _is_dining_provider_type
from travel_agent.integrations.places.taxonomy import _is_lodging_provider_type
from travel_agent.integrations.places.taxonomy import is_administrative_provider_type
from travel_agent.planning.requirements.destination_scope import is_within_destination
from travel_agent.planning.research.admission.evidence import _fact_value_matches
from travel_agent.planning.research.admission.evidence import (
    _missing_identity_provenance_binding,
)
from travel_agent.planning.research.admission.evidence import (
    fact_has_compiled_tool_source_support,
)
from travel_agent.planning.research.candidates import DiningCandidate
from travel_agent.planning.research.candidates import LodgingCandidate
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.candidates import VisitCandidate
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.research.provider_contracts import (
    TIMETABLED_TRANSPORT_CLASSES,
)
from typing import Any
from typing import Mapping
from typing import Optional
from typing import Sequence


_UNKNOWN_IDENTITY_MARKERS = (
    "unknown",
    "not verified",
    "unverified",
    "reference only",
    "placeholder",
    "no verified specific",
    "未检索",
    "未确认",
    "待确认",
    "不详",
    "未確認",
)


def _missing_concrete_identity_fields(
    candidate: ResearchCandidate,
    identity_fact_values: Mapping[str, Sequence[Any]],
    *,
    candidate_facts: Sequence[FactAssertion],
    source_records: Sequence[SourceRecord],
) -> list[str]:
    """Every required identity field this candidate cannot honestly claim.

    Two layers answer that.  ``_missing_declared_identity_fields`` asks whether
    the candidate's own fields are concrete and are what its facts assert — a
    self-consistency check over the model's output.  The identity provenance
    binding then asks the question self-consistency cannot: was this entity
    *ever returned by a Provider*?  A wholly invented place or route can be
    perfectly self-consistent, so the binding is what keeps it out.
    """

    missing = _missing_declared_identity_fields(
        candidate,
        identity_fact_values,
        candidate_facts=candidate_facts,
        source_records=source_records,
    )
    unbound_identity_field = _missing_identity_provenance_binding(
        candidate,
        candidate_facts=candidate_facts,
        source_records=source_records,
    )
    if unbound_identity_field is not None and unbound_identity_field not in missing:
        missing.append(unbound_identity_field)
    return missing


def _missing_declared_identity_fields(
    candidate: ResearchCandidate,
    identity_fact_values: Mapping[str, Sequence[Any]],
    *,
    candidate_facts: Sequence[FactAssertion],
    source_records: Sequence[SourceRecord],
) -> list[str]:
    missing: list[str] = []
    required: tuple[tuple[str, Any], ...]
    if isinstance(candidate, LodgingCandidate):
        required = (
            ("property_name", candidate.property_name),
            ("place_id", candidate.place_id),
            ("provider_place_type", candidate.provider_place_type),
            ("provider_country_code", candidate.provider_country_code),
            ("address", candidate.address),
        )
    elif isinstance(candidate, DiningCandidate):
        required = (
            ("branch_name", candidate.branch_name),
            ("place_id", candidate.place_id),
            ("provider_place_type", candidate.provider_place_type),
            ("provider_country_code", candidate.provider_country_code),
            ("address", candidate.address),
        )
    elif isinstance(candidate, VisitCandidate):
        required = (
            ("name", candidate.name),
            ("place_id", candidate.place_id),
            ("provider_place_type", candidate.provider_place_type),
            ("provider_country_code", candidate.provider_country_code),
            ("address", candidate.address),
        )
    elif isinstance(candidate, TransportCandidate):
        required_values: list[tuple[str, Any]] = [
            ("route_id", candidate.route_id),
            ("selected_mode", candidate.selected_mode.value),
            ("duration_minutes", candidate.duration_minutes),
            (
                "segments",
                [segment.model_dump(mode="json") for segment in candidate.segments],
            ),
        ]
        if candidate.transport_class in TIMETABLED_TRANSPORT_CLASSES:
            required_values.extend(
                [
                    (
                        "departure_at",
                        candidate.departure_at,
                    ),
                    (
                        "arrival_at",
                        candidate.arrival_at,
                    ),
                ]
            )
        route_id = candidate.route_id.strip()

        route_is_bound = bool(route_id) and any(
            fact.field_path == "route_id"
            and fact.entity_ref.entity_id == candidate.candidate_id
            and _fact_value_matches(fact.asserted_value, route_id)
            and fact_has_compiled_tool_source_support(
                fact,
                source_records=source_records,
                required_entity_id=route_id,
            )
            for fact in candidate_facts
        )
        for field_path, value in required_values:
            if (
                value is None
                or (
                    field_path in {"departure_at", "arrival_at"}
                    and isinstance(value, datetime)
                    and value.utcoffset() is None
                )
                or not any(
                    _fact_value_matches(asserted, value)
                    for asserted in identity_fact_values.get(field_path, ())
                )
            ):
                missing.append(field_path)
                continue

            if not route_is_bound:
                continue
            if not any(
                fact.field_path == field_path
                and fact.entity_ref.entity_id == candidate.candidate_id
                and _fact_value_matches(fact.asserted_value, value)
                and fact_has_compiled_tool_source_support(
                    fact,
                    source_records=source_records,
                    required_entity_id=route_id,
                )
                for fact in candidate_facts
            ):
                missing.append(field_path)
        return missing
    else:
        return missing
    for field_path, value in required:
        normalized = value.strip().lower() if isinstance(value, str) else value
        if isinstance(normalized, str) and (
            not normalized
            or any(marker in normalized for marker in _UNKNOWN_IDENTITY_MARKERS)
        ):
            missing.append(field_path)
            continue
        if not any(
            _fact_value_matches(asserted, value)
            for asserted in identity_fact_values.get(field_path, ())
        ):
            missing.append(field_path)

    if (
        isinstance(candidate, DiningCandidate)
        and "provider_place_type" not in missing
        and not _is_dining_provider_type(candidate.provider_place_type)
    ):
        missing.append("provider_place_type")
    if (
        isinstance(candidate, LodgingCandidate)
        and "provider_place_type" not in missing
        and not _is_lodging_provider_type(candidate.provider_place_type)
    ):
        missing.append("provider_place_type")

    if (
        isinstance(candidate, VisitCandidate)
        and "provider_place_type" not in missing
        and is_administrative_provider_type(candidate.provider_place_type)
    ):
        missing.append("provider_place_type")
    return missing


DETERMINISTIC_IDENTITY_VERDICT_FIELD_PATHS = frozenset({"place_id.destination_scope"})


def _out_of_destination_identity_fields(
    candidate: ResearchCandidate,
    *,
    destination_point: Optional[tuple[float, float]],
    identity_fact_values: Mapping[str, Sequence[Any]],
) -> list[str]:
    """Reject a located place that is not a stop in the destination it claims.

    The backstop half of the destination-scope rule.  The enum a worker selects from
    already drops far places (``planning.research.output.options._eligible_place_selection_options``),
    which is the half that keeps the *near* one instead of losing both; this half catches
    any path that reaches admission without having gone through that enum.

    **A rejection, not a fit score.**  Country scope right above is only a ranking
    signal, and composition does not act on rankings: every slot's option count is
    ``1 + (candidates − placed)``, so composition places every candidate it is given.
    A low ``constraint_fit`` would therefore change nothing at all.

    Coordinates come from the candidate's own verified identity facts, the same
    pair the map is drawn from.  No point on either side means the rule has
    nothing to say and the candidate passes — a destination whose geocode is
    missing is a supply outage, not a city full of out-of-scope places.
    """
    if destination_point is None:
        return []
    if not isinstance(candidate, (DiningCandidate, LodgingCandidate, VisitCandidate)):
        return []
    values: dict[str, float] = {}
    for field_path in ("latitude", "longitude"):
        for asserted in identity_fact_values.get(field_path, ()):
            if isinstance(asserted, bool) or not isinstance(asserted, (int, float)):
                continue
            values[field_path] = float(asserted)
            break
    if set(values) != {"latitude", "longitude"}:
        return []
    if is_within_destination(
        values["latitude"],
        values["longitude"],
        destination_point[0],
        destination_point[1],
    ):
        return []
    return sorted(DETERMINISTIC_IDENTITY_VERDICT_FIELD_PATHS)
