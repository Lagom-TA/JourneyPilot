"""Planning completion audit."""

from __future__ import annotations

from datetime import date
from travel_agent.planning.requirements.composition_contracts import (
    COMPOSITION_PROMPT_VERSION,
)
from travel_agent.planning.requirements.route_legs import (
    build_required_long_distance_legs,
)
from travel_agent.planning.requirements.route_legs import (
    missing_long_distance_leg_roles,
)
from travel_agent.planning.research.provider_contracts import ProviderEvidenceOutcome
from travel_agent.planning.research.provider_outcomes import (
    current_provider_evidence_summary,
)
from travel_agent.runtime.time import iso_or_none as _iso_or_none
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import Mapping
from typing import Optional
import hashlib
import json

from travel_agent.runtime.delivery_audit import _as_mapping


COMPLETION_AUDIT_SUMMARY_KEY = "completion_audit"


def _as_mappings(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    values: List[Dict[str, Any]] = []
    for item in value:
        mapped = _as_mapping(item)
        if mapped:
            values.append(mapped)
    return values


def _unique_strings(values: Iterable[Any]) -> List[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value).strip()))


def _as_int(value: Any, *, default: int = -1) -> int:
    """Read a non-boolean integer without turning malformed state into truth."""

    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _controlled_identity_is_valid(value: Any) -> bool:
    """Check the compact identity shape without retaining its user-facing text.

    The audit needs a durable yes/no eligibility observation, not a duplicate of
    the complete controlled identity.  The workflow has already validated the
    rich Pydantic contract before this point; this check merely prevents a
    malformed checkpoint summary from being treated as eligible on replay.
    """

    identity = _as_mapping(value)
    origin = _as_mapping(identity.get("origin"))
    destinations = identity.get("destinations")
    party = _as_mapping(identity.get("party"))
    style = _as_mapping(identity.get("style"))
    return bool(
        origin.get("place_id")
        and isinstance(destinations, list)
        and destinations
        and all(_as_mapping(item).get("place_id") for item in destinations)
        and identity.get("start_date")
        and identity.get("end_date")
        and party
        and style
    )


def _delivery_is_intact(data: Mapping[str, Any]) -> bool:
    """Whether the persisted state still has the core ability to form a Bundle."""

    return not _as_mapping(data.get("delivery_failure"))


def _unsupported_external_fact_leak_count(
    *,
    facts: Mapping[str, Any],
    report: Mapping[str, Any],
) -> int:
    """Count only objectively unsupported projected fact ids.

    This intentionally does not classify a stale but source-linked fact as
    unsupported.  It catches the zero-tolerance case: a report citation names
    a fact that is absent from the final fact snapshot or has no live external
    supporting source record.
    """

    fact_index = {
        str(item.get("fact_assertion_id")): item
        for item in _as_mappings(facts.get("fact_assertions"))
        if item.get("fact_assertion_id")
    }
    source_ids = {
        str(item.get("source_record_id"))
        for item in _as_mappings(facts.get("source_records"))
        if item.get("source_record_id")
    }
    leaked: set[str] = set()
    for citation in _as_mappings(report.get("citations")):
        for fact_id in _unique_strings(citation.get("fact_assertion_ids") or []):
            fact = fact_index.get(fact_id)
            if not fact:
                leaked.add(fact_id)
                continue
            supporting_source_ids = {
                str(link.get("source_record_id"))
                for link in _as_mappings(fact.get("source_links"))
                if link.get("relation") == "supports" and link.get("source_record_id")
            }
            if not supporting_source_ids or not supporting_source_ids <= source_ids:
                leaked.add(fact_id)
    return len(leaked)


def _as_date(value: Any) -> Optional[date]:
    """Read a calendar date from the JSON projection without ever raising."""

    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _long_distance_leg_ledger(workspace: Mapping[str, Any]) -> tuple[int, int]:
    """Count the round trip's long-distance legs owed, and how many are missing.

    The Workspace's controlled-identity anchor is the same authority the report
    reads in ``_long_distance_path_notes``, and delivery is counted off the Day
    timelines, so a leg the composer never placed on a Day is never counted as
    delivered.  Both counts are needed: a lone missing count would read a Run
    that owed no round trip and a Run that lost both of its legs as the same 0.
    When the shared judgement declines to speak — no responsibility, or Days
    that do not cover a required service date — both stay 0, because the audit
    must not assert a gap the reader-facing note is unwilling to assert.
    """

    identity: Optional[Mapping[str, Any]] = None
    for anchor in _as_mappings(workspace.get("user_input_anchors")):
        if (
            anchor.get("input_kind") == "controlled_identity"
            and anchor.get("field_path") == "controlled_trip_identity"
            and isinstance(anchor.get("value"), Mapping)
        ):
            identity = anchor["value"]
            break
    if identity is None:
        return 0, 0

    required = build_required_long_distance_legs(
        identity, cross_day_return_required=False
    )
    itinerary = _as_mapping(workspace.get("itinerary"))
    long_distance_leg_ids = {
        str(leg.get("transport_leg_id"))
        for leg in _as_mappings(itinerary.get("transport_legs"))
        if leg.get("transport_class") == "long_distance" and leg.get("transport_leg_id")
    }
    day_dates: set[date] = set()
    dates_with_long_distance: set[date] = set()
    for day in _as_mappings(itinerary.get("day_plans")):
        day_date = _as_date(day.get("date"))
        if day_date is None:
            continue
        day_dates.add(day_date)
        if any(
            entry.get("entity_type") == "transport_leg"
            and str(entry.get("entity_id")) in long_distance_leg_ids
            for entry in _as_mappings(day.get("timeline"))
        ):
            dates_with_long_distance.add(day_date)

    missing = missing_long_distance_leg_roles(
        required,
        day_dates=day_dates,
        dates_with_long_distance=dates_with_long_distance,
    )
    if missing is None:
        return 0, 0
    return len(required), len(missing)


def _quality_indicators(
    *,
    data: Mapping[str, Any],
    facts: Mapping[str, Any],
    report: Mapping[str, Any],
) -> Dict[str, int]:
    """Persist only countable, non-prose quality evidence for Eval metrics."""

    catalog = _as_mapping(data.get("recommendation_catalog"))
    workspace = _as_mapping(data.get("trip_workspace_v2"))
    if not catalog:
        catalog = _as_mapping(workspace.get("recommendation_catalog"))
    candidates = {
        str(candidate.get("candidate_id")): candidate
        for packet in _as_mappings(catalog.get("research_packets"))
        for candidate in _as_mappings(packet.get("candidates"))
        if candidate.get("candidate_id")
    }
    provider_candidate_ids: set[str] = set()
    for packet in _as_mappings(catalog.get("research_packets")):
        provider_source_ids = {
            str(source.get("source_record_id"))
            for source in _as_mappings(packet.get("source_records"))
            if source.get("source_record_id") and source.get("tool_audit_id")
        }
        for candidate in _as_mappings(packet.get("candidates")):
            candidate_id = str(candidate.get("candidate_id") or "")
            if candidate_id and provider_source_ids.intersection(
                _unique_strings(candidate.get("source_record_ids") or [])
            ):
                provider_candidate_ids.add(candidate_id)
    passed_candidate_ids = {
        str(admission.get("candidate_id"))
        for admission in _as_mappings(catalog.get("admission_results"))
        if admission.get("status") == "passed" and admission.get("candidate_id")
    }

    current_constraint_revision = _as_int(data.get("constraint_pack_revision"))
    provider_outcomes = {
        str(scope_id): ProviderEvidenceOutcome.model_validate(outcome)
        for scope_id, outcome in _as_mapping(
            data.get("provider_evidence_outcomes")
        ).items()
    }
    provider_summary = current_provider_evidence_summary(
        provider_outcomes,
        constraint_pack_revision=current_constraint_revision,
    )
    constraint_pack = _as_mapping(data.get("constraint_pack"))
    pack_meta = _as_mapping(constraint_pack.get("pack_meta"))
    required_leg_count, missing_leg_count = _long_distance_leg_ledger(workspace)

    return {
        "unsupported_external_fact_leak_count": _unsupported_external_fact_leak_count(
            facts=facts,
            report=report,
        ),
        "passed_candidate_count": len(
            [
                candidate_id
                for candidate_id in passed_candidate_ids
                if candidate_id in candidates
            ]
        ),
        "provider_evidence_current_scope_count": (provider_summary.current_scope_count),
        "provider_evidence_unresolved_scope_count": (
            provider_summary.unresolved_scope_count
        ),
        "provider_option_count": provider_summary.provider_option_count,
        "provider_option_materialized_count": (
            provider_summary.provider_option_materialized_count
        ),
        "provider_option_admissible_count": len(
            passed_candidate_ids.intersection(provider_candidate_ids)
        ),
        "provider_salvage_loss_count": (provider_summary.provider_salvage_loss_count),
        "required_long_distance_leg_count": required_leg_count,
        "required_long_distance_leg_missing_count": missing_leg_count,
        "hard_constraint_contract_complete": int(
            pack_meta.get("hard_constraint_contract_complete") is not False
        ),
    }


def _completion_audit_summary(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Project completion controls into a durable, audit-safe summary.

    Full LangGraph state is checkpointed elsewhere and must not be copied into
    TripRun.  This compact projection is deliberately sufficient to recompute
    the 5/6/8-minute and zero-tolerance metrics after a process restart while
    excluding prompts, provider payloads, candidate prose, and tool arguments.
    """

    draft = _as_mapping(data.get("minimum_delivery_draft"))
    planning_authorized_at = _iso_or_none(draft.get("planning_authorized_at"))
    if not draft or not planning_authorized_at:
        return None

    deadline = _as_mapping(data.get("run_deadline"))
    bundle = _as_mapping(data.get("delivery_bundle"))
    workspace = _as_mapping(data.get("trip_workspace_v2")) or _as_mapping(
        bundle.get("workspace")
    )
    facts = _as_mapping(data.get("fact_store_snapshot")) or _as_mapping(
        bundle.get("fact_snapshot")
    )
    report = _as_mapping(data.get("report_projection")) or _as_mapping(
        bundle.get("report_projection")
    )
    map_projection = _as_mapping(data.get("map_projection")) or _as_mapping(
        bundle.get("map_projection")
    )
    source_index = _as_mapping(data.get("source_index_projection")) or _as_mapping(
        bundle.get("source_index")
    )
    manifest = _as_mapping(bundle.get("manifest"))
    intent_spec = _as_mapping(data.get("intent_spec"))
    planning_generation = _as_mapping(data.get("planning_generation"))
    query_plan = _as_mapping(data.get("research_query_plan"))
    catalog = _as_mapping(workspace.get("recommendation_catalog")) or _as_mapping(
        data.get("recommendation_catalog")
    )
    selection_plan = _as_mapping(
        workspace.get("candidate_selection_plan")
    ) or _as_mapping(data.get("candidate_selection_plan"))
    selection_policy = _as_mapping(selection_plan.get("selection_policy"))
    coverage = _as_mapping(workspace.get("intent_coverage_report")) or _as_mapping(
        data.get("intent_coverage_report")
    )
    mutations = _as_mappings(workspace.get("composition_mutations")) or _as_mappings(
        data.get("composition_mutations")
    )

    def audit_hash(value: Any) -> str:
        material = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    packets = _as_mappings(catalog.get("research_packets"))
    executed_query_ids = _unique_strings(
        query_id
        for packet in packets
        for query_id in packet.get("executed_query_ids") or []
    )
    provider_snapshot_hashes = _unique_strings(
        source.get("content_hash")
        for packet in packets
        for source in _as_mappings(packet.get("source_records"))
        if source.get("content_hash")
    )
    generic_candidate_ids = {
        str(record.get("candidate_id"))
        for record in _as_mappings(catalog.get("candidate_discovery_records"))
        if "generic_fallback" in set(record.get("origins") or [])
    }
    selection_entries = _as_mappings(selection_plan.get("entries"))
    selected_candidate_ids = _unique_strings(
        entry.get("candidate_id")
        for entry in selection_entries
        if entry.get("eligible_for_composition") is True
    )
    admitted_candidate_ids = _unique_strings(
        admission.get("candidate_id")
        for admission in _as_mappings(catalog.get("admission_results"))
        if admission.get("status") == "passed"
    )
    ranking_scores = _as_mappings(catalog.get("candidate_ranking_scores"))
    coverage_items = _as_mappings(coverage.get("items"))
    active_intents = _as_mappings(intent_spec.get("active_items"))
    unresolved_clauses = _as_mappings(intent_spec.get("unresolved_clauses"))
    active_count = len(active_intents)
    clause_count = active_count + len(unresolved_clauses)
    covered_selection_ids = set(selection_plan.get("covered_intent_ids") or [])
    candidate_relevant_ids = {
        str(intent.get("intent_id"))
        for intent in active_intents
        if "ranking" in set(intent.get("impact_stages") or [])
    }
    entity_count = sum(
        len(_as_mappings(_as_mapping(workspace.get("itinerary")).get(field)))
        for field in (
            "visit_stops",
            "dining_stops",
            "lodging_stays",
            "transport_legs",
        )
    )
    postprocessor_mutations = [
        mutation for mutation in mutations if mutation.get("created_by") != "user_edit"
    ]
    unexplained_mutation_count = sum(
        not mutation.get("reason_code")
        or mutation.get("hard_rules_revalidated") is not True
        for mutation in mutations
    )

    exhausted_gap_ids = _unique_strings(
        gap.get("gap_id")
        for gap in _as_mappings(data.get("candidate_research_gaps"))
        if gap.get("status") == "exhausted"
    )

    source_origin_counts = {
        "live": 0,
        "provider_snapshot_cache": 0,
        "other": 0,
    }
    for source in _as_mappings(facts.get("source_records")):
        provenance = _as_mapping(source.get("cache_provenance"))
        origin = str(provenance.get("origin") or "other")
        if origin not in source_origin_counts:
            origin = "other"
        source_origin_counts[origin] += 1

    attributions: List[Dict[str, Any]] = []
    for attribution_id, raw_attribution in _as_mapping(
        data.get("gate_failure_attributions")
    ).items():
        attribution = _as_mapping(raw_attribution)
        if not attribution:
            continue
        attributions.append(
            {
                "attribution_id": str(
                    attribution.get("attribution_id") or attribution_id
                ),
                "gate_class": attribution.get("gate_class"),
                "disposition": attribution.get("disposition"),
                "reason_code": attribution.get("reason_code"),
                "research_domain": attribution.get("research_domain"),
                "gap_ids": _unique_strings(attribution.get("gap_ids") or []),
                "failure_signature": attribution.get("failure_signature"),
                "deterministic": bool(attribution.get("deterministic")),
                "retry_attempt": int(attribution.get("retry_attempt") or 0),
                "recorded_at": _iso_or_none(attribution.get("recorded_at")),
            }
        )
    attributions.sort(key=lambda item: item["attribution_id"])

    terminal = _as_mapping(data.get("terminal_attribution"))
    terminal_attribution = (
        {
            "draft_id": terminal.get("draft_id"),
            "closure_status": terminal.get("closure_status"),
            "reason_code": terminal.get("reason_code"),
            "recorded_at": _iso_or_none(terminal.get("recorded_at")),
            "delivery_bundle_id": terminal.get("delivery_bundle_id"),
            "gate_class": terminal.get("gate_class"),
        }
        if terminal
        else None
    )

    controlled_identity_valid = _controlled_identity_is_valid(
        data.get("controlled_trip_identity")
    ) and (
        _as_int(draft.get("controlled_trip_identity_revision"))
        == _as_int(data.get("controlled_trip_identity_revision"))
    )
    intent_generation_valid = bool(
        planning_generation.get("generation_id")
        and draft.get("planning_generation_id")
        == planning_generation.get("generation_id")
        and _as_int(draft.get("intent_spec_revision"))
        == _as_int(data.get("intent_spec_revision"))
        == _as_int(intent_spec.get("revision"))
        and draft.get("intent_spec_hash") == intent_spec.get("content_hash")
    )
    constraint_revision_valid = isinstance(
        data.get("constraint_pack"), dict
    ) and _as_int(draft.get("constraint_pack_revision")) == _as_int(
        data.get("constraint_pack_revision")
    )
    sealed_draft_valid = bool(
        draft.get("planning_authorized") is True
        and draft.get("draft_id")
        and draft.get("run_id")
        and str(draft.get("run_id")) == str(data.get("run_id") or draft.get("run_id"))
        and intent_generation_valid
        and _as_int(draft.get("plan_revision"))
        == _as_int(data.get("plan_gate_revision_count"))
        and deadline.get("draft_id") == draft.get("draft_id")
        and _iso_or_none(deadline.get("planning_authorized_at"))
        == planning_authorized_at
    )
    user_cancelled = bool(
        _as_mapping(terminal_attribution).get("reason_code") == "user_cancelled"
    )
    formal_bundle_capable = bool(sealed_draft_valid and _delivery_is_intact(data))

    expected_constraint_ids = _unique_strings(
        draft.get("preserved_constraint_ids") or []
    )
    workspace_constraint_ids = _unique_strings(
        anchor.get("constraint_id")
        for anchor in _as_mappings(workspace.get("user_input_anchors"))
        if anchor.get("input_kind") == "hard_constraint"
    )
    workspace_revision = workspace.get("workspace_revision")
    fact_revision = facts.get("fact_data_revision")
    weather = _as_mapping(data.get("weather_context")) or _as_mapping(
        bundle.get("weather_snapshot")
    )
    weather_revision = weather.get("weather_data_revision")
    projection_consistent = bool(manifest) and (
        manifest.get("workspace_revision") == workspace_revision
        and manifest.get("fact_data_revision") == fact_revision
        and manifest.get("weather_data_revision") == weather_revision
        and report.get("source_workspace_revision") == workspace_revision
        and report.get("source_fact_data_revision") == fact_revision
        and report.get("source_weather_data_revision") == weather_revision
        and map_projection.get("source_workspace_revision") == workspace_revision
        and source_index.get("source_fact_data_revision") == fact_revision
    )
    document = _as_mapping(report.get("document"))
    report_content_nonempty = bool(
        document.get("days")
        or document.get("sections")
        or document.get("summary")
        or document.get("title")
    )
    prompt_versions = dict(_as_mapping(data.get("prompt_versions")))
    prompt_versions.setdefault("itinerary_composition", COMPOSITION_PROMPT_VERSION)

    return {
        "run_id": str(data.get("run_id") or draft.get("run_id") or ""),
        "draft_id": str(draft.get("draft_id") or ""),
        "planning_authorized_at": planning_authorized_at,
        "deadline": {
            "target_at": _iso_or_none(deadline.get("target_at")),
            "closeout_at": _iso_or_none(deadline.get("closeout_at")),
            "composition_at": _iso_or_none(deadline.get("composition_at")),
            "delivery_deadline_at": _iso_or_none(deadline.get("delivery_deadline_at")),
            "last_observed_at": _iso_or_none(deadline.get("last_observed_at")),
            "target_seconds": int(deadline.get("target_seconds") or 0),
            "closeout_seconds": int(deadline.get("closeout_seconds") or 0),
            "composition_seconds": int(deadline.get("composition_seconds") or 0),
            "delivery_deadline_seconds": int(
                deadline.get("delivery_deadline_seconds") or 0
            ),
            "checkpointed_elapsed_seconds": float(
                deadline.get("checkpointed_elapsed_seconds") or 0.0
            ),
        },
        "exhausted_gap_ids": exhausted_gap_ids,
        "candidate_gate_attempts": {
            str(key): int(value or 0)
            for key, value in _as_mapping(data.get("candidate_gate_attempts")).items()
        },
        "source_origin_counts": source_origin_counts,
        "planning_generation": {
            "generation_id": planning_generation.get("generation_id"),
            "identity_hash": planning_generation.get("identity_hash"),
            "intent_hash": planning_generation.get("intent_hash"),
            "constraint_hash": planning_generation.get("constraint_hash"),
        },
        "versions": {
            "intent_schema": intent_spec.get("schema_version"),
            "query_policy": query_plan.get("policy_version"),
            "ranking_policy": (
                ranking_scores[0].get("policy_version") if ranking_scores else None
            ),
            "selection_policy": selection_policy.get("policy_version"),
            "composition_policy": "composition_rules.v1",
            "fidelity_policy": "intent_fidelity.v1",
            "prompt_versions": prompt_versions,
            "model_versions": dict(_as_mapping(data.get("model_versions"))),
            "policy_versions": dict(_as_mapping(data.get("policy_versions"))),
            "contract_versions": dict(_as_mapping(manifest.get("contract_versions"))),
        },
        "research": {
            "query_plan_hash": query_plan.get("content_hash"),
            "executed_query_ids": executed_query_ids,
            "provider_snapshot_hashes": provider_snapshot_hashes,
            "generic_fallback_usage_count": len(
                generic_candidate_ids.intersection(selected_candidate_ids)
            ),
        },
        "candidate": {
            "catalog_hash": audit_hash(catalog) if catalog else None,
            "admitted_candidate_ids": admitted_candidate_ids,
            "ranking_hash": audit_hash(ranking_scores) if ranking_scores else None,
        },
        "selection": {
            "selection_plan_hash": selection_plan.get("content_hash"),
            "selection_seed": selection_policy.get("selection_seed"),
            "mode": selection_policy.get("mode"),
            "selected_candidate_ids": selected_candidate_ids,
        },
        "composition": {
            "workspace_hash": _as_mapping(manifest.get("content_hashes")).get(
                "workspace"
            )
            or (audit_hash(workspace) if workspace else None),
            "mutation_ids": _unique_strings(
                mutation.get("mutation_id") for mutation in mutations
            ),
            "mutation_count": len(mutations),
            "postprocessor_override_count": len(postprocessor_mutations),
        },
        "intent_fidelity": {
            "coverage_hash": coverage.get("content_hash"),
            "hard_satisfaction_rate": coverage.get("hard_satisfaction_rate"),
            "soft_coverage_rate": coverage.get("soft_coverage_rate"),
            "unsatisfied_intent_ids": _unique_strings(
                item.get("intent_id")
                for item in coverage_items
                if item.get("status")
                in {"partially_satisfied", "unsatisfied", "conflicted", "unsupported"}
            ),
            "unverifiable_intent_ids": _unique_strings(
                item.get("intent_id")
                for item in coverage_items
                if item.get("status") == "unverifiable"
            ),
        },
        "behavior_metrics": {
            "intent_clause_coverage_rate": (
                round(active_count / clause_count, 4) if clause_count else 1.0
            ),
            "intent_assignment_coverage_rate": (
                round(len(coverage_items) / active_count, 4) if active_count else 1.0
            ),
            "hard_intent_satisfaction_rate": coverage.get("hard_satisfaction_rate"),
            "soft_intent_coverage_rate": coverage.get("soft_coverage_rate"),
            "intent_candidate_coverage_rate": (
                round(
                    len(covered_selection_ids.intersection(candidate_relevant_ids))
                    / len(candidate_relevant_ids),
                    4,
                )
                if candidate_relevant_ids
                else 1.0
            ),
            "generic_fallback_usage_rate": (
                round(
                    len(generic_candidate_ids.intersection(selected_candidate_ids))
                    / len(selected_candidate_ids),
                    4,
                )
                if selected_candidate_ids
                else 0.0
            ),
            "postprocessor_override_rate": (
                round(len(postprocessor_mutations) / entity_count, 4)
                if entity_count
                else 0.0
            ),
            "unexplained_mutation_count": unexplained_mutation_count,
        },
        "gate_failure_attributions": attributions,
        "constraint_contract": {
            "expected_ids": expected_constraint_ids,
            "workspace_ids": workspace_constraint_ids,
        },
        "eligibility_contract": {
            "controlled_identity_valid": controlled_identity_valid,
            "intent_generation_valid": intent_generation_valid,
            "constraint_revision_valid": constraint_revision_valid,
            "sealed_draft_valid": sealed_draft_valid,
            "formal_bundle_capable": formal_bundle_capable,
            "user_cancelled": user_cancelled,
        },
        "quality_indicators": _quality_indicators(
            data=data,
            facts=facts,
            report=report,
        ),
        "formal_delivery": {
            "bundle_id": manifest.get("bundle_id"),
            "has_bundle": bool(manifest),
            "report_ready": report.get("status") == "ready",
            "report_content_nonempty": report_content_nonempty,
            "projection_consistent": projection_consistent,
        },
        "terminal_attribution": terminal_attribution,
    }


def completion_audit_from_state_summary(summary: Any) -> Dict[str, Any]:
    """Read a completion audit safely (including older embedded projections)."""

    data = _as_mapping(summary)
    embedded = _as_mapping(data.get(COMPLETION_AUDIT_SUMMARY_KEY))
    if embedded:
        return embedded
    return data if data.get("planning_authorized_at") else {}


def build_trip_run_completion_audit(state: Any) -> Dict[str, Any]:
    """Return the separate developer/Eval completion projection for a state."""

    if state is None:
        return {}
    if hasattr(state, "model_dump"):
        data = state.model_dump(mode="json")
    elif isinstance(state, dict):
        data = state
    else:
        data = {}
    return _completion_audit_summary(data) or {}
