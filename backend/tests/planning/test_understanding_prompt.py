"""旅行理解的来源、对话角色与输入顺序。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from travel_agent.llm.token_counting import estimate_message_tokens
from travel_agent.planning.requirements.understanding.prompts import (
    initial_understanding_messages,
    understanding_context_payload,
    understanding_system_prompt,
)


def _state(**overrides):
    values = dict(
        constraint_pack={},
        preset_context="",
        session_anchor=None,
        controlled_trip_identity=None,
        submitted_trip_identity=None,
        understanding_messages=[],
        current_requirements="",
        refinement_context="",
        user_query="安排一次旅行",
        understanding_qa=[],
        pending_intent_amendments=[],
        applied_intent_amendment_ids=set(),
        plan_gate_amendment=None,
        current_time="2027-03-01",
        messages=[],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _item(value, *sources):
    return {
        "category": "other",
        "value": value,
        "status": "active",
        "source_refs": [{"source": source} for source in sources],
    }


def _message(role, text):
    return SimpleNamespace(type=role, content=text)


def test_system_prompt_states_equal_inputs_corrections_and_existing_rules():
    prompt = understanding_system_prompt()

    for phrase in (
        "包括默认值",
        "同等考虑",
        "完整的一问一答",
        "同一条消息中的助手提问和旅行者回答按各自标注理解",
        "后续明确更正",
        "中性说明分歧",
        "同一趟旅行此前已确认的信息",
        "摘要和约束整理可能包含模型推断",
        "表单，也可能是此前模型整理的结果",
        "单次最多 14 天",
        "每轮最多 4 题",
        "地点工具真实返回",
        "日期用 YYYY-MM-DD",
        '"action": "ask 或 ready"',
    ):
        assert phrase in prompt


def test_without_historical_reference_only_system_and_current_input_are_sent():
    identity = {
        "party": {"total": 1, "adults": 1, "children": 0},
        "style": {"primary": "均衡", "source": "current"},
    }
    state = _state(
        user_query="和朋友同行，尽量安排水路交通",
        controlled_trip_identity=identity,
        submitted_trip_identity=identity,
        constraint_pack={"soft_preferences": [_item("节奏轻松", "preset")]},
        session_anchor={"summary": "", "key_constraints": []},
    )

    messages = initial_understanding_messages(state)
    assert [message["role"] for message in messages] == ["system", "user"]
    current = json.loads(messages[-1]["content"])
    assert current["用户旅行想法"] == state.user_query
    assert current["本次已提交表单（含默认值）"] == identity
    assert current["本次已提交表单（含默认值）"]["party"]["children"] == 0
    assert current["本次应用的预设与输入整理"][0]["内容"] == "节奏轻松"
    assert "预设" in current["本次应用的预设与输入整理"][0]["来源"]
    assert "背景参考" not in current


def test_reference_precedes_current_and_keeps_its_actual_sources():
    state = _state(
        constraint_pack={
            "hard_constraints": [_item("之前偏好午后出发", "manual_profile")],
            "soft_preferences": [
                _item("旧记忆里的旅行节奏", "manual_memory"),
                _item("当前预设侧重自然景观", "preset"),
                _item("不明来历的偏好"),
                _item("混合来源的整理", "current_query", "memory_fact"),
            ],
        },
        session_anchor={"summary": "对话中提过照片", "key_constraints": ["可能需要无障碍"]},
        user_query="本次上午出发",
    )

    messages = initial_understanding_messages(state)
    assert [message["role"] for message in messages] == ["system", "user", "user"]
    reference = json.loads(messages[1]["content"])["背景参考"]
    current = json.loads(messages[2]["content"])
    entries = {item["内容"]: item["来源"] for item in reference["画像、记忆与其他参考"]}
    assert "画像" in entries["之前偏好午后出发"]
    assert "记忆" in entries["旧记忆里的旅行节奏"]
    assert "来源未注明" in entries["不明来历的偏好"]
    assert "记忆" in entries["混合来源的整理"]
    assert reference["本次会话较早对话摘要（模型整理）"] == {
        "摘要": "对话中提过照片", "摘要中的约束": ["可能需要无障碍"]
    }
    assert current["用户旅行想法"] == "本次上午出发"
    assert current["本次应用的预设与输入整理"][0]["内容"] == "当前预设侧重自然景观"
    assert "旧记忆里的旅行节奏" not in messages[-1]["content"]


def test_reference_limits_historical_entries_without_truncating_current_inputs():
    references = [_item(f"历史参考{i}", "manual_memory") for i in range(9)]
    current_items = [_item(f"本次要求{i}", "current_query") for i in range(9)]
    state = _state(
        constraint_pack={"soft_preferences": [*references, *current_items]},
        understanding_qa=[{"question_id": "q", "question": "偏好什么交通？", "answer": "坐船"}],
        user_query="想去看海",
    )

    messages = initial_understanding_messages(state)
    reference = json.loads(messages[1]["content"])["背景参考"]
    current = json.loads(messages[2]["content"])
    assert [item["内容"] for item in reference["画像、记忆与其他参考"]] == [
        f"历史参考{i}" for i in range(6)
    ]
    assert "未列出" in reference["参考资料说明"]
    assert len(current["本次应用的预设与输入整理"]) == 9
    assert current["此前问答"][0]["旅行者回答"] == "坐船"
    assert current["用户旅行想法"] == "想去看海"


def test_reference_token_budget_omits_whole_oversized_records_and_marks_omission():
    huge = "很长的参考资料" * 4000
    state = _state(
        constraint_pack={"soft_preferences": [
            _item(huge, "manual_memory"), _item("旧偏好水边", "manual_memory"),
        ]},
        session_anchor={"summary": huge, "key_constraints": ["曾提出坐船", huge]},
    )

    messages = initial_understanding_messages(state)
    reference = json.loads(messages[1]["content"])["背景参考"]
    assert estimate_message_tokens(messages[1]) <= 4000
    assert reference["画像、记忆与其他参考"][0]["内容"] == "旧偏好水边"
    assert reference["本次会话较早对话摘要（模型整理）"] == {
        "摘要": "", "摘要中的约束": ["曾提出坐船"],
    }
    assert "未列出" in reference["参考资料说明"]
    assert huge not in messages[1]["content"]


def test_question_and_answer_are_kept_with_roles_and_later_amendment():
    qa = [
        {"question_id": "season", "question": "想在哪个季节出发？", "answer": "秋天"},
        {"question_id": "pace", "question": "每天希望安排多少活动？", "answer": "一两处即可"},
    ]
    amendment = SimpleNamespace(command_id="next", content="更正，改为春天出发")
    payload = understanding_context_payload(_state(
        user_query="想去看海",
        controlled_trip_identity={"party": {"total": 3}},
        current_requirements="上轮整理：秋天看海，一天一两处活动",
        understanding_qa=qa,
        plan_gate_amendment=amendment,
    ))

    assert payload["已有旅行理解（模型整理）"] == "上轮整理：秋天看海，一天一两处活动"
    assert "表单" not in next(key for key in payload if "基础信息" in key)
    assert payload["此前问答"] == [
        {"问题标识": "season", "助手提问": "想在哪个季节出发？", "旅行者回答": "秋天"},
        {"问题标识": "pace", "助手提问": "每天希望安排多少活动？", "旅行者回答": "一两处即可"},
    ]
    assert payload["最新补充"] == ["更正，改为春天出发"]
    assert list(payload).index("用户旅行想法") < list(payload).index("此前问答")
    assert list(payload).index("此前问答") < list(payload).index("最新补充")


def test_recent_dialogue_retains_both_roles_and_latest_input_only_once():
    state = _state(
        user_query="更正，回程也坐船",
        messages=[
            _message("human", "计划去海边"),
            _message("ai", "希望怎么安排行程？"),
            _message("human", "行程慢一些"),
            _message("ai", "回程也要坐船吗？"),
            _message("human", "更正，回程也坐船"),
        ],
    )

    current = json.loads(initial_understanding_messages(state)[-1]["content"])
    assert current["近期对话（按角色区分，判断是否与本次旅行有关）"] == [
        {"role": "user", "content": "计划去海边"},
        {"role": "assistant", "content": "希望怎么安排行程？"},
        {"role": "user", "content": "行程慢一些"},
        {"role": "assistant", "content": "回程也要坐船吗？"},
    ]
    assert current["用户旅行想法"] == "更正，回程也坐船"


def test_latest_input_preserves_labeled_exchanges_in_one_user_message():
    exchange = (
        "助手提问：偏好什么交通？\n旅行者回答：坐船\n\n"
        "助手提问：希望什么节奏？\n旅行者回答：慢一些"
    )
    state = _state(
        user_query=exchange,
        messages=[_message("ai", "准备好了"), _message("human", exchange)],
    )

    messages = initial_understanding_messages(state)
    current = json.loads(messages[-1]["content"])
    assert current["用户旅行想法"] == exchange
    assert current["近期对话（按角色区分，判断是否与本次旅行有关）"] == [
        {"role": "assistant", "content": "准备好了"},
    ]
    assert messages[-1]["content"].count("偏好什么交通？") == 1
    assert messages[-1]["content"].count("旅行者回答：") == 2


def test_recent_user_message_keeps_its_labeled_exchange_when_older_assistant_is_too_long():
    old_message = "先前的助手回复" + "很长的补充" * 10000
    exchange = "助手提问：偏好什么交通？\n旅行者回答：坐船"
    state = _state(
        user_query="更正，回程坐火车",
        messages=[
            _message("ai", old_message),
            _message("human", exchange),
            _message("human", "更正，回程坐火车"),
        ],
    )

    current = json.loads(initial_understanding_messages(state)[-1]["content"])
    assert current["近期对话（按角色区分，判断是否与本次旅行有关）"] == [
        {"role": "user", "content": exchange},
    ]
    assert current["用户旅行想法"] == "更正，回程坐火车"
    assert "较早的对话未列出" in current["近期对话说明"]


def test_latest_labeled_exchange_does_not_pull_in_unrelated_oversized_assistant_message():
    old_message = "先前的助手回复" + "很长的补充" * 10000
    exchange = "助手提问：偏好什么交通？\n旅行者回答：坐船"
    state = _state(
        user_query=exchange,
        messages=[_message("ai", old_message), _message("human", exchange)],
    )

    current = json.loads(initial_understanding_messages(state)[-1]["content"])
    assert current["用户旅行想法"] == exchange
    assert "近期对话（按角色区分，判断是否与本次旅行有关）" not in current
    assert "较早的对话未列出" in current["近期对话说明"]


def test_recent_unlabeled_user_message_is_preserved_without_rewriting():
    old_exchange = "偏好什么交通？：坐船"
    state = _state(
        user_query="回程坐火车",
        messages=[_message("human", old_exchange), _message("human", "回程坐火车")],
    )

    current = json.loads(initial_understanding_messages(state)[-1]["content"])
    assert current["近期对话（按角色区分，判断是否与本次旅行有关）"] == [
        {"role": "user", "content": old_exchange},
    ]


def test_bounded_conversation_keeps_recent_complete_question_and_answer():
    old_question = "先前的问题" + "很长的补充" * 10000
    state = _state(messages=[
        _message("ai", old_question),
        _message("human", "是的"),
        _message("ai", "偏好什么交通？"),
        _message("human", "坐船"),
        _message("ai", "还有其他要求吗？"),
    ])

    payload = understanding_context_payload(state)
    recent = payload["近期对话（按角色区分，判断是否与本次旅行有关）"]
    assert recent == [
        {"role": "assistant", "content": "偏好什么交通？"},
        {"role": "user", "content": "坐船"},
        {"role": "assistant", "content": "还有其他要求吗？"},
    ]
    assert "较早的对话未列出" in payload["近期对话说明"]


def test_followup_context_does_not_repeat_the_new_input():
    refinement = "旅行者：先看看滨海\n助手：已为你规划两天\n旅行者：改成三天"
    payload = understanding_context_payload(_state(
        user_query="改成三天", refinement_context=refinement,
    ))

    assert payload["本轮追问上下文"] == "旅行者：先看看滨海\n助手：已为你规划两天"
    assert payload["用户旅行想法"] == "改成三天"


def test_replanning_does_not_attach_the_raw_conversation_again():
    human = _message("human", "先看看滨海")
    ai = _message("ai", "已为你规划两天")
    replanning = initial_understanding_messages(_state(
        user_query="改成三天",
        refinement_context="旅行者：先看看滨海\n助手：已为你规划两天",
        messages=[human, ai],
    ))
    fresh = initial_understanding_messages(_state(messages=[human, ai]))

    assert not any("近期对话" in message["content"] for message in replanning[1:])
    assert any("近期对话" in message["content"] for message in fresh[1:])
    assert json.loads(replanning[-1]["content"])["用户旅行想法"] == "改成三天"
