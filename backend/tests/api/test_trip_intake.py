"""规划前的一轮需求收集。"""

from types import SimpleNamespace

import pytest

from tests.fixtures.chat_execution import resources as resources, request, decode, prepare
from travel_agent.conversation.chat import preparation
from travel_agent.conversation.chat.preparation import PreparedChat
from travel_agent.conversation.intake import IntakeUnderstandingUnavailable
from travel_agent.conversation.intake import merge_intake_answers
from travel_agent.conversation.intake import understand_trip_intake
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
    response = await request("POST", "/api/chat-stream", {"messages": [{"role": "user", "content": "想找一个适合第一次独自旅行的海边城市，预算5000元"}], "route": "trip_planning", "session_id": "intake-failure"})
    assert response.status_code == 200
    intake = decode(response)[0]["guided_intake"]
    assert intake["understanding_status"] == "unavailable"
    assert {"origin", "destinations", "dates"} <= set(intake["missing_fields"])
    assert not intake["ready_to_create"] and not resources.trip_run_store.runs


async def test_answers_are_saved_and_create_run_with_original_requirements(resources):
    saved = GuidedIntakeState.model_validate({
        "raw_input": "想找一个适合第一次独自旅行的海边城市，预算5000元",
        "route_decision": decision().model_dump(mode="json"),
        "questions": [{"id": "budget", "question": "预算包括往返交通吗？", "kind": "single", "options": [{"id": "all", "label": "包含往返交通和住宿"}, {"id": "local", "label": "仅当地花费"}]}],
    })
    await resources.chat_session_memory.save_guided_intake(session_id="intake-complete", guided_intake=saved)
    submitted = saved.model_dump(mode="json")
    submitted["raw_input"] = "客户端不能替换原始需求"
    submitted["answers"] = [{"question_id": "budget", "selected_option_ids": ["all"], "supplement": ""}]
    response = await request("PATCH", "/api/sessions/intake-complete/intake", submitted)
    assert response.status_code == 200
    assert response.json()["raw_input"] == saved.raw_input
    place = {"place_id": "osm:relation:1", "provider": "osm", "kind": "city", "name": "上海", "display_name": "上海", "country_code": "CN", "latitude": 31.23, "longitude": 121.47, "admin_path": []}
    identity = {"origin": place, "destinations": [{**place, "place_id": "osm:relation:2", "name": "青岛"}], "start_date": "2026-11-05", "end_date": "2026-11-08", "party": {"adults": 1, "children": 0}, "style": {"primary": "轻松慢游", "secondary_interests": []}}
    body = {"messages": [{"role": "user", "content": "确认旅行", "message_id": "confirm-intake"}], "session_id": "intake-complete", "route": "trip_planning", "guided_intake": submitted, "controlled_trip_identity": identity}
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
