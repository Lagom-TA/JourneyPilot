"""Offline clarification before a research plan can be created."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from tests.fixtures.chat_execution import execute, prepare, request, resources as resources
from travel_agent.conversation import intake as intake_module
from travel_agent.conversation.chat.errors import PreparationRefused, PreparationRejection
from travel_agent.conversation.chat.preparation import ImmediateChat, PreparedChat
from travel_agent.conversation.chat.execution import _clear_checkpointed_intake
from travel_agent.conversation.intake_lock import intake_fingerprint
from travel_agent.conversation.intake import (
    IntakeUnderstandingUnavailable, apply_intake_answers, merge_intake_answers, understand_trip_intake,
)
from travel_agent.conversation.intake_contracts import (
    MAX_INTAKE_QUESTIONS, GuidedIntakeState, RouteDecision,
)
from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity


IDENTITY = {
    "origin": {
        "place_id": "origin", "provider": "osm", "kind": "city", "name": "上海",
        "display_name": "上海", "country_code": "CN", "latitude": 31.2,
        "longitude": 121.4, "admin_path": [],
    },
    "destinations": [{
        "place_id": "destination", "provider": "osm", "kind": "city", "name": "杭州",
        "display_name": "杭州", "country_code": "CN", "latitude": 30.3,
        "longitude": 120.2, "admin_path": [],
    }],
    "start_date": "2026-11-05", "end_date": "2026-11-08",
    "party": {"adults": 2, "children": 0, "elderly_companions": True},
    "style": {"primary": "轻松慢游", "secondary_interests": []},
}


def question(question_id, text, first, second):
    return {
        "id": question_id, "question": text, "kind": "single",
        "options": [{"id": "first", "label": first}, {"id": "second", "label": second}],
    }


BUDGET = question("budget_scope", "预算包含往返交通吗？", "包含", "不包含")
MOBILITY = question("mobility", "长辈爬楼是否受限？", "需要避免爬楼", "可以少量爬楼")


class MultiRoundModel:
    def __init__(self, *, fail_after_first=False):
        self.payloads = []
        self.fail_after_first = fail_after_first

    async def ainvoke(self, messages, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        self.payloads.append(payload)
        if self.fail_after_first and len(self.payloads) > 1:
            raise RuntimeError("offline model unavailable")
        answered = payload["already_answered"]
        new = [BUDGET] if not answered else [MOBILITY] if len(answered) == 1 else []
        return SimpleNamespace(content=json.dumps({
            "draft": {}, "recognized_requirements": ["带长辈，预算一万元"],
            "questions": new,
        }, ensure_ascii=False))


def _body(session_id, message_id, *, identity=None, guided=None):
    body = {
        "messages": [{"role": "user", "content": "带长辈去杭州，预算一万元", "message_id": message_id}],
        "route": "trip_planning", "session_id": session_id,
    }
    if identity is not None:
        body["controlled_trip_identity"] = identity
    if guided is not None:
        body["guided_intake"] = guided
    return body


async def _event(result):
    assert isinstance(result, ImmediateChat)
    events = [event async for event in result.events]
    assert events[0]["type"] == "guided_intake"
    return events[0]["guided_intake"]


@pytest.mark.parametrize("structured_entry", [False, True])
async def test_answers_are_reassessed_until_all_necessary_questions_are_answered(
    resources, monkeypatch, structured_entry
):
    model = MultiRoundModel()
    monkeypatch.setattr(intake_module, "get_model_router", lambda: object())
    monkeypatch.setattr(intake_module, "llm_for_task", lambda *_args: model)
    resources.checkpointer = object()
    session_id = "multi-round-form" if structured_entry else "multi-round-natural"
    first = await prepare(_body(session_id, "first", identity=IDENTITY if structured_entry else None), resources)
    guided = await _event(first)
    assert [q["id"] for q in guided["questions"]] == ["budget_scope"]
    assert not resources.trip_run_store.runs

    guided["answers"] = [{"question_id": "budget_scope", "selected_option_ids": ["first"]}]
    second = await prepare(_body(session_id, "second", identity=IDENTITY, guided=guided), resources)
    guided = await _event(second)
    assert [q["id"] for q in guided["questions"]] == ["budget_scope", "mobility"]
    assert model.payloads[1]["already_answered"] == [{"question": "预算包含往返交通吗？", "answer": "包含"}]
    assert not resources.trip_run_store.runs

    guided["answers"].append({"question_id": "mobility", "selected_option_ids": ["first"]})
    third = await prepare(_body(session_id, "third", identity=IDENTITY, guided=guided), resources)
    assert isinstance(third, PreparedChat)
    assert len(model.payloads) == 3
    assert "需要避免爬楼" in third.user_message
    assert "带长辈去杭州，预算一万元" in third.user_message
    evidence_texts = [item["text"] for item in third.intake_evidence_sources]
    assert "包含" in evidence_texts and "需要避免爬楼" in evidence_texts
    assert "预算包含往返交通吗？" not in evidence_texts
    assert all(item["intake_id"] for item in third.intake_evidence_sources)
    assert len(resources.trip_run_store.runs) == 1
    await third.lease_keeper.release(reason="test_complete")


async def test_separately_saved_answer_is_reassessed_even_if_chat_omits_intake(resources, monkeypatch):
    model = MultiRoundModel()
    monkeypatch.setattr(intake_module, "get_model_router", lambda: object())
    monkeypatch.setattr(intake_module, "llm_for_task", lambda *_args: model)
    resources.checkpointer = object()
    first = await _event(await prepare(_body("saved-answer", "first", identity=IDENTITY), resources))
    first["answers"] = [{"question_id": "budget_scope", "selected_option_ids": ["first"]}]
    response = await request("PATCH", "/api/sessions/saved-answer/intake", first)
    assert response.status_code == 200
    body = _body("saved-answer", "second", identity=IDENTITY)
    body["intake_id"] = response.json()["intake_id"]
    body["intake_revision"] = response.json()["intake_revision"]
    second = await prepare(body, resources)
    guided = await _event(second)
    assert [q["id"] for q in guided["questions"]] == ["budget_scope", "mobility"]
    assert len(model.payloads) == 2
    assert not resources.trip_run_store.runs


async def test_concurrent_answer_cannot_be_overwritten_by_stale_assessment(resources, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    class Model:
        async def ainvoke(self, messages, **_kwargs):
            payload = json.loads(messages[-1]["content"])
            if payload.get("additional_requirements") == "第一版":
                entered.set()
                await release.wait()
            return SimpleNamespace(content=json.dumps({
                "draft": {}, "recognized_requirements": [], "questions": [],
            }, ensure_ascii=False))

    monkeypatch.setattr(intake_module, "get_model_router", lambda: object())
    monkeypatch.setattr(intake_module, "llm_for_task", lambda *_args: Model())
    resources.checkpointer = object()
    saved = GuidedIntakeState.model_validate({
        "raw_input": "带长辈去杭州", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "controlled_identity": IDENTITY, "questions": [], "answers": [],
        "archived_answers": [{
            "question_id": "prior", "question": "此前已确认的偏好？", "answer": "按已确认安排",
        }],
    })
    await resources.chat_session_memory.save_guided_intake(session_id="race-intake", guided_intake=saved)
    saved = await resources.chat_session_memory.get_guided_intake(session_id="race-intake", user_id="local")
    first = saved.model_copy(update={"additional_requirements": "第一版"}).model_dump(mode="json")
    newer = saved.model_copy(update={"additional_requirements": "需要避免长楼梯"}).model_dump(mode="json")
    task_a = asyncio.create_task(prepare(_body("race-intake", "first", identity=IDENTITY, guided=first), resources))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task_b = asyncio.create_task(request("PATCH", "/api/sessions/race-intake/intake", newer))
        await asyncio.sleep(0.05)
        assert not task_b.done(), "draft updates must serialize against in-flight assessment"
        release.set()
        prepared = await asyncio.wait_for(task_a, timeout=2)
        assert isinstance(prepared, PreparedChat)
        patched = await asyncio.wait_for(task_b, timeout=2)
        assert patched.status_code == 409
        latest = await resources.chat_session_memory.get_guided_intake(session_id="race-intake", user_id="local")
        rebased = latest.model_dump(mode="json")
        rebased["additional_requirements"] = "需要避免长楼梯"
        patched = await request("PATCH", "/api/sessions/race-intake/intake", rebased)
        assert patched.status_code == 200
        latest = await resources.chat_session_memory.get_guided_intake(session_id="race-intake", user_id="local")
        assert latest.additional_requirements == "需要避免长楼梯"
        events = [event async for event in execute(
            _body("race-intake", "first", identity=IDENTITY, guided=first), prepared, resources,
        ) if event is not None]
        failed = next(event for event in events if event.get("type") == "run_failed")
        assert "旅行信息已更新" in failed["message"]
        assert not resources.travel_workflow.calls
        preserved = await resources.chat_session_memory.get_guided_intake(session_id="race-intake", user_id="local")
        assert preserved.additional_requirements == "需要避免长楼梯"
    finally:
        release.set()
        if not task_a.done():
            task_a.cancel()


async def test_newer_question_rejects_older_concurrent_chat_before_run_creation(resources, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    class Model:
        async def ainvoke(self, messages, **_kwargs):
            payload = json.loads(messages[-1]["content"])
            if payload.get("additional_requirements") == "旧回答":
                entered.set()
                await release.wait()
                questions = []
            else:
                questions = [MOBILITY]
            return SimpleNamespace(content=json.dumps({
                "draft": {}, "recognized_requirements": [], "questions": questions,
            }, ensure_ascii=False))

    monkeypatch.setattr(intake_module, "get_model_router", lambda: object())
    monkeypatch.setattr(intake_module, "llm_for_task", lambda *_args: Model())
    resources.checkpointer = object()
    saved = GuidedIntakeState.model_validate({
        "raw_input": "带长辈去杭州", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "controlled_identity": IDENTITY, "questions": [], "answers": [],
        "archived_answers": [{
            "question_id": "prior", "question": "此前已确认的偏好？", "answer": "按已确认安排",
        }],
    })
    await resources.chat_session_memory.save_guided_intake(session_id="two-chat-race", guided_intake=saved)
    saved = await resources.chat_session_memory.get_guided_intake(session_id="two-chat-race", user_id="local")
    old = saved.model_copy(update={"additional_requirements": "旧回答"}).model_dump(mode="json")
    new = saved.model_copy(update={"additional_requirements": "长辈限制待明确"}).model_dump(mode="json")
    task_a = asyncio.create_task(prepare(_body("two-chat-race", "old", identity=IDENTITY, guided=old), resources))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task_b = asyncio.create_task(prepare(_body("two-chat-race", "new", identity=IDENTITY, guided=new), resources))
        await asyncio.sleep(0.05)
        assert not task_b.done()
        release.set()
        first = await asyncio.wait_for(task_a, timeout=2)
        with pytest.raises(PreparationRefused) as caught:
            await asyncio.wait_for(task_b, timeout=2)
        assert caught.value.reason is PreparationRejection.INTAKE_VERSION_STALE
        assert isinstance(first, PreparedChat)
        latest = await resources.chat_session_memory.get_guided_intake(session_id="two-chat-race", user_id="local")
        rebased = latest.model_dump(mode="json")
        rebased["additional_requirements"] = "长辈限制待明确"
        second = await prepare(_body("two-chat-race", "new-rebased", identity=IDENTITY, guided=rebased), resources)
        assert [q["id"] for q in (await _event(second))["questions"]] == ["mobility"]
        events = [event async for event in execute(
            _body("two-chat-race", "old", identity=IDENTITY, guided=old), first, resources,
        ) if event is not None]
        assert any(event.get("type") == "run_failed" and "旅行信息已更新" in event.get("message", "") for event in events)
        assert not resources.travel_workflow.calls
        latest = await resources.chat_session_memory.get_guided_intake(session_id="two-chat-race", user_id="local")
        assert latest.questions[0].id == "mobility"
    finally:
        release.set()
        if not task_a.done():
            task_a.cancel()


async def test_late_old_page_cannot_replace_newer_saved_answers(resources):
    resources.checkpointer = object()
    saved = GuidedIntakeState.model_validate({
        "raw_input": "带长辈去杭州", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "controlled_identity": IDENTITY, "questions": [], "answers": [],
    })
    await resources.chat_session_memory.save_guided_intake(session_id="late-page", guided_intake=saved)
    saved = await resources.chat_session_memory.get_guided_intake(session_id="late-page", user_id="local")
    newer = saved.model_dump(mode="json")
    newer["additional_requirements"] = "新版必须无障碍"
    response = await request("PATCH", "/api/sessions/late-page/intake", newer)
    assert response.status_code == 200 and response.json()["intake_revision"] == 1
    retry = await request("PATCH", "/api/sessions/late-page/intake", newer)
    assert retry.status_code == 200 and retry.json()["intake_revision"] == 1
    with pytest.raises(PreparationRefused) as stale_start:
        await prepare(_body("late-page", "retry-old-version", identity=IDENTITY, guided=newer), resources)
    assert stale_start.value.reason is PreparationRejection.INTAKE_VERSION_STALE
    old = saved.model_dump(mode="json")
    old["additional_requirements"] = "旧版可以爬楼"
    stale = await request("PATCH", "/api/sessions/late-page/intake", old)
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "intake_version_stale"
    with pytest.raises(PreparationRefused) as caught:
        await prepare(_body("late-page", "old", identity=IDENTITY, guided=old), resources)
    assert caught.value.reason is PreparationRejection.INTAKE_VERSION_STALE
    stale_chat = await request("POST", "/api/chat-stream", _body("late-page", "old-http", identity=IDENTITY, guided=old))
    assert stale_chat.status_code == 409
    assert stale_chat.json()["detail"]["code"] == "intake_version_stale"
    latest = await resources.chat_session_memory.get_guided_intake(session_id="late-page", user_id="local")
    assert latest.additional_requirements == "新版必须无障碍"
    assert not resources.trip_run_store.runs


async def test_old_intake_id_cannot_overwrite_new_intake_with_same_revision(resources):
    resources.checkpointer = object()
    base = {
        "raw_input": "规划杭州旅行", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "controlled_identity": IDENTITY, "questions": [], "answers": [], "intake_revision": 1,
    }
    old = GuidedIntakeState.model_validate({**base, "intake_id": "it_" + "a" * 32})
    await resources.chat_session_memory.save_guided_intake(session_id="aba", guided_intake=old)
    stale = old.model_dump(mode="json")
    stale["additional_requirements"] = "旧版要求"
    await resources.chat_session_memory.clear_guided_intake(session_id="aba", user_id="local")
    new = GuidedIntakeState.model_validate({
        **base, "intake_id": "it_" + "b" * 32, "additional_requirements": "新版无障碍",
    })
    await resources.chat_session_memory.save_guided_intake(session_id="aba", guided_intake=new)
    response = await request("PATCH", "/api/sessions/aba/intake", stale)
    assert response.status_code == 409
    with pytest.raises(PreparationRefused) as caught:
        await prepare(_body("aba", "stale", identity=IDENTITY, guided=stale), resources)
    assert caught.value.reason is PreparationRejection.INTAKE_VERSION_STALE
    current = await resources.chat_session_memory.get_guided_intake(session_id="aba", user_id="local")
    assert current.intake_id == new.intake_id and current.additional_requirements == "新版无障碍"


async def test_legacy_stored_draft_requires_fresh_identity_and_revision(resources):
    old_payload = {
        "raw_input": "规划杭州旅行", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "questions": [], "answers": [],
    }
    await resources.chat_session_memory.save_guided_intake(
        session_id="legacy-intake", guided_intake=GuidedIntakeState.model_validate(old_payload),
    )
    old_payload["additional_requirements"] = "无障碍"
    rejected = await request("PATCH", "/api/sessions/legacy-intake/intake", old_payload)
    assert rejected.status_code == 409
    refreshed = await resources.chat_session_memory.get_guided_intake(session_id="legacy-intake", user_id="local")
    assert refreshed.intake_id.startswith("legacy_") and refreshed.intake_revision == 0
    current = refreshed.model_dump(mode="json")
    current["additional_requirements"] = "无障碍"
    accepted = await request("PATCH", "/api/sessions/legacy-intake/intake", current)
    assert accepted.status_code == 200 and accepted.json()["intake_revision"] == 1


async def test_readonly_replay_never_rewrites_or_advances_intake(resources, monkeypatch):
    resources.checkpointer = object()
    saved = GuidedIntakeState.model_validate({
        "intake_id": "it_" + "c" * 32, "intake_revision": 7,
        "raw_input": "带长辈去杭州", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "controlled_identity": IDENTITY, "questions": [BUDGET], "answers": [],
    })
    await resources.chat_session_memory.save_guided_intake(session_id="readonly-intake", guided_intake=saved)
    original = resources.chat_session_memory.guided_intake
    body = _body("readonly-intake", "replay", identity=IDENTITY)
    body["messages"][0]["content"] = saved.raw_input
    result = await prepare(body, resources)
    assert (await _event(result))["intake_revision"] == 7
    assert resources.chat_session_memory.guided_intake is original
    assert not resources.trip_run_store.runs


async def test_start_preserves_intake_until_a_checkpoint_exists(resources, monkeypatch):
    class Model:
        calls = 0

        async def ainvoke(self, *_args, **_kwargs):
            self.calls += 1
            return SimpleNamespace(content=json.dumps({"draft": {}, "recognized_requirements": [], "questions": []}))

    model = Model()
    monkeypatch.setattr(intake_module, "get_model_router", lambda: object())
    monkeypatch.setattr(intake_module, "llm_for_task", lambda *_args: model)
    resources.checkpointer = object()
    seed = GuidedIntakeState.model_validate({
        "raw_input": "带长辈去杭州，预算一万元", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "controlled_identity": IDENTITY, "questions": [], "answers": [],
        "archived_answers": [{
            "question_id": "prior", "question": "此前已确认的偏好？", "answer": "按已确认安排",
        }],
    })
    await resources.chat_session_memory.save_guided_intake(
        session_id="atomic-start", guided_intake=seed
    )
    seed = await resources.chat_session_memory.get_guided_intake(
        session_id="atomic-start", user_id="local"
    )
    body = _body(
        "atomic-start", "first", identity=IDENTITY,
        guided=seed.model_dump(mode="json"),
    )
    prepared = await prepare(body, resources)
    assert isinstance(prepared, PreparedChat)
    store = resources.trip_run_store
    original_transaction = store.transaction
    original_get = resources.chat_session_memory.get_guided_intake
    token = object()

    @asynccontextmanager
    async def transaction(run_id):
        async with original_transaction(run_id):
            yield token

    async def get_current(**kwargs):
        assert kwargs.get("db_session") is token and kwargs.get("for_update") is True
        return await original_get(**kwargs)

    async def must_not_clear(**_kwargs):
        raise AssertionError("intake cannot be cleared before a durable checkpoint")

    monkeypatch.setattr(store, "transaction", transaction)
    monkeypatch.setattr(resources.chat_session_memory, "get_guided_intake", get_current)
    monkeypatch.setattr(resources.chat_session_memory, "clear_guided_intake", must_not_clear)
    stream = execute(body, prepared, resources)
    first = await anext(stream)
    assert first["type"] == "chat_start"
    assert not resources.travel_workflow.calls
    assert await original_get(session_id="atomic-start") is not None
    await stream.aclose()
    restored = await original_get(session_id="atomic-start")
    assert restored is not None and model.calls == 1
    # Recovery presents the saved intake; it does not spend until the user
    # explicitly starts a fresh planning request.
    monkeypatch.setattr(resources.chat_session_memory, "get_guided_intake", original_get)
    resumed = await prepare(_body("atomic-start", "fresh-user-action", identity=IDENTITY, guided=restored.model_dump(mode="json")), resources)
    assert isinstance(resumed, PreparedChat) and model.calls == 2
    await resumed.lease_keeper.release(reason="test_complete")


async def test_only_a_real_checkpoint_can_clear_its_matching_intake(resources):
    saved = GuidedIntakeState.model_validate({
        "intake_id": "it_" + "d" * 32, "intake_revision": 3,
        "raw_input": "杭州旅行", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
    })
    await resources.chat_session_memory.save_guided_intake(session_id="checkpoint-input", guided_intake=saved)

    class Workflow:
        available = False

        async def probe_checkpoint_input(self, _run_id, **_kwargs):
            return (self.available, "checkpoint-1" if self.available else None)

    workflow = Workflow()
    kwargs = {
        "run_id": "checkpoint-input-run", "session_id": "checkpoint-input",
        "expected_fingerprint": intake_fingerprint(saved), "workflow": workflow,
        "expected_user_message": "杭州旅行", "expected_identity": IDENTITY,
        "expected_evidence_sources": [],
        "trip_run_store": resources.trip_run_store, "chat_session_memory": resources.chat_session_memory,
    }
    assert not await _clear_checkpointed_intake(**kwargs)
    assert await resources.chat_session_memory.get_guided_intake(session_id="checkpoint-input", user_id="local")
    workflow.available = True
    assert await _clear_checkpointed_intake(**kwargs)
    assert await resources.chat_session_memory.get_guided_intake(session_id="checkpoint-input", user_id="local") is None

    newer = saved.model_copy(update={"intake_id": "it_" + "e" * 32, "additional_requirements": "新版"})
    await resources.chat_session_memory.save_guided_intake(session_id="checkpoint-input", guided_intake=newer)
    assert await _clear_checkpointed_intake(**kwargs)
    current = await resources.chat_session_memory.get_guided_intake(session_id="checkpoint-input", user_id="local")
    assert current.intake_id == newer.intake_id and current.additional_requirements == "新版"


async def test_changed_confirmed_identity_is_reassessed_even_without_new_answers(resources, monkeypatch):
    model = MultiRoundModel()
    monkeypatch.setattr(intake_module, "get_model_router", lambda: object())
    monkeypatch.setattr(intake_module, "llm_for_task", lambda *_args: model)
    resources.checkpointer = object()
    identity = ControlledTripIdentity.model_validate(IDENTITY)
    saved = GuidedIntakeState.model_validate({
        "raw_input": "带长辈去杭州，预算一万元",
        "route_decision": {"route": "trip_planning", "confidence": 1, "requires_trip_draft": True},
        "controlled_identity": IDENTITY, "questions": [], "answers": [],
    })
    await resources.chat_session_memory.save_guided_intake(session_id="identity-changed", guided_intake=saved)
    saved = await resources.chat_session_memory.get_guided_intake(session_id="identity-changed", user_id="local")
    changed = identity.model_dump(mode="json")
    changed["destinations"][0]["name"] = "苏州"
    changed["destinations"][0]["display_name"] = "苏州"
    changed["destinations"][0]["place_id"] = "offline:苏州"
    body = _body("identity-changed", "changed", identity=changed)
    body["intake_id"] = saved.intake_id
    body["intake_revision"] = saved.intake_revision
    result = await prepare(body, resources)
    guided = await _event(result)
    assert guided["questions"][0]["id"] == "budget_scope"
    assert model.payloads[0]["confirmed_trip_identity"]["destinations"][0]["name"] == "苏州"
    assert not resources.trip_run_store.runs


async def test_failed_reassessment_does_not_create_a_run(resources, monkeypatch):
    model = MultiRoundModel(fail_after_first=True)
    monkeypatch.setattr(intake_module, "get_model_router", lambda: object())
    monkeypatch.setattr(intake_module, "llm_for_task", lambda *_args: model)
    resources.checkpointer = object()
    guided = await _event(await prepare(_body("reassessment-failure", "first", identity=IDENTITY), resources))
    guided["answers"] = [{"question_id": "budget_scope", "selected_option_ids": ["first"]}]
    with pytest.raises(PreparationRefused) as caught:
        await prepare(_body("reassessment-failure", "second", identity=IDENTITY, guided=guided), resources)
    assert caught.value.reason is PreparationRejection.INTAKE_UNAVAILABLE
    assert len(model.payloads) == 2
    assert not resources.trip_run_store.runs


async def test_four_prior_answers_do_not_silently_discard_a_new_question():
    prior_questions = [question(f"q{index}", f"问题{index}？", "甲", "乙") for index in range(4)]
    previous = GuidedIntakeState.model_validate({
        "raw_input": "规划一次旅行", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "questions": prior_questions,
        "answers": [{"question_id": q["id"], "selected_option_ids": ["first"]} for q in prior_questions],
    })

    class Model:
        async def ainvoke(self, *_args, **_kwargs):
            return SimpleNamespace(content=json.dumps({
                "draft": {}, "recognized_requirements": [], "questions": [MOBILITY],
            }, ensure_ascii=False))

    assessed = await understand_trip_intake(
        previous.raw_input, RouteDecision.model_validate(previous.route_decision),
        llm=Model(), controlled_identity=ControlledTripIdentity.model_validate(IDENTITY),
        previous=previous,
    )
    assert assessed.questions[-1].id == "mobility"
    assert len(assessed.questions) == 5
    assert not assessed.ready_to_create


def test_ready_flag_requires_an_available_assessment_and_actual_answer():
    base = {
        "raw_input": "规划旅行",
        "route_decision": {"route": "trip_planning", "confidence": 1, "requires_trip_draft": True},
        "controlled_identity": IDENTITY,
        "questions": [BUDGET],
        "answers": [{"question_id": "budget_scope", "selected_option_ids": []}],
    }
    assert not GuidedIntakeState.model_validate(base).ready_to_create
    assert not GuidedIntakeState.model_validate({
        **base, "questions": [], "answers": [], "understanding_status": "unavailable",
    }).ready_to_create


async def test_reused_question_id_does_not_hide_a_different_question():
    previous = GuidedIntakeState.model_validate({
        "raw_input": "带长辈旅行", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "questions": [BUDGET],
        "answers": [{"question_id": "budget_scope", "selected_option_ids": ["first"]}],
    })

    class Model:
        async def ainvoke(self, *_args, **_kwargs):
            return SimpleNamespace(content=json.dumps({
                "draft": {}, "recognized_requirements": [],
                "questions": [{**MOBILITY, "id": "budget_scope"}],
            }, ensure_ascii=False))

    assessed = await understand_trip_intake(
        previous.raw_input, previous.route_decision, llm=Model(),
        controlled_identity=ControlledTripIdentity.model_validate(IDENTITY), previous=previous,
    )
    assert assessed.questions[-1].question == "长辈爬楼是否受限？"
    assert assessed.questions[-1].id != previous.questions[0].id
    assert not assessed.ready_to_create


async def test_answered_question_history_is_preserved_when_more_questions_are_needed():
    questions = [question(f"q{index}", f"问题{index}？", "甲", "乙") for index in range(MAX_INTAKE_QUESTIONS)]
    previous = GuidedIntakeState.model_validate({
        "raw_input": "规划一次旅行", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "questions": questions,
        "answers": [{"question_id": q["id"], "selected_option_ids": ["first"]} for q in questions],
    })

    class Model:
        async def ainvoke(self, *_args, **_kwargs):
            return SimpleNamespace(content=json.dumps({
                "draft": {}, "recognized_requirements": [], "questions": [MOBILITY],
            }, ensure_ascii=False))

    assessed = await understand_trip_intake(
        previous.raw_input, previous.route_decision, llm=Model(),
        controlled_identity=ControlledTripIdentity.model_validate(IDENTITY), previous=previous,
    )
    assert [item.id for item in assessed.questions] == ["mobility"]
    assert len(assessed.archived_answers) == MAX_INTAKE_QUESTIONS
    assert assessed.archived_answers[0].question == "问题0？"
    assert assessed.archived_answers[0].answer == "甲"
    assert not assessed.ready_to_create
    answered_payload = assessed.model_dump(mode="json")
    answered_payload["answers"] = [{
        "question_id": "mobility", "selected_option_ids": ["first"], "supplement": "",
    }]
    answered = GuidedIntakeState.model_validate(answered_payload)
    seen = []

    class FinalModel:
        async def ainvoke(self, messages, **_kwargs):
            seen.extend(json.loads(messages[-1]["content"])["already_answered"])
            return SimpleNamespace(content=json.dumps({"draft": {}, "recognized_requirements": [], "questions": []}))

    complete = await understand_trip_intake(
        answered.raw_input, answered.route_decision, llm=FinalModel(),
        controlled_identity=ControlledTripIdentity.model_validate(IDENTITY), previous=answered,
    )
    assert len(seen) == MAX_INTAKE_QUESTIONS + 1
    assert "问题0？：甲" in merge_intake_answers(complete)
    assert "长辈爬楼是否受限？：需要避免爬楼" in merge_intake_answers(complete)


def test_client_cannot_rewrite_archived_answers():
    saved = GuidedIntakeState.model_validate({
        "intake_id": "it_" + "a" * 32, "intake_revision": 1,
        "raw_input": "规划旅行", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "archived_answers": [{"question_id": "q1", "question": "饮食禁忌？", "answer": "不吃牛肉"}],
    })
    submitted = saved.model_copy(update={"archived_answers": []})
    actual = apply_intake_answers(saved, submitted)
    assert actual.archived_answers[0].answer == "不吃牛肉"


async def test_oversized_saved_answers_are_stopped_before_a_model_call():
    previous = GuidedIntakeState.model_validate({
        "raw_input": "规划一次旅行", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "archived_answers": [
            {"question_id": f"past-{index}", "question": f"旧问题{index}？", "answer": "甲" * 500}
            for index in range(40)
        ],
    })

    class Model:
        async def ainvoke(self, *_args, **_kwargs):
            raise AssertionError("oversized intake must not call the model")

    with pytest.raises(IntakeUnderstandingUnavailable, match="过长"):
        await understand_trip_intake(
            previous.raw_input, previous.route_decision, llm=Model(),
            controlled_identity=ControlledTripIdentity.model_validate(IDENTITY), previous=previous,
        )


async def test_history_over_hard_limit_stops_without_discarding_answers():
    previous = GuidedIntakeState.model_validate({
        "raw_input": "规划一次旅行", "route_decision": {
            "route": "trip_planning", "confidence": 1, "requires_trip_draft": True,
        },
        "questions": [question("new", "待确认的问题？", "甲", "乙")],
        "answers": [{"question_id": "new", "selected_option_ids": ["first"]}],
        "archived_answers": [
            {"question_id": f"past-{index}", "question": f"旧问题{index}？", "answer": "甲"}
            for index in range(100)
        ],
    })
    class Model:
        async def ainvoke(self, *_args, **_kwargs):
            return SimpleNamespace(content=json.dumps({
                "draft": {}, "recognized_requirements": [],
                "questions": [question(f"new-{index}", f"新问题{index}？", "甲", "乙") for index in range(MAX_INTAKE_QUESTIONS)],
            }, ensure_ascii=False))
    with pytest.raises(IntakeUnderstandingUnavailable, match="开始新旅行"):
        await understand_trip_intake(
            previous.raw_input, previous.route_decision, llm=Model(),
            controlled_identity=ControlledTripIdentity.model_validate(IDENTITY), previous=previous,
        )
