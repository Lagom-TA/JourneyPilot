"""规划前的一轮需求收集。"""

import json
from types import SimpleNamespace

import pytest

from tests.fixtures.chat_execution import resources as resources, request, decode, prepare
import travel_agent.conversation.intake as intake_module
from travel_agent.conversation.chat import preparation
from travel_agent.conversation.chat.errors import PreparationRefused, PreparationRejection
from travel_agent.conversation.chat.preparation import ImmediateChat, PreparedChat
from travel_agent.conversation.intake import IntakeUnderstandingUnavailable
from travel_agent.conversation.intake import merge_intake_answers
from travel_agent.conversation.intake import DEFAULT_ANSWER_LABEL
from travel_agent.conversation.intake import DEFAULT_ANSWER_OPTION_ID
from travel_agent.conversation.intake import understand_trip_intake
from travel_agent.conversation.intake import unavailable_intake
from travel_agent.conversation.intake import validate_intake_answers
from travel_agent.conversation.intake_contracts import GuidedIntakeState
from travel_agent.conversation.intake_contracts import RouteDecision
from travel_agent.conversation.intake_contracts import IntakeDraft
from travel_agent.conversation.intake_contracts import RouteName
from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity


def decision():
    return RouteDecision(route=RouteName.TRIP_PLANNING, confidence=1, requires_trip_draft=True)


async def test_model_generates_only_the_necessary_question_schema():
    class LLM:
        async def ainvoke(self, messages, **kwargs):
            return SimpleNamespace(content='{"draft":{},"recognized_requirements":["想去海边"],"questions":[{"id":"dates","question":"准备什么时候出发？","kind":"single","options":[{"id":"weekend","label":"近期周末"},{"id":"later","label":"再晚一些"}]}]}')

    intake = await understand_trip_intake("想找一个海边城市", decision(), llm=LLM())
    assert intake.recognized_requirements == ["想去海边"]
    assert intake.questions[0].kind == "single"
    assert intake.questions[0].options[1].label == "再晚一些"
    assert {"origin", "destinations", "dates", "party", "place_confirmation"} <= set(intake.missing_fields)
    assert not intake.ready_to_create


def test_answers_and_optional_supplements_merge_into_one_requirement_text():
    intake = GuidedIntakeState.model_validate({
        "raw_input": "想找一个海边城市",
        "route_decision": decision().model_dump(mode="json"),
        "questions": [{"id": "dates", "question": "什么时候出发？", "kind": "single", "options": [{"id": "weekend", "label": "近期周末"}, {"id": "later", "label": "再晚一些"}]}],
        "answers": [{"question_id": "dates", "selected_option_ids": ["weekend"], "supplement": "周五晚上走"}],
        "additional_requirements": "预算五千元",
    })
    validate_intake_answers(intake)
    text = merge_intake_answers(intake)
    assert "想找一个海边城市" in text
    assert "什么时候出发？：近期周末；周五晚上走" in text
    assert "其他补充：预算五千元" in text


def test_single_choice_rejects_multiple_options():
    intake = GuidedIntakeState.model_validate({
        "raw_input": "规划旅行",
        "route_decision": decision().model_dump(mode="json"),
        "questions": [{"id": "party", "question": "几位同行？", "kind": "single", "options": [{"id": "one", "label": "一位"}, {"id": "two", "label": "两位"}]}],
        "answers": [{"question_id": "party", "selected_option_ids": ["one", "two"]}],
    })
    with pytest.raises(ValueError, match="单选题"):
        validate_intake_answers(intake)


async def test_empty_model_output_is_unavailable_instead_of_ready():
    class LLM:
        async def ainvoke(self, *_args, **_kwargs):
            return "{}"
    with pytest.raises(IntakeUnderstandingUnavailable):
        await understand_trip_intake("想找一个海边城市，预算5000元", decision(), llm=LLM())


async def test_intake_failure_keeps_missing_fields_without_creating_run(resources, monkeypatch):
    async def unavailable(*_args, **_kwargs):
        raise IntakeUnderstandingUnavailable("unavailable")
    monkeypatch.setattr(preparation, "understand_trip_intake", unavailable)
    resources.checkpointer = object()
    response = await request("POST", "/api/chat-stream", {"messages": [{"role": "user", "content": "想找一个适合第一次独自旅行的海边城市，预算5000元"}], "route": "trip_planning", "session_id": "intake-failure"})
    assert response.status_code == 200
    intake = decode(response)[0]["guided_intake"]
    assert intake["understanding_status"] == "unavailable"
    assert {"origin", "destinations", "dates"} <= set(intake["missing_fields"])
    assert not intake["ready_to_create"] and not resources.trip_run_store.runs


async def test_answers_are_saved_and_create_run_with_original_requirements(resources, monkeypatch):
    class LLM:
        async def ainvoke(self, *_args, **_kwargs):
            return SimpleNamespace(content=json.dumps({
                "draft": {}, "recognized_requirements": [], "questions": [],
            }, ensure_ascii=False))

    monkeypatch.setattr(intake_module, "get_model_router", lambda: object())
    monkeypatch.setattr(intake_module, "llm_for_task", lambda *_args, **_kwargs: LLM())
    saved = GuidedIntakeState.model_validate({
        "raw_input": "想找一个适合第一次独自旅行的海边城市，预算5000元",
        "route_decision": decision().model_dump(mode="json"),
        "questions": [{"id": "budget", "question": "预算包括往返交通吗？", "kind": "single", "options": [{"id": "all", "label": "包含往返交通和住宿"}, {"id": "local", "label": "仅当地花费"}]}],
    })
    await resources.chat_session_memory.save_guided_intake(session_id="intake-complete", guided_intake=saved)
    saved = await resources.chat_session_memory.get_guided_intake(session_id="intake-complete", user_id="local")
    submitted = saved.model_dump(mode="json")
    submitted["raw_input"] = "客户端不能替换原始需求"
    submitted["answers"] = [{"question_id": "budget", "selected_option_ids": ["all"], "supplement": ""}]
    response = await request("PATCH", "/api/sessions/intake-complete/intake", submitted)
    assert response.status_code == 200
    assert response.json()["raw_input"] == saved.raw_input
    submitted = response.json()
    place = {"place_id": "osm:relation:1", "provider": "osm", "kind": "city", "name": "上海", "display_name": "上海", "country_code": "CN", "latitude": 31.23, "longitude": 121.47, "admin_path": []}
    identity = {"origin": place, "destinations": [{**place, "place_id": "osm:relation:2", "name": "青岛"}], "start_date": "2026-11-05", "end_date": "2026-11-08", "party": {"adults": 1, "children": 0}, "style": {"primary": "轻松慢游", "secondary_interests": []}}
    body = {"messages": [{"role": "user", "content": "确认旅行", "message_id": "confirm-intake"}], "session_id": "intake-complete", "route": "trip_planning", "guided_intake": submitted, "controlled_trip_identity": identity}
    resources.checkpointer = object()
    prepared = await prepare(body, resources)
    assert isinstance(prepared, PreparedChat)
    assert saved.raw_input in prepared.user_message
    assert "包含往返交通和住宿" in prepared.user_message
    assert "客户端不能替换" not in prepared.user_message
    assert prepared.user_message.count("用户补充确认") == 1
    assert prepared.authoritative_controlled_trip_identity["destinations"][0]["name"] == "青岛"
    assert len(resources.trip_run_store.runs) == 1
    assert await resources.chat_session_memory.get_guided_intake(session_id="intake-complete", user_id="local") is not None
    from travel_agent.runtime.run_contracts import TripRunStatus
    await resources.trip_run_store.transition_status(prepared.trip_run.run_id, TripRunStatus.RUNNING)
    await resources.chat_session_memory.clear_guided_intake(session_id="intake-complete", user_id="local")
    await prepared.lease_keeper.release(reason="test_complete")
    replay = await prepare(body, resources)
    from travel_agent.conversation.chat.preparation import ImmediateChat
    assert isinstance(replay, ImmediateChat)
    replay_events = [event async for event in replay.events]
    assert replay_events[0]["run_id"] == prepared.trip_run.run_id
    assert len(resources.trip_run_store.runs) == 1


def _place(name: str, place_id: str) -> dict:
    return {"place_id": place_id, "provider": "osm", "kind": "city", "name": name, "display_name": name, "country_code": "CN", "latitude": 31.2, "longitude": 121.4, "admin_path": []}


def test_controlled_identity_and_intake_draft_share_a_five_destination_limit():
    origin = _place("上海", "osm:relation:origin")
    destinations = [_place(name, f"osm:relation:{index}") for index, name in enumerate(["苏州", "杭州", "南京", "宁波", "绍兴"], start=1)]
    identity = ControlledTripIdentity.model_validate({
        "origin": origin,
        "destinations": destinations,
        "start_date": "2026-11-05",
        "end_date": "2026-11-09",
        "party": {"adults": 1, "children": 0},
        "style": {"primary": "经典均衡", "secondary_interests": []},
    })
    assert [place.name for place in identity.destinations] == ["苏州", "杭州", "南京", "宁波", "绍兴"]
    draft = IntakeDraft.model_validate({
        "destination_queries": ["苏州", "杭州", "南京", "宁波", "绍兴"],
        "confirmed_destinations": destinations,
    })
    assert [place.name for place in draft.confirmed_destinations] == ["苏州", "杭州", "南京", "宁波", "绍兴"]

    with pytest.raises(ValueError, match="最多 5 个目的地"):
        ControlledTripIdentity.model_validate({
            "origin": origin,
            "destinations": destinations + [_place("湖州", "osm:relation:6")],
            "start_date": "2026-11-05",
            "end_date": "2026-11-10",
            "party": {"adults": 1, "children": 0},
            "style": {"primary": "经典均衡", "secondary_interests": []},
        })
    with pytest.raises(ValueError, match="at most 5 items"):
        IntakeDraft.model_validate({
            "destination_queries": ["苏州", "杭州", "南京", "宁波", "绍兴", "湖州"],
            "confirmed_destinations": destinations + [_place("湖州", "osm:relation:6")],
        })


def test_required_answer_cannot_be_omitted():
    intake = GuidedIntakeState.model_validate({"raw_input": "规划旅行", "route_decision": decision().model_dump(mode="json"), "questions": [{"id": "budget", "question": "预算范围？", "kind": "single", "options": [{"id": "all", "label": "全程"}, {"id": "local", "label": "当地"}]}]})
    with pytest.raises(ValueError, match="尚未回答"):
        validate_intake_answers(intake)


def _identity(destination: str = "青岛") -> ControlledTripIdentity:
    place = {"place_id": "osm:relation:1", "provider": "osm", "kind": "city", "name": "上海", "display_name": "上海", "country_code": "CN", "latitude": 31.23, "longitude": 121.47, "admin_path": []}
    return ControlledTripIdentity.model_validate({
        "origin": place,
        "destinations": [{**place, "place_id": "osm:relation:2", "name": destination}],
        "start_date": "2026-11-05",
        "end_date": "2026-11-08",
        "party": {"adults": 1, "children": 0},
        "style": {"primary": "轻松慢游", "secondary_interests": ["海边"]},
    })


def _question(question_id: str = "budget_scope", text: str = "总预算是否包含往返交通？") -> dict:
    return {
        "id": question_id,
        "question": text,
        "kind": "single",
        "options": [
            {"id": "all", "label": "包含往返交通和住宿"},
            {"id": "local", "label": "仅当地花费"},
        ],
    }


async def test_unavailable_assessment_is_reevaluated_when_answers_are_submitted(resources, monkeypatch):
    identity = _identity()
    saved = unavailable_intake("规划这趟旅行，总预算12000元", decision())
    await resources.chat_session_memory.save_guided_intake(
        session_id="identity-unavailable-answer", guided_intake=saved
    )
    saved = await resources.chat_session_memory.get_guided_intake(session_id="identity-unavailable-answer", user_id="local")
    calls = []

    async def assess(raw_input, route_decision, *, controlled_identity=None, previous=None, **_kwargs):
        calls.append((raw_input, controlled_identity, previous))
        return GuidedIntakeState.model_validate({
            "raw_input": raw_input,
            "route_decision": route_decision.model_dump(mode="json"),
            "controlled_identity": identity.model_dump(mode="json"),
            "draft": identity.model_dump(mode="json"),
            "questions": [],
            "missing_fields": [],
        })

    monkeypatch.setattr(preparation, "understand_trip_intake", assess)
    resources.checkpointer = object()
    body = {
        "messages": [{"role": "user", "content": "确认旅行", "message_id": "identity-unavailable-answer"}],
        "session_id": "identity-unavailable-answer",
        "route": "trip_planning",
        "guided_intake": saved.model_dump(mode="json"),
        "controlled_trip_identity": identity.model_dump(mode="json"),
    }
    prepared = await prepare(body, resources)
    assert isinstance(prepared, PreparedChat)
    assert len(calls) == 1
    assert calls[0][0] == saved.raw_input
    assert calls[0][1] == identity
    assert calls[0][2].understanding_status == "unavailable"
    assert len(resources.trip_run_store.runs) == 1


async def test_reassessment_includes_submitted_additional_requirements(resources, monkeypatch):
    identity = _identity()
    saved = unavailable_intake("规划这趟旅行，预算12000元，带长辈", decision())
    await resources.chat_session_memory.save_guided_intake(
        session_id="identity-additional-requirements", guided_intake=saved
    )
    saved = await resources.chat_session_memory.get_guided_intake(session_id="identity-additional-requirements", user_id="local")
    submitted = saved.model_copy(update={
        "additional_requirements": "总预算12000元，带长辈，不确定是否自驾",
    })
    payloads = []

    class LLM:
        async def ainvoke(self, messages, **kwargs):
            payloads.append(json.loads(messages[-1]["content"]))
            return SimpleNamespace(content=json.dumps({
                "draft": {},
                "recognized_requirements": [],
                "questions": [],
            }, ensure_ascii=False))

    monkeypatch.setattr(intake_module, "get_model_router", lambda: object())
    monkeypatch.setattr(intake_module, "llm_for_task", lambda *_args, **_kwargs: LLM())
    resources.checkpointer = object()
    body = {
        "messages": [{"role": "user", "content": "确认旅行", "message_id": "identity-additional-requirements"}],
        "session_id": "identity-additional-requirements",
        "route": "trip_planning",
        "guided_intake": submitted.model_dump(mode="json"),
        "controlled_trip_identity": identity.model_dump(mode="json"),
    }
    prepared = await prepare(body, resources)
    assert isinstance(prepared, PreparedChat)
    assert payloads[0]["additional_requirements"] == submitted.additional_requirements
    assert "总预算12000元" in prepared.user_message
    assert len(resources.trip_run_store.runs) == 1
    await prepared.lease_keeper.release(reason="test_complete")


async def test_reassessment_prompt_keeps_additional_requirements_without_answers():
    previous = GuidedIntakeState.model_validate({
        "raw_input": "规划旅行",
        "route_decision": decision().model_dump(mode="json"),
        "additional_requirements": "预算已明确为12000元，包含往返交通和住宿",
    })
    payloads = []

    class LLM:
        async def ainvoke(self, messages, **kwargs):
            payloads.append(json.loads(messages[-1]["content"]))
            return SimpleNamespace(content=json.dumps({
                "draft": {},
                "recognized_requirements": [],
                "questions": [],
            }, ensure_ascii=False))

    await understand_trip_intake(
        previous.raw_input,
        decision(),
        llm=LLM(),
        controlled_identity=_identity(),
        previous=previous,
    )
    assert payloads[0]["additional_requirements"] == previous.additional_requirements
    assert payloads[0]["already_answered"] == []


async def test_unavailable_assessment_still_unavailable_blocks_run_after_answers(resources, monkeypatch):
    identity = _identity()
    saved = unavailable_intake("规划这趟旅行，总预算12000元", decision())
    await resources.chat_session_memory.save_guided_intake(
        session_id="identity-unavailable-retry", guided_intake=saved
    )
    saved = await resources.chat_session_memory.get_guided_intake(session_id="identity-unavailable-retry", user_id="local")
    calls = []

    async def unavailable(*_args, **_kwargs):
        calls.append(True)
        raise IntakeUnderstandingUnavailable("offline")

    monkeypatch.setattr(preparation, "understand_trip_intake", unavailable)
    resources.checkpointer = object()
    body = {
        "messages": [{"role": "user", "content": "确认旅行", "message_id": "identity-unavailable-retry"}],
        "session_id": "identity-unavailable-retry",
        "route": "trip_planning",
        "guided_intake": saved.model_dump(mode="json"),
        "controlled_trip_identity": identity.model_dump(mode="json"),
    }
    with pytest.raises(PreparationRefused) as caught:
        await prepare(body, resources)
    assert caught.value.reason is PreparationRejection.INTAKE_UNAVAILABLE
    assert calls == [True]
    assert not resources.trip_run_store.runs


async def test_material_gap_that_mentions_identity_fields_is_not_dropped():
    identity = _identity()

    class LLM:
        async def ainvoke(self, *_args, **_kwargs):
            return SimpleNamespace(content=json.dumps({
                "draft": {},
                "recognized_requirements": ["总预算12000元"],
                "questions": [_question(
                    "budget_scope",
                    "总预算是否包含出发地至目的地的往返交通？",
                )],
            }, ensure_ascii=False))

    assessed = await understand_trip_intake(
        "规划这趟旅行，总预算12000元",
        decision(),
        llm=LLM(),
        controlled_identity=identity,
    )
    assert [item.id for item in assessed.questions] == ["budget_scope"]
    assert assessed.questions[0].options[-1].id == DEFAULT_ANSWER_OPTION_ID
    assert assessed.ready_to_create is False


async def test_real_identity_question_is_still_removed_when_identity_is_confirmed():
    identity = _identity()

    class LLM:
        async def ainvoke(self, *_args, **_kwargs):
            return SimpleNamespace(content=json.dumps({
                "draft": {},
                "recognized_requirements": [],
                "questions": [_question("schedule", "出发地是哪里？")],
            }, ensure_ascii=False))

    assessed = await understand_trip_intake(
        "规划这趟旅行",
        decision(),
        llm=LLM(),
        controlled_identity=identity,
    )
    assert assessed.questions == []


async def test_complete_identity_with_material_gap_stops_for_clarification(resources, monkeypatch):
    identity = _identity()
    observed = {}

    original = preparation.understand_trip_intake

    class LLM:
        async def ainvoke(self, *_args, **_kwargs):
            return SimpleNamespace(content=json.dumps({
                "draft": {},
                "recognized_requirements": ["总预算12000元"],
                "questions": [_question()],
            }, ensure_ascii=False))

    async def assess(raw_input, route_decision, *, controlled_identity=None, previous=None, **kwargs):
        observed["raw_input"] = raw_input
        observed["identity"] = controlled_identity
        return await original(
            raw_input,
            route_decision,
            llm=LLM(),
            controlled_identity=controlled_identity,
            previous=previous,
        )

    monkeypatch.setattr(preparation, "understand_trip_intake", assess)
    resources.checkpointer = object()
    body = {
        "messages": [{"role": "user", "content": "规划这趟旅行，总预算12000元", "message_id": "identity-gap"}],
        "session_id": "identity-gap",
        "route": "trip_planning",
        "controlled_trip_identity": identity.model_dump(mode="json"),
    }
    prepared = await prepare(body, resources)
    assert isinstance(prepared, ImmediateChat)
    events = [event async for event in prepared.events]
    payload = events[0]["guided_intake"]
    assert observed["identity"] == identity
    assert payload["questions"][0]["id"] == "budget_scope"
    assert payload["questions"][0]["options"][-1] == {
        "id": DEFAULT_ANSWER_OPTION_ID,
        "label": DEFAULT_ANSWER_LABEL,
    }
    assert not resources.trip_run_store.runs
    saved = await resources.chat_session_memory.get_guided_intake(session_id="identity-gap", user_id="local")
    assert saved.controlled_identity.origin.name == "上海"


async def test_refresh_keeps_pending_questions_and_does_not_reassess(resources, monkeypatch):
    identity = _identity()
    saved = GuidedIntakeState.model_validate({
        "raw_input": "规划这趟旅行，总预算12000元",
        "route_decision": decision().model_dump(mode="json"),
        "controlled_identity": identity.model_dump(mode="json"),
        "draft": identity.model_dump(mode="json"),
        "questions": [_question()],
        "missing_fields": [],
    })
    await resources.chat_session_memory.save_guided_intake(
        session_id="identity-refresh", guided_intake=saved
    )

    async def should_not_reassess(*_args, **_kwargs):
        raise AssertionError("a pending saved intake must be shown again, not reassessed")

    monkeypatch.setattr(preparation, "understand_trip_intake", should_not_reassess)
    resources.checkpointer = object()
    body = {
        "messages": [{"role": "user", "content": "规划这趟旅行，总预算12000元", "message_id": "identity-refresh"}],
        "session_id": "identity-refresh",
        "route": "trip_planning",
        "controlled_trip_identity": identity.model_dump(mode="json"),
    }
    prepared = await prepare(body, resources)
    assert isinstance(prepared, ImmediateChat)
    events = [event async for event in prepared.events]
    assert [item["id"] for item in events[0]["guided_intake"]["questions"]] == ["budget_scope"]
    assert not resources.trip_run_store.runs


async def test_complete_unambiguous_identity_creates_run_without_extra_questions(resources, monkeypatch):
    identity = _identity()
    calls = []

    async def assess(raw_input, route_decision, *, controlled_identity=None, previous=None, **_kwargs):
        calls.append(controlled_identity)
        return GuidedIntakeState.model_validate({
            "raw_input": raw_input,
            "route_decision": route_decision.model_dump(mode="json"),
            "controlled_identity": identity.model_dump(mode="json"),
            "draft": identity.model_dump(mode="json"),
            "questions": [],
            "missing_fields": [],
        })

    monkeypatch.setattr(preparation, "understand_trip_intake", assess)
    resources.checkpointer = object()
    body = {
        "messages": [{"role": "user", "content": "从上海去青岛，11月5日至8日，一个人，轻松慢游", "message_id": "identity-clear"}],
        "session_id": "identity-clear",
        "route": "trip_planning",
        "controlled_trip_identity": identity.model_dump(mode="json"),
    }
    prepared = await prepare(body, resources)
    assert isinstance(prepared, PreparedChat)
    assert calls == [identity]
    assert "青岛" in prepared.user_message and "2026-11-05" in prepared.user_message
    assert "用户补充确认" not in prepared.user_message
    assert len(resources.trip_run_store.runs) == 1


async def test_answered_and_default_questions_are_not_reasked():
    identity = _identity()
    previous = GuidedIntakeState.model_validate({
        "raw_input": "预算12000元",
        "route_decision": decision().model_dump(mode="json"),
        "questions": [_question()],
        "answers": [{"question_id": "budget_scope", "selected_option_ids": [DEFAULT_ANSWER_OPTION_ID]}],
    })

    class LLM:
        async def ainvoke(self, messages, **kwargs):
            return SimpleNamespace(content=json.dumps({
                "draft": {},
                "recognized_requirements": ["预算12000元"],
                "questions": [
                    _question(),
                    {
                        "id": "pace",
                        "question": "希望紧凑还是留白？",
                        "kind": "single",
                        "options": [
                            {"id": "packed", "label": "紧凑"},
                            {"id": "slow", "label": "留白"},
                        ],
                    },
                ],
            }, ensure_ascii=False))

    assessed = await understand_trip_intake(
        previous.raw_input,
        decision(),
        llm=LLM(),
        controlled_identity=identity,
        previous=previous,
    )
    assert [item.id for item in assessed.questions] == ["budget_scope", "pace"]
    assert assessed.answers[0].selected_option_ids == [DEFAULT_ANSWER_OPTION_ID]
    assert assessed.questions[1].options[-1].id == DEFAULT_ANSWER_OPTION_ID
    assert assessed.ready_to_create is False


async def test_complete_identity_assessment_failure_refuses_without_creating_run(resources, monkeypatch):
    async def unavailable(*_args, **_kwargs):
        raise IntakeUnderstandingUnavailable("offline")

    monkeypatch.setattr(preparation, "understand_trip_intake", unavailable)
    resources.checkpointer = object()
    body = {
        "messages": [{"role": "user", "content": "规划这趟旅行", "message_id": "identity-unavailable"}],
        "session_id": "identity-unavailable",
        "route": "trip_planning",
        "controlled_trip_identity": _identity().model_dump(mode="json"),
    }
    with pytest.raises(PreparationRefused) as caught:
        await prepare(body, resources)
    assert caught.value.reason is PreparationRejection.INTAKE_UNAVAILABLE
    assert not resources.trip_run_store.runs


async def test_disabled_plan_gate_rejects_natural_entry_before_assessment(resources, monkeypatch):
    async def should_not_assess(*_args, **_kwargs):
        raise AssertionError("a disabled plan gate must reject before intake assessment")

    monkeypatch.setattr(preparation, "understand_trip_intake", should_not_assess)
    body = {
        "messages": [{"role": "user", "content": "规划这趟旅行", "message_id": "gate-natural"}],
        "session_id": "gate-natural",
        "route": "trip_planning",
        "plan_gate": False,
    }
    with pytest.raises(PreparationRefused) as caught:
        await prepare(body, resources)
    assert caught.value.reason is PreparationRejection.PLAN_GATE_DISABLED
    assert not resources.trip_run_store.runs


async def test_unsupported_plan_gate_rejects_deep_planning_before_run(resources, monkeypatch):
    identity = _identity()
    calls = []

    async def no_gap(raw_input, route_decision, *, controlled_identity=None, previous=None, **_kwargs):
        calls.append(controlled_identity)
        return GuidedIntakeState.model_validate({
            "raw_input": raw_input,
            "route_decision": route_decision.model_dump(mode="json"),
            "controlled_identity": identity.model_dump(mode="json"),
            "draft": identity.model_dump(mode="json"),
            "questions": [],
            "missing_fields": [],
        })

    monkeypatch.setattr(preparation, "understand_trip_intake", no_gap)
    base = {
        "messages": [{"role": "user", "content": "规划这趟旅行", "message_id": "gate-check"}],
        "session_id": "gate-check",
        "route": "trip_planning",
        "controlled_trip_identity": identity.model_dump(mode="json"),
    }
    with pytest.raises(PreparationRefused) as missing_checkpoint:
        await prepare(base, resources)
    assert missing_checkpoint.value.reason is PreparationRejection.GATE_REQUIRES_CHECKPOINT
    assert not resources.trip_run_store.runs
    assert calls == []

    resources.checkpointer = object()
    with pytest.raises(PreparationRefused) as disabled:
        await prepare({**base, "plan_gate": False}, resources)
    assert disabled.value.reason is PreparationRejection.PLAN_GATE_DISABLED
    assert not resources.trip_run_store.runs
    assert calls == []
