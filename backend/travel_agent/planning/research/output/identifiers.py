"""Research packet identifiers responsibilities."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from travel_agent.tools.governance import compiled_tool_source_id


def _canonical_snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _provider_fact_id(audit_id: str, candidate_id: str, field_path: str) -> str:
    digest = hashlib.sha256(
        f"{audit_id}\0{candidate_id}\0{field_path}".encode("utf-8")
    ).hexdigest()[:20]
    return f"fact_provider_{digest}"


def _provider_candidate_id(candidate_kind: str, place_id: str) -> str:
    digest = hashlib.sha256(
        f"{candidate_kind}\0{place_id}".encode("utf-8")
    ).hexdigest()[:20]
    return f"candidate_{candidate_kind}_{digest}"


def _provider_entity_source_id(audit_id: str, entity_id: str) -> str:
    "Bind an entity snapshot to this Run's tool audit exactly once."
    return compiled_tool_source_id(audit_id, entity_id)


def _provider_route_source_id(audit_id: str, route_id: str) -> str:
    "Bind a selected route snapshot to this Run's tool audit exactly once."
    return compiled_tool_source_id(audit_id, route_id)
