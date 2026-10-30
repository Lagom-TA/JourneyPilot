"""Convert checkpointed intake evidence into bounded confirmation sources.

Only server-built intake evidence is accepted here. A digest is an integrity
check, not proof that a client supplied record came from the server; the caller
must load these records from the server-owned checkpoint.
"""

from __future__ import annotations

from typing import Any, List, Mapping

from travel_agent.conversation.intake_evidence import intake_evidence_source_id
from travel_agent.planning.requirements.confirmation_contracts import MAX_SOURCES, SourceEvidence, SourceKind


_KIND_MAP = {
    "current_request": SourceKind.CURRENT_REQUEST,
    "explicit_supplement": SourceKind.EXPLICIT_SUPPLEMENT,
    "explicit_selection": SourceKind.EXPLICIT_SELECTION,
    "structured_form": SourceKind.STRUCTURED_FORM,
    # No provider attestation or trustworthy archive split: context only.
    "structured_form_unverified": SourceKind.TRIP_CONTEXT,
    "legacy_unverified": SourceKind.TRIP_CONTEXT,
}


def confirmation_sources_from_intake(
    records: List[Mapping[str, Any]], *, intake_id: str, intake_revision: int,
) -> List[SourceEvidence]:
    if not intake_id or isinstance(intake_revision, bool) or not isinstance(intake_revision, int) or intake_revision < 0:
        raise ValueError("invalid intake identity")
    if len(records) > MAX_SOURCES:
        raise ValueError("too many intake evidence records")
    sources: List[SourceEvidence] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("intake evidence must be an object")
        source_id = record.get("source_id")
        kind = record.get("kind")
        field = record.get("field")
        text = record.get("text")
        context = record.get("context")
        if (
            not isinstance(source_id, str) or not isinstance(kind, str) or kind not in _KIND_MAP
            or not isinstance(field, str) or not field or not isinstance(text, str) or not text
            or not isinstance(context, str)
            or record.get("intake_id") != intake_id
            or isinstance(record.get("intake_revision"), bool)
            or not isinstance(record.get("intake_revision"), int)
            or record.get("intake_revision") != intake_revision
        ):
            raise ValueError("intake evidence does not match its saved version")
        expected = intake_evidence_source_id(intake_id, intake_revision, kind, field, text, context)
        if source_id != expected or source_id in seen:
            raise ValueError("intake evidence identifier does not match its contents")
        seen.add(source_id)
        sources.append(SourceEvidence(
            source_id=source_id, kind=_KIND_MAP[kind], text=text,
            context=context or None, revision=intake_revision,
        ))
    return sources
