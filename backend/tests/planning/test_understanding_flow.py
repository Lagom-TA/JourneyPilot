"""旅行理解的离线多轮、输入快照和格式校验。"""

from __future__ import annotations

from copy import deepcopy
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from travel_agent.planning.requirements.understanding import agent, gate
from travel_agent.planning.requirements.understanding.contracts import validate_understanding_questions
from travel_agent.planning.state import TravelAgentState
from travel_agent.tools.result import ReactOutcome, ReactResult


FORM = {
    "destinations": [{
        "place_id": "city_synthetic", "provider": "osm", "kind": "city", "name": "合成市",
        "display_name": "合成市", "country_code": "CN", "latitude": 30.0, "longitude": 120.0,
        "admin_path": [],
    }],
    "start_date": "2027-04-01", "end_date": "2027-04-03",
    "party": {"total": 1, "adults": 1, "children": 0},
}
MODEL_IDENTITY = {
    **FORM,
    "party": {"total": 2, "adults": 1, "children": 1},
}
QUESTION = {"id": "party", "question": "同行人数如何确定？", "kind": "single", "options": []}
PACK = {"pack_meta": {}, "constraints": [], "hard_constraints": [], "soft_preferences": []}


@pytest.fixture
def offline_understanding(monkeypatch):
    calls = []
    responses = []

    async def available():
        return []

    async def react(**kwargs):
        calls.append(deepcopy(kwargs["messages"]))
        assert responses, "离线测试没有配置模型结果"
        return ReactResult(outcome=ReactOutcome.FINAL_ANSWER, content=json.dumps(responses.pop(0), ensure_ascii=False))

    async def no_database(_state):
        raise AssertionError("测试不能加载真实约束来源")

    monkeypatch.setattr(agent, "get_available_tools", available)
    monkeypatch.setattr(agent, "get_model_router", lambda: object())
    monkeypatch.setattr(agent, "llm_for_task", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(agent, "streaming_react_loop", react)
    monkeypatch.setattr(agent, "build_planning_constraint_pack", no_database)
    return calls, responses


def _output(action, identity=MODEL_IDENTITY, questions=None):
    return {
        "action": action,
        "trip_identity": deepcopy(identity),
        "requirements": "已整理本次出行与交通偏好",
        "questions": questions if questions is not None else [],
    }


@pytest.mark.parametrize("with_form", [True, False])
async def test_submission_snapshot_survives_model_output_and_message_reset(offline_understanding, monkeypatch, with_form):
    calls, responses = offline_understanding
    form = deepcopy(FORM) if with_form else {}
    model_identity = deepcopy(MODEL_IDENTITY)
    if not with_form:
        model_identity["destinations"] = []
    responses.extend([_output("ask", model_identity, [QUESTION]), _output("ready", model_identity)])
    state = TravelAgentState(
        run_id="synthetic", user_query="与同伴看海，优先坐船",
        controlled_trip_identity=deepcopy(form), submitted_trip_identity=deepcopy(form),
        current_time="2027-03-01", constraint_pack=deepcopy(PACK),
    )
    first = await agent.understanding_agent_node(state)
    state = state.model_copy(update=first)
    assert state.submitted_trip_identity == form
    assert state.controlled_trip_identity["party"]["children"] == 1

    def answer(payload):
        return {
            "action": "answer", "approval_token": payload["approval_token"],
            "answers": [{"question_id": "party", "text": "两个人，坐船"}],
        }

    monkeypatch.setattr(gate, "interrupt", answer)
    gate_update = await gate.understanding_gate_node(state)
    gate_message = gate_update["understanding_messages"][-1]["content"]
    assert "助手提问（party）：同行人数如何确定？" in gate_message
    assert "旅行者回答：两个人，坐船" in gate_message
    state = state.model_copy(update={**gate_update, "understanding_messages": []})
    await agent.understanding_agent_node(state)

    payload = json.loads(calls[-1][-1]["content"])
    assert payload["本次旅行已有基础信息（可能包含模型整理）"]["party"]["children"] == 1
    assert payload["此前问答"] == [{
        "问题标识": "party", "助手提问": "同行人数如何确定？", "旅行者回答": "两个人，坐船",
    }]
    if with_form:
        assert payload["本次已提交表单（含默认值）"]["party"]["children"] == 0
    else:
        assert "本次已提交表单（含默认值）" not in payload
        assert state.submitted_trip_identity == {}


async def test_old_checkpoint_refreshes_prefix_and_retains_tools_and_role_marked_qa(offline_understanding):
    calls, responses = offline_understanding
    responses.append(_output("ready"))
    reference = {
        "category": "other", "value": "过去偏好水边", "status": "active",
        "source_refs": [{"source": "manual_memory"}],
    }
    old_prefix = {
        "相关偏好与记忆": "【本轮统一约束】过去偏好水边",
        "已知基础信息": FORM,
        "用户旅行想法": "与同伴看海",
    }
    tail = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t", "type": "function", "function": {"name": "search", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t", "content": "合成工具结果"},
        {"role": "assistant", "content": "询问同行人数"},
        {"role": "user", "content": "用户回答：\n问：同行人数如何确定？\n答：两个人"},
    ]
    state = TravelAgentState(
        run_id="old", user_query="与同伴看海", current_time="2027-03-01",
        submitted_trip_identity=None, controlled_trip_identity=deepcopy(MODEL_IDENTITY),
        current_requirements="上轮模型整理的旅行要求", understanding_rounds=1,
        understanding_qa=[{"question_id": "party", "question": "同行人数如何确定？", "answer": "两个人"}],
        understanding_messages=[
            {"role": "system", "content": "旧系统规则"},
            {"role": "user", "content": json.dumps(old_prefix, ensure_ascii=False)},
            *tail,
        ],
        constraint_pack={**PACK, "constraints": [reference], "soft_preferences": [reference]},
    )
    await agent.understanding_agent_node(state)
    sent = calls[0]
    assert sent[0]["role"] == "system" and "旧系统规则" not in sent[0]["content"]
    assert "背景参考" in json.loads(sent[1]["content"])
    current = json.loads(sent[2]["content"])
    assert "本次已提交表单（含默认值）" not in current
    assert current["此前输入中的基础信息（可能为提交值或模型整理）"]["party"]["children"] == 0
    assert current["本次旅行已有基础信息（可能包含模型整理）"]["party"]["children"] == 1
    assert current["此前问答"][0]["助手提问"] == "同行人数如何确定？"
    assert current["此前问答"][0]["旅行者回答"] == "两个人"
    assert "【本轮统一约束】" not in "".join(str(message.get("content")) for message in sent[:3])
    assert sent[3:6] == tail[:3]
    assert "问：同行人数如何确定？" in sent[6]["content"]


async def test_current_input_and_answers_take_priority_over_optional_history(offline_understanding):
    calls, responses = offline_understanding
    responses.append(_output("ready"))
    user_query = "本次旅行要求" * 2000
    answer = "此前确认的回答" * 500
    old_message = "早先历史" * 2300
    historical_item = {
        "type": "soft", "category": "other", "value": "历史参考" * 700,
        "status": "active", "source_refs": [{"source": "manual_memory"}],
    }
    state = TravelAgentState(
        run_id="budget", user_query=user_query, current_time="2027-03-01",
        controlled_trip_identity=deepcopy(FORM), submitted_trip_identity=deepcopy(FORM),
        understanding_qa=[{"question_id": "q", "question": "如何安排？", "answer": answer}],
        messages=[
            HumanMessage(content=old_message),
            AIMessage(content="本次还有哪些条件？"),
            HumanMessage(content=user_query),
        ],
        constraint_pack={**PACK, "constraints": [historical_item], "soft_preferences": [historical_item]},
    )

    await agent.understanding_agent_node(state)
    sent = calls[0]
    current = json.loads(sent[-1]["content"])
    assert current["用户旅行想法"] == user_query
    assert current["此前问答"][0]["旅行者回答"] == answer
    assert current["近期对话（按角色区分，判断是否与本次旅行有关）"] == [
        {"role": "assistant", "content": "本次还有哪些条件？"},
    ]
    assert "较早的对话未列出" in current["近期对话说明"]
    assert "未列出" in json.loads(sent[1]["content"])["背景参考"]["参考资料说明"]
    assert agent.estimate_request_tokens({"messages": sent})[0] <= agent.UNDERSTANDING_PROMPT_MAX_ESTIMATED_TOKENS


async def test_ready_with_nonempty_questions_is_repaired(offline_understanding):
    calls, responses = offline_understanding
    responses.extend([_output("ready", questions=[QUESTION]), _output("ready")])
    state = TravelAgentState(
        run_id="repair", user_query="看海", controlled_trip_identity=deepcopy(FORM),
        submitted_trip_identity=deepcopy(FORM), constraint_pack=deepcopy(PACK),
    )
    result = await agent.understanding_agent_node(state)
    assert len(calls) == 2
    assert "ready 时 questions 必须为空" in calls[1][-1]["content"]
    assert result["understanding_pending_questions"] is None


@pytest.mark.parametrize("questions", [
    [{"id": " ", "question": "问题", "options": []}],
    [{"id": "q", "question": "  ", "options": []}],
    [{"id": "q", "question": "问题", "options": [{"id": " ", "label": "选项"}]}],
    [{"id": "q", "question": "问题", "options": [{"id": "a", "label": "A"}, {"id": " a ", "label": "B"}]}],
    [{"id": "q", "question": "问题"}, {"id": " q ", "question": "另一个问题"}],
    [{"id": str(i), "question": "问题"} for i in range(5)],
])
def test_invalid_question_contract_is_rejected(questions):
    with pytest.raises(ValueError):
        validate_understanding_questions(questions)


async def test_workflow_snapshots_only_new_run_submissions(monkeypatch):
    from travel_agent.planning import workflow

    class Graph:
        def __init__(self):
            self.inputs = []

        async def astream(self, initial, **_kwargs):
            self.inputs.append(initial)
            yield "updates", {"synthetic": {}}

    graph = Graph()
    instance = object.__new__(workflow.TravelPlanningWorkflow)
    instance._graph = graph
    instance._checkpointer = None
    instance._delivery_bundle_store = object()
    instance._trip_run_store = object()
    for name in ("get_cost_ledger_store", "get_usage_recorder", "get_tool_audit_store"):
        monkeypatch.setattr(workflow, name, lambda: object())

    submitted = deepcopy(FORM)
    for form, action in ((submitted, ""), (None, ""), (deepcopy(FORM), "replan")):
        async for _ in instance.astream(
            user_message="看海", session_id="synthetic", run_id=f"run-{len(graph.inputs)}",
            controlled_trip_identity=form, refinement_action=action, plan_gate_enabled=False,
        ):
            pass
    submitted["party"]["children"] = 4
    assert graph.inputs[0].submitted_trip_identity["party"]["children"] == 0
    assert graph.inputs[1].submitted_trip_identity == {}
    assert graph.inputs[2].submitted_trip_identity == {}
    assert TravelAgentState.model_validate({"run_id": "old"}).submitted_trip_identity is None
