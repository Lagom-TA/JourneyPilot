"""Research packet metadata responsibilities."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .policy import ResearchWorkerKind


def build_authoritative_research_packet_metadata(
    *,
    worker_kind: ResearchWorkerKind,
    run_id: str,
    generation_id: str,
    intent_spec_revision: int,
    research_query_plan_id: str,
    executed_queries: Sequence[Mapping[str, Any]],
    task_id: str,
    constraint_pack_revision: int,
    fact_data_revision: int,
    query_context: Mapping[str, Any],
    generated_at: datetime,
) -> dict[str, Any]:
    "Create server-owned Packet lineage; models never author these fields."
    digest = hashlib.sha256(
        f"{run_id}\0{generation_id}\0{task_id}\0{worker_kind}".encode("utf-8")
    ).hexdigest()[:20]
    return {
        "research_packet_id": f"packet_{worker_kind}_{digest}",
        "run_id": run_id,
        "generation_id": generation_id,
        "task_id": task_id,
        "worker_kind": worker_kind,
        "intent_spec_revision": intent_spec_revision,
        "research_query_plan_id": research_query_plan_id,
        "executed_query_ids": [
            str(query.get("query_id") or "")
            for query in executed_queries
            if query.get("query_id")
        ],
        "constraint_pack_revision": constraint_pack_revision,
        "fact_data_revision": fact_data_revision,
        "query_context": {
            **dict(query_context),
            "query_lineage": [dict(query) for query in executed_queries],
        },
        "generated_at": generated_at.isoformat(),
    }


def _payload_generated_at(payload: Mapping[str, Any]) -> datetime:
    "Read the packet's own timestamp so derived records stay deterministic."
    raw = payload.get("generated_at")
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _controlled_destination_ids(base_payload: Mapping[str, Any]) -> list[str]:
    query_context = base_payload.get("query_context")
    identity = (
        query_context.get("controlled_trip_identity")
        if isinstance(query_context, Mapping)
        else None
    )
    destinations = (
        identity.get("destinations") if isinstance(identity, Mapping) else None
    )
    if not isinstance(destinations, list):
        return []
    return list(
        dict.fromkeys(
            str(item.get("place_id") or "").strip()
            for item in destinations
            if isinstance(item, Mapping) and str(item.get("place_id") or "").strip()
        )
    )


def _provider_selection_base_payload(
    raw: str,
    *,
    expected_worker: ResearchWorkerKind,
    expected_run_id: str,
    authoritative_packet_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    "Keep only authoritative Packet metadata from a malformed model payload."
    if authoritative_packet_metadata is not None:
        return {
            **authoritative_packet_metadata,
            "source_records": [],
        }
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if (
        payload.get("worker_kind") != expected_worker
        or payload.get("run_id") != expected_run_id
    ):
        return None
    for field_name in ("research_packet_id", "task_id"):
        if (
            not isinstance(payload.get(field_name), str)
            or not payload[field_name].strip()
        ):
            return None
    for field_name in ("constraint_pack_revision", "fact_data_revision"):
        value = payload.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return None
    if not isinstance(payload.get("query_context"), dict):
        return None
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.strip():
        return None
    try:
        datetime.fromisoformat(generated_at.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return {
        "research_packet_id": payload["research_packet_id"],
        "run_id": expected_run_id,
        "task_id": payload["task_id"],
        "worker_kind": expected_worker,
        "constraint_pack_revision": payload["constraint_pack_revision"],
        "fact_data_revision": payload["fact_data_revision"],
        "query_context": payload["query_context"],
        "source_records": [],
        "generated_at": generated_at,
    }


def _bind_authoritative_candidate_constraints(
    payload: dict[str, Any],
    expected_active_constraint_ids: Sequence[str] | None,
) -> None:
    "Discard model-created constraint identity before typed validation."
    if expected_active_constraint_ids is None:
        return
    authoritative_ids = list(dict.fromkeys(expected_active_constraint_ids))
    authoritative_set = set(authoritative_ids)
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate["active_constraint_ids"] = authoritative_ids
        evaluations = candidate.get("constraint_evaluations")
        candidate["constraint_evaluations"] = (
            [
                evaluation
                for evaluation in evaluations
                if isinstance(evaluation, dict)
                and evaluation.get("constraint_id") in authoritative_set
            ]
            if isinstance(evaluations, list)
            else []
        )
        candidate["constraint_gate_attestation"] = None


def _bind_authoritative_packet_metadata(
    payload: dict[str, Any],
    authoritative_packet_metadata: Mapping[str, Any] | None,
) -> None:
    if authoritative_packet_metadata is None:
        return
    payload.update(authoritative_packet_metadata)
    packet_id = str(authoritative_packet_metadata["research_packet_id"])
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return
    for candidate in candidates:
        if isinstance(candidate, dict):
            candidate["research_packet_id"] = packet_id
