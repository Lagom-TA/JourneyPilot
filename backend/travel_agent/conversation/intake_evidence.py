"""Extract user-owned source records from the server-saved intake.

These records are evidence candidates, not authorization. In particular, a
model-authored question is context, not an affirmative user request; selected
answers and free text are kept separately as the initial requirements text.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from travel_agent.conversation.intake import DEFAULT_ANSWER_OPTION_ID
from travel_agent.conversation.intake_contracts import GuidedIntakeState


def intake_evidence_source_id(intake_id: str, revision: int, kind: str, field: str, text: str, context: str) -> str:
    payload = json.dumps(
        {"intake_id": intake_id, "revision": revision, "kind": kind, "field": field, "text": text, "context": context},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return "source_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def intake_evidence_sources(intake: GuidedIntakeState) -> List[Dict[str, Any]]:
    """Use only the saved raw input, selected answers and explicit form values."""
    if not intake.intake_id:
        raise ValueError("intake evidence requires a server-owned intake id")
    sources: List[Dict[str, Any]] = []

    def add(kind: str, field: str, text: str, *, context: str = "") -> None:
        value = text.strip()
        if not value:
            return
        sources.append({
            "source_id": intake_evidence_source_id(intake.intake_id or "", intake.intake_revision, kind, field, value, context),
            "kind": kind, "field": field, "text": value, "context": context,
            "intake_id": intake.intake_id, "intake_revision": intake.intake_revision,
        })

    add("current_request", "raw_input", intake.raw_input)
    for item in intake.archived_answers:
        if not item.selected_option_ids and not item.supplement:
            # Old archives lack a reliable split between an option and free text.
            add("legacy_unverified", f"answer:{item.question_id}", item.answer, context=item.question)
            continue
        for option_id, label in zip(item.selected_option_ids, item.selected_labels):
            if option_id != DEFAULT_ANSWER_OPTION_ID:
                add("explicit_selection", f"answer:{item.question_id}:{option_id}", label, context=item.question)
        add("explicit_supplement", f"answer:{item.question_id}:supplement", item.supplement, context=item.question)
    questions = {question.id: question for question in intake.questions}
    for answer in intake.answers:
        question = questions.get(answer.question_id)
        if question is None:
            raise ValueError("intake answer refers to an unknown question")
        options = {option.id: option.label for option in question.options}
        for option_id in answer.selected_option_ids:
            if option_id == DEFAULT_ANSWER_OPTION_ID:
                continue
            if option_id not in options:
                raise ValueError("intake answer refers to an unknown option")
            add("explicit_selection", f"answer:{question.id}:{option_id}", options[option_id], context=question.question)
        add("explicit_supplement", f"answer:{question.id}:supplement", answer.supplement, context=question.question)
    add("explicit_supplement", "additional_requirements", intake.additional_requirements)

    identity = intake.controlled_identity
    if identity is not None:
        # Place candidates and style IDs need a server-side attestation before
        # they can authorize execution; a client-supplied source flag is not proof.
        add("structured_form_unverified", "origin", identity.origin.name)
        for index, place in enumerate(identity.destinations):
            add("structured_form_unverified", f"destination:{index}", place.name)
        add("structured_form", "date_range", f"{identity.start_date.isoformat()} 至 {identity.end_date.isoformat()}")
        add("structured_form", "party", f"{identity.party.adults} 位成人、{identity.party.children} 位儿童")
        if identity.party.elderly_companions:
            add("structured_form", "elderly_companions", "有长辈同行")
        if identity.party.accessibility_required:
            add("structured_form", "accessibility", "需要无障碍安排")
        if identity.style.source == "current":
            add("structured_form_unverified", "style", identity.style.primary)
            for index, interest in enumerate(identity.style.secondary_interests):
                add("structured_form_unverified", f"interest:{index}", interest)
    if len(sources) > 256:
        raise ValueError("intake contains too many evidence sources")
    return sources
