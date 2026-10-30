"""Evidence matching never decides polarity and never trusts a model question."""

import pytest

from travel_agent.planning.requirements.evidence_resolution import literal_evidence_candidates


def source(source_id, kind, text, *, context=""):
    return {
        "source_id": source_id, "kind": kind, "text": text, "context": context,
        "intake_id": "it_" + "a" * 32, "intake_revision": 4,
    }


def test_model_invented_object_in_question_and_option_is_not_user_evidence():
    sources = [
        source("raw", "current_request", "规划杭州旅行"),
        source("selection", "explicit_selection", "去东京迪士尼", context="是否去东京迪士尼？"),
    ]
    assert literal_evidence_candidates(subject="东京迪士尼", domain="visit", sources=sources) == []


def test_user_typed_supplement_can_ground_a_specific_subject_without_authorizing_it():
    sources = [
        source("raw", "current_request", "规划杭州旅行"),
        source("supplement", "explicit_supplement", "不要去东京迪士尼"),
    ]
    [candidate] = literal_evidence_candidates(subject="东京迪士尼", domain="visit", sources=sources)
    assert candidate["source_id"] == "supplement"
    assert candidate["source_text"] == "不要去东京迪士尼"
    assert candidate["quote"] == "东京迪士尼"
    # The caller must still ask the user whether this is a current exclusion.


def test_selected_subject_requires_independent_user_text_and_negation_stays_uninterpreted():
    sources = [
        source("raw", "current_request", "不喝咖啡"),
        source("selection", "explicit_selection", "包含交通", context="预算包含往返交通吗？"),
    ]
    [coffee] = literal_evidence_candidates(subject="咖啡", domain="dining", sources=sources)
    assert coffee["source_text"] == "不喝咖啡"
    assert literal_evidence_candidates(subject="交通", domain="long_distance_transport", sources=sources) == []
    assert literal_evidence_candidates(subject="咖啡", domain="visit", sources=sources)[0]["source_id"] == "raw"


def test_legacy_history_and_cross_version_sources_do_not_authorize_candidates():
    sources = [source("old", "legacy_unverified", "想喝咖啡")]
    assert literal_evidence_candidates(subject="咖啡", domain="dining", sources=sources) == []
    sources.append({**source("new", "current_request", "去杭州"), "intake_revision": 5})
    with pytest.raises(ValueError, match="different intake versions"):
        literal_evidence_candidates(subject="杭州", domain="visit", sources=sources)
