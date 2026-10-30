"""Evidence comes from saved user inputs, not model-authored questions."""

import pytest

from travel_agent.conversation.intake_evidence import intake_evidence_sources
from travel_agent.conversation.intake_contracts import GuidedIntakeState


def intake():
    return GuidedIntakeState.model_validate({
        "intake_id": "it_" + "a" * 32, "intake_revision": 3,
        "raw_input": "去杭州，不喝咖啡", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "questions": [
            {"id": "diet", "question": "是否想吃牛肉？", "kind": "single", "options": [
                {"id": "no", "label": "不吃牛肉"}, {"id": "yes", "label": "可以吃牛肉"},
            ]},
            {"id": "pace", "question": "什么节奏？", "kind": "single", "options": [
                {"id": "slow", "label": "轻松"}, {"id": "sensible_default", "label": "按合理默认安排，不再补充"},
            ]},
        ],
        "answers": [
            {"question_id": "diet", "selected_option_ids": ["no"], "supplement": "对花生过敏"},
            {"question_id": "pace", "selected_option_ids": ["sensible_default"]},
        ],
        "additional_requirements": "不走长楼梯",
    })


def test_question_text_and_default_choice_are_not_affirmative_sources():
    records = intake_evidence_sources(intake())
    texts = [item["text"] for item in records]
    assert texts == ["去杭州，不喝咖啡", "不吃牛肉", "对花生过敏", "不走长楼梯"]
    selected = next(item for item in records if item["text"] == "不吃牛肉")
    assert selected["kind"] == "explicit_selection"
    assert selected["context"] == "是否想吃牛肉？"
    assert all(item["intake_id"] == "it_" + "a" * 32 for item in records)
    assert all(item["intake_revision"] == 3 for item in records)
    assert records == intake_evidence_sources(intake())
    modified = intake().model_dump(mode="json")
    modified["questions"][0]["question"] = "是否想避开牛肉？"
    changed = intake_evidence_sources(GuidedIntakeState.model_validate(modified))
    changed_selection = next(item for item in changed if item["text"] == "不吃牛肉")
    assert changed_selection["source_id"] != selected["source_id"]


def test_client_place_and_style_are_not_yet_server_attested():
    data = intake().model_dump(mode="json")
    place = {"place_id": "offline:1", "provider": "osm", "kind": "city", "name": "东京", "display_name": "东京", "country_code": "JP", "latitude": 35.6, "longitude": 139.7, "admin_path": []}
    data["controlled_identity"] = {
        "origin": {**place, "place_id": "offline:2", "name": "上海", "country_code": "CN"},
        "destinations": [place], "start_date": "2026-11-05", "end_date": "2026-11-07",
        "party": {"adults": 2, "children": 0},
        "style": {"primary": "咖啡", "secondary_interests": [], "source": "current"},
    }
    records = intake_evidence_sources(GuidedIntakeState.model_validate(data))
    assert next(item for item in records if item["field"] == "destination:0")["kind"] == "structured_form_unverified"
    assert next(item for item in records if item["field"] == "style")["kind"] == "structured_form_unverified"
    assert next(item for item in records if item["field"] == "date_range")["kind"] == "structured_form"


def test_archived_defaults_do_not_become_positive_sources():
    data = intake().model_dump(mode="json")
    data["archived_answers"] = [
        {"question_id": "old-default", "question": "是否需要咖啡？", "answer": "按合理默认安排，不再补充", "selected_option_ids": ["sensible_default"], "selected_labels": ["按合理默认安排，不再补充"], "supplement": ""},
        {"question_id": "old-legacy", "question": "是否需要甜食？", "answer": "暂不确定"},
    ]
    records = intake_evidence_sources(GuidedIntakeState.model_validate(data))
    assert all(item["text"] != "按合理默认安排，不再补充" for item in records)
    legacy = next(item for item in records if item["text"] == "暂不确定")
    assert legacy["kind"] == "legacy_unverified"


def test_unknown_selected_option_or_missing_server_intake_id_is_rejected():
    data = intake().model_dump(mode="json")
    data["answers"][0]["selected_option_ids"] = ["model-invented"]
    with pytest.raises(ValueError, match="unknown option"):
        intake_evidence_sources(GuidedIntakeState.model_validate(data))
    data["intake_id"] = None
    with pytest.raises(ValueError, match="intake id"):
        intake_evidence_sources(GuidedIntakeState.model_validate(data))
