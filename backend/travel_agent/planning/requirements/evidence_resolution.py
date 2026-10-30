"""Resolve tentative subjects to exact user evidence, without inferring meaning.

A match is only a candidate for a later explicit user decision; it does not
prove polarity, applicability, safety, or authorization. Model-authored
questions are context, never evidence. More specific subjects proposed only in
model-authored option labels require a separate user-authored source.
"""

from __future__ import annotations

import unicodedata
from typing import Any, Dict, List, Mapping


_ALLOWED_DOMAINS = frozenset({
    "visit", "dining", "lodging", "local_transport", "long_distance_transport",
})
_USER_TYPED_KINDS = frozenset({"current_request", "explicit_supplement", "structured_form"})


def literal_evidence_candidates(
    *, subject: str, domain: str, sources: List[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Return exact occurrences only; the caller must demand user confirmation."""
    if (
        not isinstance(subject, str) or not subject or subject != subject.strip()
        or len(subject) > 200
        or any(unicodedata.category(character).startswith("C") for character in subject)
    ):
        raise ValueError("candidate subject must be bounded visible text")
    if domain not in _ALLOWED_DOMAINS:
        raise ValueError("candidate domain is not supported")
    if len(sources) > 256:
        raise ValueError("too many evidence sources")
    ids = [str(item.get("source_id") or "") for item in sources]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("source identifiers must be present and unique")
    intake_keys = {(item.get("intake_id"), item.get("intake_revision")) for item in sources}
    if len(intake_keys) > 1:
        raise ValueError("evidence sources belong to different intake versions")
    independently_grounded = any(
        item.get("kind") in _USER_TYPED_KINDS
        and isinstance(item.get("text"), str)
        and subject in item["text"]
        for item in sources
    )
    found: List[Dict[str, Any]] = []
    for source in sources:
        kind = source.get("kind")
        text = source.get("text")
        if not isinstance(text, str):
            raise ValueError("source text must be a string")
        if kind not in _USER_TYPED_KINDS and kind != "explicit_selection":
            continue
        if kind == "explicit_selection" and not independently_grounded:
            continue
        start = 0
        while True:
            index = text.find(subject, start)
            if index < 0:
                break
            found.append({
                "source_id": source["source_id"], "span_start": index,
                "span_end": index + len(subject), "quote": subject,
                "context": source.get("context") or "", "source_text": text,
            })
            if len(found) > 128:
                raise ValueError("candidate has too many evidence occurrences")
            start = index + len(subject)
    return found
