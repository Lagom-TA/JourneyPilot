"""Semantic decisions carry IDs and choices, never client-authored facts."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from travel_agent.conversation.chat.contracts import GateDecision
from travel_agent.conversation.chat.presentation import ChatPresentation
from travel_agent.conversation.chat.progress_events import _handle_state_update
from travel_agent.planning.requirements.approval import _plan_gate_approval_token
from travel_agent.api.presenters.runs import _event_response, _public_pending_user_choice
from travel_agent.api.sse_projection import project_sse_payload, public_plan_gate_payload
from travel_agent.runtime.run_contracts import TripRunEvent


CHALLENGE = "challenge_" + "a" * 64


def payload():
    return {
        "action": "supplement", "approval_token": "gate-version",
        "semantic_confirmation": {
            "challenge_id": CHALLENGE, "revision": 2,
            "decisions": [{"assertion_id": "a1", "decision": "avoid"}],
        },
    }


def test_plan_approval_token_binds_confirmed_semantics_without_changing_legacy_tokens():
    payload = {"plan": {"steps": []}, "plan_text": "计划", "recognized_requirements": {}}
    legacy = SimpleNamespace(run_id="r", plan_gate_revision_count=0)
    old = _plan_gate_approval_token(legacy, payload)
    assert old == _plan_gate_approval_token(SimpleNamespace(run_id="r", plan_gate_revision_count=0, semantic_receipt=None), payload)
    first = _plan_gate_approval_token(SimpleNamespace(run_id="r", plan_gate_revision_count=0, semantic_receipt=SimpleNamespace(receipt_hash="a" * 64)), payload)
    second = _plan_gate_approval_token(SimpleNamespace(run_id="r", plan_gate_revision_count=0, semantic_receipt=SimpleNamespace(receipt_hash="b" * 64)), payload)
    assert first != second and first != old


def test_structured_semantic_decision_is_separate_from_free_text():
    decision = GateDecision.model_validate(payload())
    assert decision.semantic_confirmation.decisions[0].decision.value == "avoid"
    assert decision.content == ""
    assert GateDecision.model_validate({"action": "supplement", "content": "需要无障碍"}).semantic_confirmation is None


@pytest.mark.parametrize("change", [
    {"action": "approve"},
    {"content": "额外模型事实"},
    {"approval_token": None},
    {"unknown_field": "extra"},
])
def test_semantic_decision_cannot_be_combined_with_other_authority(change):
    with pytest.raises(ValidationError):
        GateDecision.model_validate({**payload(), **change})


def test_semantic_gate_projection_rejects_hidden_fields_instead_of_truncating():
    item = {
        "assertion_id": "a1", "source_kind": "current_request", "context": "不喝咖啡",
        "question_context": None, "quote": "咖啡", "object_label": "咖啡", "domain_label": "餐饮",
        "allowed_decisions": ["avoid", "historical", "unknown"],
        "execution": {
            "requirement_id": "constraint_coffee", "requirement_type": "constraint",
            "kind": "dietary_restriction", "target": "dietary_restriction",
            "polarity": "exclude", "strength": "hard",
            "value": {"value": "不喝咖啡", "params": {}},
            "applies_to": ["全体同行：2 位成人、0 位儿童"],
            "scope": "dietary_restriction", "public_summary": "不喝咖啡",
        },
    }
    gate = {"gate": "plan", "phase": "semantics", "challenge_id": CHALLENGE, "revision": 1,
            "approval_token": "token", "assertions": [item]}
    projected = public_plan_gate_payload(gate)
    assert projected["assertions"] == [item]
    restored = _public_pending_user_choice({"type": "approval_gate", "gate": "plan", "payload": gate})
    assert restored["payload"] == projected
    bad = {**gate, "assertions": [{**item, "hidden_query": "牛肉"}]}
    assert public_plan_gate_payload(bad)["assertions"] is None
    history = {**item, "source_kind": "trip_context", "allowed_decisions": ["include", "unknown"]}
    assert public_plan_gate_payload({**gate, "assertions": [history]})["assertions"] is None
    assert public_plan_gate_payload({**gate, "assertions": [{**item, "domain_label": "destination_researcher"}]})["assertions"] is None
    assert public_plan_gate_payload({**gate, "revision": True})["assertions"] is None
    assert public_plan_gate_payload({**gate, "approval_token": "\ud800"})["assertions"] is None
    assert public_plan_gate_payload({**gate, "assertions": [item] * 129})["assertions"] is None
    ack = project_sse_payload({
        "type": "semantic_confirmation_accepted", "run_id": "r", "challenge_id": CHALLENGE,
        "approval_token": "token", "semantic_action": "confirm", "raw_user_text": "secret",
    })
    assert ack == {"type": "semantic_confirmation_accepted", "run_id": "r", "challenge_id": CHALLENGE, "approval_token": "token", "semantic_action": "confirm"}


@pytest.mark.parametrize(("action", "expected"), [("semantic_confirmed", "confirm"), ("semantic_correction", "correction")])
async def test_acknowledgment_only_follows_a_consumed_gate_decision(action, expected):
    ctx = ChatPresentation(message_id="m", session_id="s", mode="deep", use_deep_research=True, trace_run_id="r")
    update = {"plan_gate_decision": {"action": action, "challenge_id": CHALLENGE, "approval_token": "token"}}
    unverified = [event async for event in _handle_state_update(("state", "plan_gate", update), ctx)]
    assert all(event.get("type") != "semantic_confirmation_accepted" for event in unverified)
    update["plan_gate_decision"]["checkpoint_confirmed"] = True
    events = [event async for event in _handle_state_update(("state", "plan_gate", update), ctx)]
    ack = next(event for event in events if event.get("type") == "semantic_confirmation_accepted")
    assert ack["semantic_action"] == expected and ack["challenge_id"] == CHALLENGE
    other = [event async for event in _handle_state_update(("state", "planner", update), ctx)]
    assert all(event.get("type") != "semantic_confirmation_accepted" for event in other)


def test_preapproval_journal_results_are_never_public_events():
    for event_type in (
        "preapproval.model_call.reserved", "preapproval.model_call.retry_authorized",
        "preapproval.model_call.completed",
    ):
        event = TripRunEvent(run_id="offline", sequence=1, event_type=event_type, payload={"result": "PRIVATE", "attempt_key": "secret"})
        assert _event_response(event) is None


def test_run_audit_does_not_expose_semantic_answers_or_gate_token():
    event = TripRunEvent(
        run_id="offline-run", sequence=1, event_type="run.resumed",
        payload={"gate_decision": payload(), "approval_token": "secret-token", "status": "running"},
    )
    public = _event_response(event).model_dump(mode="json")
    assert "gate_decision" not in public["payload"]
    assert "approval_token" not in public["payload"]
    assert "a1" not in str(public)


def test_duplicate_ids_and_client_authored_values_are_rejected():
    data = payload()
    data["semantic_confirmation"]["decisions"].append({"assertion_id": "a1", "decision": "include"})
    with pytest.raises(ValidationError):
        GateDecision.model_validate(data)
    data = payload()
    data["semantic_confirmation"]["decisions"][0]["object_label"] = "东京"
    with pytest.raises(ValidationError):
        GateDecision.model_validate(data)
