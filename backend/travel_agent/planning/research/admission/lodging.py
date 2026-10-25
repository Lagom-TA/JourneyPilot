"""Planning research admission lodging."""

from __future__ import annotations

from travel_agent.planning.research.admission.evidence import _numeric_values_match
from travel_agent.planning.research.admission.evidence import (
    fact_has_exact_numeric_source_support,
)
from travel_agent.planning.research.candidates import LodgingCandidate
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.planning.research.evidence import SourceRecord
from typing import Any
from typing import Iterable
from typing import Mapping


def normalize_lodging_price_evidence(
    candidate: ResearchCandidate,
    *,
    candidate_facts: Iterable[FactAssertion],
    source_records: Iterable[SourceRecord],
) -> ResearchCandidate:
    """Remove numeric lodging claims that cannot be found in source evidence.

    The function is deliberately non-destructive to the verified property
    identity: lack of a current rate should not discard an otherwise useful
    hotel.  It only suppresses unsupported price fields.  If a purported live
    quote has no surviving price evidence, it becomes a confirmation-only
    reference state so no consumer projection can present a model-authored
    number as a current quote.
    """

    if not isinstance(candidate, LodgingCandidate):
        return candidate
    facts = list(candidate_facts)
    sources = list(source_records)
    updates: dict[str, Any] = {}
    retained_price_fields = 0
    for field_path in ("nightly_price_cny", "total_price_cny"):
        value = getattr(candidate, field_path)
        if value is None:
            continue
        if any(
            fact.entity_ref.entity_id == candidate.candidate_id
            and fact.field_path == field_path
            and fact_has_exact_numeric_source_support(
                fact,
                expected_value=value,
                source_records=sources,
            )
            for fact in facts
        ):
            retained_price_fields += 1
        else:
            updates[field_path] = None
    effective_price_kind = candidate.price_kind
    if candidate.price_kind == "live_quote" and retained_price_fields == 0:
        updates["price_kind"] = "reference_estimate"
        effective_price_kind = "reference_estimate"
    if (
        effective_price_kind == "reference_estimate"
        and candidate.availability_status == "confirmed"
    ):
        updates["availability_status"] = "needs_confirmation"
    return candidate.model_copy(update=updates) if updates else candidate


def _active_lodging_budget_caps(
    candidate: ResearchCandidate,
    hard_constraints: Iterable[Mapping[str, Any]],
) -> list[tuple[str, Mapping[str, Any]]]:
    if not isinstance(candidate, LodgingCandidate):
        return []
    candidate_constraint_ids = set(candidate.active_constraint_ids)
    active: list[tuple[str, Mapping[str, Any]]] = []
    for item in hard_constraints:
        if not isinstance(item, Mapping):
            continue
        constraint_id = str(item.get("constraint_id") or "").strip()
        if (
            not constraint_id
            or constraint_id not in candidate_constraint_ids
            or str(item.get("status") or "active").strip().casefold() != "active"
            or str(item.get("category") or "").strip().casefold() != "budget_cap"
        ):
            continue
        active.append((constraint_id, item))
    return active


_UNMEASURED_BUDGET_FIT = 0.5


def _lodging_budget_fit(
    candidate: ResearchCandidate,
    *,
    hard_constraints: Iterable[Mapping[str, Any]],
    candidate_facts: Iterable[FactAssertion],
    source_records: Iterable[SourceRecord],
) -> float:
    """Score a property against every explicit cap the user set.

    A user who says "at most" fixes a number, and only a date/stay-specific
    ``live_quote`` with a matching verified source value measures against it.
    A sourced rate under the cap scores 1.0; one above it scores the ratio by
    which it fits, so a 10% overshoot outranks a doubled price.
    """

    if not isinstance(candidate, LodgingCandidate):
        return 1.0
    facts = list(candidate_facts)
    sources = list(source_records)
    fit = 1.0
    for constraint_id, constraint in _active_lodging_budget_caps(
        candidate, hard_constraints
    ):
        params = constraint.get("params")
        if not isinstance(params, Mapping):
            fit = min(fit, _UNMEASURED_BUDGET_FIT)
            continue
        amount = params.get("amount")
        currency = str(params.get("currency") or "").strip().upper()
        per = str(params.get("per") or "").strip().casefold()
        if (
            not _numeric_values_match(amount, amount)
            or float(amount) <= 0
            or currency != "CNY"
            or per not in {"night", "day", "total"}
        ):
            fit = min(fit, _UNMEASURED_BUDGET_FIT)
            continue
        field_path = "total_price_cny" if per == "total" else "nightly_price_cny"
        price = getattr(candidate, field_path)
        if candidate.price_kind != "live_quote" or price is None:
            fit = min(fit, _UNMEASURED_BUDGET_FIT)
            continue
        price_facts = [
            fact
            for fact in facts
            if (
                fact.entity_ref.entity_id == candidate.candidate_id
                and fact.field_path == field_path
            )
        ]
        if not any(
            fact_has_exact_numeric_source_support(
                fact,
                expected_value=price,
                source_records=sources,
            )
            for fact in price_facts
        ):
            fit = min(fit, _UNMEASURED_BUDGET_FIT)
            continue
        fit = min(
            fit, 1.0 if float(price) <= float(amount) else float(amount) / float(price)
        )
    return fit
