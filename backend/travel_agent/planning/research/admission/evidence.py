"""Planning research admission evidence."""

from __future__ import annotations

from datetime import datetime
from travel_agent.planning.research.candidates import DiningCandidate
from travel_agent.planning.research.candidates import LodgingCandidate
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.candidates import TransportCandidate
from travel_agent.planning.research.candidates import VisitCandidate
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.tools.governance import compiled_tool_source_id_is_about
from typing import Any
from typing import Iterable
from typing import Mapping
from typing import Optional
from typing import Sequence
import re


DYNAMIC_FACT_FIELD_MARKERS = frozenset(
    {
        "availability",
        "inventory",
        "price",
        "spend",
        "cost",
        "fare",
        "route",
        "departure",
        "arrival",
        "duration",
        "schedule",
        "time_window",
        "weather_context",
    }
)


def is_dynamic_fact_field(field_path: str) -> bool:
    """Return whether a persisted Fact describes a volatile live option."""

    normalized = str(field_path or "").casefold()
    return any(marker in normalized for marker in DYNAMIC_FACT_FIELD_MARKERS)


def _identity_value_matches(asserted: Any, expected: str) -> bool:
    if not isinstance(asserted, str):
        return False
    return (
        " ".join(asserted.split()).casefold() == " ".join(expected.split()).casefold()
    )


def _fact_value_matches(asserted: Any, expected: Any) -> bool:
    if isinstance(expected, datetime):
        if not isinstance(asserted, str):
            return False
        try:
            parsed = datetime.fromisoformat(asserted.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed == expected
    if isinstance(expected, str):
        return _identity_value_matches(asserted, expected)
    if isinstance(expected, (dict, list)):
        return _without_absent_optional_values(
            asserted
        ) == _without_absent_optional_values(expected)
    return asserted == expected


def _without_absent_optional_values(value: Any) -> Any:
    """Treat omitted Provider optionals and typed ``None`` fields identically."""
    if isinstance(value, dict):
        return {
            key: _without_absent_optional_values(child)
            for key, child in value.items()
            if child is not None
        }
    if isinstance(value, list):
        return [_without_absent_optional_values(child) for child in value]
    return value


_MISSING_SOURCE_SNAPSHOT_VALUE = object()


_SOURCE_LOCATOR_SEGMENT = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_-]*)(?P<indices>(?:\[\d+\])*)"
)


def _numeric_values_match(left: Any, right: Any) -> bool:
    return (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
        and float(left) == float(right)
    )


def _source_snapshot_value_at_locator(snapshot: Any, locator: str) -> Any:
    """Resolve a bounded source locator against its retained raw snapshot.

    Candidate price facts are allowed to map a provider field such as ``rate``
    into ``nightly_price_cny``.  We therefore validate the locator's actual
    scalar value instead of inferring a field name from the typed projection.
    The resolver intentionally accepts only plain dotted mapping keys and
    numeric list indexes; it never interprets expressions supplied by a model.
    """

    path = str(locator or "").strip()
    if path.startswith("snapshot."):
        path = path[len("snapshot.") :]
    elif path == "snapshot":
        return snapshot
    if not path:
        return _MISSING_SOURCE_SNAPSHOT_VALUE
    value = snapshot
    for segment in path.split("."):
        matched = _SOURCE_LOCATOR_SEGMENT.fullmatch(segment)
        if matched is None or not isinstance(value, Mapping):
            return _MISSING_SOURCE_SNAPSHOT_VALUE
        key = matched.group("key")
        if key not in value:
            return _MISSING_SOURCE_SNAPSHOT_VALUE
        value = value[key]
        for index_text in re.findall(r"\[(\d+)\]", matched.group("indices")):
            if not isinstance(value, list):
                return _MISSING_SOURCE_SNAPSHOT_VALUE
            index = int(index_text)
            if index >= len(value):
                return _MISSING_SOURCE_SNAPSHOT_VALUE
            value = value[index]
    return value


def fact_has_exact_numeric_source_support(
    fact: FactAssertion,
    *,
    expected_value: float | int,
    source_records: Iterable[SourceRecord],
) -> bool:
    """Require a verified numeric Fact to resolve to the same source value.

    A supporting source link alone is not enough for a displayed reference
    budget: otherwise a model can attach a legitimate source ID to a number
    that never appeared in that source's immutable snapshot.
    """

    if fact.status != "verified" or not _numeric_values_match(
        fact.asserted_value, expected_value
    ):
        return False
    sources_by_id = {source.source_record_id: source for source in source_records}
    return any(
        link.relation == "supports"
        and (source := sources_by_id.get(link.source_record_id)) is not None
        and source.lifecycle_status == "active"
        and _numeric_values_match(
            _source_snapshot_value_at_locator(source.snapshot, link.source_locator),
            expected_value,
        )
        for link in fact.source_links
    )


def _supporting_compiled_tool_sources(
    fact: FactAssertion,
    *,
    source_records: Sequence[SourceRecord],
    required_entity_id: str,
) -> list[SourceRecord]:
    """Every compiled tool source that supports ``fact`` *about* one entity.

    ``tools.governance.COMPILED_TOOL_SOURCE_ID_PREFIX`` separates "the server
    saw this tool call" from "the model typed a URL": a model-authored
    ``external_web`` record
    survives parsing with its body intact, but no model can put an
    ``external_tool`` record into a packet — the compiler substitutes its own
    registry entry or rejects the packet outright.

    The prefix alone is not enough, though.  It says *some* tool call happened
    this Run, not that the call was about this entity, so a model could hang a
    fabricated entity's claim on a genuine compiled source for a different
    place.  ``compiled_tool_source_id_is_about`` closes that: the id's final
    component is the digest of the entity the envelope returned, minted by
    ``planning.research.output.identifiers`` from the very same helper.
    """

    sources_by_id = {source.source_record_id: source for source in source_records}
    matched: list[SourceRecord] = []
    for link in fact.source_links:
        if link.relation != "supports":
            continue
        if not compiled_tool_source_id_is_about(
            link.source_record_id, required_entity_id
        ):
            continue
        source = sources_by_id.get(link.source_record_id)
        if (
            source is not None
            and source.source_kind == "external_tool"
            and source.lifecycle_status == "active"
        ):
            matched.append(source)
    return matched


def fact_has_compiled_tool_source_support(
    fact: FactAssertion,
    *,
    source_records: Iterable[SourceRecord],
    required_entity_id: str,
) -> bool:
    """Require a claim to rest on a compiled source about ``required_entity_id``.

    This is the whole-entity grounding predicate.  The Research Packet compiler
    rewrites a candidate's identity facts to link its compiled source only for
    candidates whose ``place_id``/``route_id`` actually appeared in this round's
    Tool Gateway transcript, so "an identity fact supported by a compiled source
    whose id was minted for this very identity" is equivalent to "a Provider
    really returned this entity".  A candidate the model invented wholesale can
    satisfy neither half.
    """

    return bool(
        _supporting_compiled_tool_sources(
            fact,
            source_records=list(source_records),
            required_entity_id=required_entity_id,
        )
    )


_UNKNOWN_CANDIDATE_KIND_FIELD = "candidate_kind"


def _identity_provenance_binding(
    candidate: ResearchCandidate,
) -> tuple[str, str] | None:
    """The one identity field whose fact must name the compiled entity source.

    Returns ``None`` only for a candidate kind this dispatch does not know, which
    the caller turns into a refusal — never into "no requirement".  See
    :func:`_missing_identity_provenance_binding`.

    The field chosen is the *entity identifier itself* — ``place_id`` for the
    three place domains, ``route_id`` for transport — because that is the exact
    string the compiled source id digests.  Hanging the requirement there makes
    the check closed over one value: the field's asserted value and the digest
    input are the same string, so no second field has to be trusted to relate
    them.  Any other identity field (a name, an address) would need the
    candidate's ``place_id`` as an unchecked intermediary and would still leave
    the identifier itself free to be invented.

    For transport this binds the *route*, because ``route_id`` is what
    ``_provider_route_source_id`` digests.  A ``route_id`` identifies one
    provider route — a train number, a service — not an individual leg, so this
    check alone once let a genuinely returned route carry model-authored
    timetable detail.  That is closed in
    :func:`_missing_declared_identity_fields`, which requires each of the leg's
    own required values to rest on a compiled source about the same route,
    rather than by digesting anything new here: changing the digest input would
    diverge from the mint site and reject every genuinely grounded candidate.
    """

    if isinstance(candidate, TransportCandidate):
        return "route_id", candidate.route_id
    if isinstance(candidate, (DiningCandidate, LodgingCandidate, VisitCandidate)):
        return "place_id", candidate.place_id
    return None


def _missing_identity_provenance_binding(
    candidate: ResearchCandidate,
    *,
    candidate_facts: Sequence[FactAssertion],
    source_records: Sequence[SourceRecord],
) -> Optional[str]:
    """The identity field this candidate cannot prove a Provider ever returned.

    An unrecognized candidate kind fails **closed**.  ``ResearchCandidate`` is a
    closed four-member discriminated union today, so that branch is unreachable —
    but a dispatch whose default is "no requirement" is exactly the shape this
    round exists to remove: a fifth kind added later would be admitted with no
    provider grounding at all and nothing would say so.  Refusal is also the only
    honest outcome available here; raising would take down the whole Run over a
    single candidate admission could simply decline.
    """

    binding = _identity_provenance_binding(candidate)
    if binding is None:
        return _UNKNOWN_CANDIDATE_KIND_FIELD
    field_path, raw_entity_id = binding
    entity_id = raw_entity_id.strip() if isinstance(raw_entity_id, str) else ""
    if not entity_id:
        return field_path
    if any(
        fact.field_path == field_path
        and fact.entity_ref.entity_id == candidate.candidate_id
        and _fact_value_matches(fact.asserted_value, entity_id)
        and fact_has_compiled_tool_source_support(
            fact,
            source_records=source_records,
            required_entity_id=entity_id,
        )
        for fact in candidate_facts
    ):
        return None
    return field_path
