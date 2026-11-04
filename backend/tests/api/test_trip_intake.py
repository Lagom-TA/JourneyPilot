"""两种入口进入理解阶段的 HTTP/SSE 契约。

表单表达正式规划，自然语言由模型分流；点击开始规划立即建 Run 并把
理解问题流回同一工作台。这里的深度工作流是脚本替身，多轮理解的真实
图行为在 test_multi_round_intake_flow.py 中验证。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.fixtures.chat_execution import (
    chat_body,
    decision,
    decode,
    request,
    resources as resources,
)
from travel_agent.conversation.intake_contracts import RouteName
from travel_agent.runtime.run_contracts import TripRunStatus


QUESTIONS = [
    {
        "id": "pace",
        "question": "这次更想慢慢逛还是把行程排满？",
        "kind": "single",
        "options": [
            {"id": "slow", "label": "慢慢逛"},
            {"id": "full", "label": "排满一些"},
        ],
    }
]
GATE_PAYLOAD = {
    "gate": "understanding",
    "revision": 1,
    "questions": QUESTIONS,
    "decision_options": ["answer", "cancel"],
    "approval_token": "understanding_gate.approval:offline",
}
SECOND_PAYLOAD = {
    "gate": "understanding",
    "revision": 2,
    "questions": [
        {
            "id": "dates",
            "question": "大概什么时候出发？",
            "kind": "single",
            "options": [{"id": "next_month", "label": "下个月"}],
        }
    ],
    "decision_options": ["answer", "cancel"],
    "approval_token": "understanding_gate.approval:offline-2",
}


class UnderstandingWorkflow:
    """先提出理解问题，回答后再问一轮；不进入后续研究。"""

    def __init__(self):
        self.resume_payloads = []
        self.inputs = []

    async def probe_checkpoint(self, run_id):
        return True, "checkpoint-1"

    async def astream(self, *, user_message, stream_queue, run_id, **kwargs):
        self.inputs.append(user_message)
        if kwargs.get("resume_from_checkpoint"):
            self.resume_payloads.append(kwargs.get("resume_payload"))
            yield {"__interrupt__": [SimpleNamespace(value=SECOND_PAYLOAD, id="interrupt-2")]}
            return
        await stream_queue.put(
            (
                "state",
                "understanding_agent",
                {"understanding_rounds": 1, "understanding_pending_questions": QUESTIONS},
            )
        )
        yield {"__interrupt__": [SimpleNamespace(value=GATE_PAYLOAD, id="interrupt-1")]}


@pytest.fixture
def deep_workflow(resources):
    workflow = UnderstandingWorkflow()
    resources.travel_workflow = workflow
    resources.checkpointer = object()
    return workflow


@pytest.fixture
def planning_route(monkeypatch):
    async def classify_planning(*args, **kwargs):
        return decision(RouteName.TRIP_PLANNING)

    monkeypatch.setattr(
        "travel_agent.conversation.chat.preparation.classify_route", classify_planning
    )


def _planning_body(message_id, **updates):
    return chat_body(
        route_decision=None,
        messages=[{"role": "user", "content": "想去青岛放松几天", "message_id": message_id}],
        **updates,
    )


async def test_natural_language_planning_streams_understanding_questions(
    resources, deep_workflow, planning_route
):
    response = await request("POST", "/api/chat-stream", _planning_body("m1"))
    assert response.status_code == 200
    events = decode(response)
    assert [event["type"] for event in events] == [
        "chat_start",
        "understanding_questions",
        "chat_complete",
    ]
    run_id = events[0]["run_id"]
    assert events[1]["run_id"] == run_id
    payload = events[1]["payload"]
    assert payload["gate"] == "understanding"
    assert payload["questions"] == QUESTIONS
    assert payload["approval_token"] == GATE_PAYLOAD["approval_token"]
    assert events[2]["run_status"] == TripRunStatus.AWAITING_INPUT.value
    detail = await resources.trip_run_store.get_detail(run_id)
    assert detail.run.status is TripRunStatus.AWAITING_INPUT
    assert detail.run.current_node == "understanding_gate"
    assert detail.state.pending_user_choice["gate"] == "understanding"
    # 自然语言请求没有带身份：Run 行此刻还没有身份，理解阶段完成后才补写。
    assert detail.run.controlled_trip_identity in (None, {})


async def test_answer_resumes_the_same_run_and_next_round_streams_back(
    resources, deep_workflow, planning_route
):
    first = decode(await request("POST", "/api/chat-stream", _planning_body("m1")))
    run_id = first[0]["run_id"]
    token = first[1]["payload"]["approval_token"]

    answer_body = {
        "messages": [{"role": "user", "content": "慢慢逛", "message_id": "m2"}],
        "session_id": first[0]["session_id"],
        "run_id": run_id,
        "route": "trip_planning",
        "gate_decision": {
            "action": "answer",
            "approval_token": token,
            "answers": [{"question_id": "pace", "text": "慢慢逛"}],
        },
    }
    response = await request("POST", "/api/chat-stream", answer_body)
    assert response.status_code == 200, response.text
    events = decode(response)
    assert [event["type"] for event in events] == [
        "chat_start",
        "understanding_questions",
        "chat_complete",
    ]
    assert events[1]["payload"]["revision"] == 2
    assert deep_workflow.resume_payloads == [
        {
            "action": "answer",
            "content": "",
            "answers": [{"question_id": "pace", "text": "慢慢逛"}],
            "approval_token": token,
        }
    ]
    detail = await resources.trip_run_store.get_detail(run_id)
    assert detail.run.status is TripRunStatus.AWAITING_INPUT
    assert detail.state.pending_user_choice["payload"]["revision"] == 2


@pytest.mark.parametrize("route", [None, "fast_answer"])
async def test_gate_answer_resumes_without_semantic_routing(
    resources, deep_workflow, planning_route, monkeypatch, route
):
    first = decode(await request("POST", "/api/chat-stream", _planning_body("m1")))

    async def forbidden(*_args, **_kwargs):
        pytest.fail("明确的门控操作不应调用意图分流模型")

    monkeypatch.setattr("travel_agent.conversation.chat.preparation.classify_route", forbidden)
    body = {
        "messages": [{"role": "user", "content": "慢慢逛", "message_id": "m2"}],
        "session_id": first[0]["session_id"],
        "run_id": first[0]["run_id"],
        "gate_decision": {
            "action": "answer",
            "approval_token": first[1]["payload"]["approval_token"],
            "answers": [{"question_id": "pace", "text": "慢慢逛"}],
        },
    }
    if route is not None:
        body["route"] = route
    response = await request("POST", "/api/chat-stream", body)
    assert response.status_code == 200, response.text
    assert deep_workflow.resume_payloads[0]["action"] == "answer"
    assert decode(response)[1]["payload"]["revision"] == 2


async def test_stale_answer_token_is_rejected_before_execution(
    resources, deep_workflow, planning_route
):
    first = decode(await request("POST", "/api/chat-stream", _planning_body("m1")))
    run_id = first[0]["run_id"]

    answer_body = {
        "messages": [{"role": "user", "content": "慢慢逛", "message_id": "m2"}],
        "session_id": first[0]["session_id"],
        "run_id": run_id,
        "route": "trip_planning",
        "gate_decision": {
            "action": "answer",
            "approval_token": "understanding_gate.approval:not-current",
            "answers": [{"question_id": "pace", "text": "慢慢逛"}],
        },
    }
    response = await request("POST", "/api/chat-stream", answer_body)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "plan_gate_version_stale"
    assert not deep_workflow.resume_payloads
    detail = await resources.trip_run_store.get_detail(run_id)
    assert detail.run.status is TripRunStatus.AWAITING_INPUT


async def test_answer_without_answers_is_a_client_error(resources, deep_workflow, planning_route):
    first = decode(await request("POST", "/api/chat-stream", _planning_body("m1")))

    answer_body = {
        "messages": [{"role": "user", "content": "慢慢逛", "message_id": "m2"}],
        "session_id": first[0]["session_id"],
        "run_id": first[0]["run_id"],
        "route": "trip_planning",
        "gate_decision": {
            "action": "answer",
            "approval_token": first[1]["payload"]["approval_token"],
        },
    }
    response = await request("POST", "/api/chat-stream", answer_body)
    assert response.status_code == 422


async def test_resubmitting_the_same_message_replays_the_pending_questions(
    resources, deep_workflow, planning_route
):
    body = _planning_body("m1")
    first = decode(await request("POST", "/api/chat-stream", body))
    again = decode(await request("POST", "/api/chat-stream", body))
    assert [event["type"] for event in again] == [
        "chat_start",
        "understanding_questions",
        "chat_complete",
    ]
    assert again[0]["run_id"] == first[0]["run_id"]
    assert again[1]["payload"]["questions"] == QUESTIONS
    # 重放没有再次执行工作流，也没有新开 Run。
    assert len(resources.trip_run_store.runs) == 1
    assert len(deep_workflow.inputs) == 1


@pytest.mark.parametrize("gate", ["understanding", "research"])
async def test_replay_preserves_the_pending_question_gate(gate):
    from travel_agent.conversation.chat.preparation import _replay_run_events

    payload = {"questions": QUESTIONS, "approval_token": "gate-token"}
    run = SimpleNamespace(
        run_id="run-1", assistant_message_id="message-1", status=TripRunStatus.AWAITING_INPUT
    )

    class Store:
        async def get_detail(self, run_id, *, event_limit):
            assert run_id == run.run_id and event_limit == 1
            return SimpleNamespace(state=SimpleNamespace(pending_user_choice={"gate": gate, "payload": payload}))

    events = [
        event async for event in _replay_run_events(
            run=run, trip_run_store=Store(), session_id="session-1",
            route_decision=decision(RouteName.TRIP_PLANNING),
        )
    ]
    assert [event["type"] for event in events] == ["chat_start", "understanding_questions", "chat_complete"]
    assert events[1]["gate"] == gate
    assert events[1]["payload"] == payload


async def test_form_entry_stores_the_confirmed_identity_on_the_run_row(
    resources, deep_workflow, planning_route
):
    place = {
        "place_id": "city_qingdao", "provider": "osm", "kind": "city",
        "name": "青岛", "display_name": "青岛", "country_code": "CN",
        "latitude": 36.07, "longitude": 120.38, "admin_path": [],
    }
    origin = dict(
        place, place_id="city_shanghai", name="上海", display_name="上海",
        latitude=31.23, longitude=121.47,
    )
    body = chat_body(
        route="trip_planning",
        messages=[{"role": "user", "content": "从上海去青岛放松几天", "message_id": "f1"}],
        controlled_trip_identity={
            "origin": origin,
            "destinations": [place],
            "start_date": "2026-11-05",
            "end_date": "2026-11-07",
            "party": {"adults": 2, "children": 0, "elderly_companions": False, "accessibility_required": False},
            "style": {"primary": "休闲", "secondary_interests": [], "source": "current"},
        },
    )
    events = decode(await request("POST", "/api/chat-stream", body))
    run_id = events[0]["run_id"]
    detail = await resources.trip_run_store.get_detail(run_id)
    assert detail.run.controlled_trip_identity["destinations"][0]["name"] == "青岛"


async def test_fast_answer_never_raises_planning_gates(resources):
    events = decode(await request("POST", "/api/chat-stream", chat_body()))
    types = [event["type"] for event in events]
    assert types[0] == "chat_start"
    assert "understanding_questions" not in types and "approval_gate_raised" not in types
    assert types[-1] == "chat_complete"


async def test_planning_without_checkpoint_support_is_refused(resources, planning_route):
    response = await request("POST", "/api/chat-stream", _planning_body("m1"))
    assert response.status_code == 409
    assert "checkpoint" in response.json()["detail"]
