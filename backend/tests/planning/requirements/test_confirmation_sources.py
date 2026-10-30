"""Only server-saved intake records may enter semantic confirmation."""

import pytest

from travel_agent.conversation.intake_contracts import GuidedIntakeState
from travel_agent.conversation.intake_evidence import intake_evidence_sources
from travel_agent.planning.requirements.confirmation_contracts import SourceKind
from travel_agent.planning.requirements.confirmation_sources import confirmation_sources_from_intake


def evidence():
    intake = GuidedIntakeState.model_validate({
        "intake_id": "it_" + "a" * 32, "intake_revision": 3,
        "raw_input": "去杭州，不喝咖啡", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "questions": [{"id": "diet", "question": "是否想吃牛肉？", "kind": "single", "options": [
            {"id": "no", "label": "不吃牛肉"}, {"id": "yes", "label": "可以吃牛肉"},
        ]}],
        "answers": [{"question_id": "diet", "selected_option_ids": ["no"]}],
    })
    return intake_evidence_sources(intake)


def test_selected_option_is_not_relabelled_as_raw_user_text():
    sources = confirmation_sources_from_intake(evidence(), intake_id="it_" + "a" * 32, intake_revision=3)
    raw = next(item for item in sources if item.text == "去杭州，不喝咖啡")
    selected = next(item for item in sources if item.text == "不吃牛肉")
    assert raw.kind is SourceKind.CURRENT_REQUEST
    assert selected.kind is SourceKind.EXPLICIT_SELECTION
    assert selected.context == "是否想吃牛肉？"


def test_changed_context_kind_or_revision_is_rejected():
    for key, value in [("context", "伪造问题"), ("kind", "current_request"), ("intake_revision", 4)]:
        records = evidence()
        records[-1] = {**records[-1], key: value}
        with pytest.raises(ValueError):
            confirmation_sources_from_intake(records, intake_id="it_" + "a" * 32, intake_revision=3)
