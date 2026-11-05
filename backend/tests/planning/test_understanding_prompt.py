"""理解提示词的输入编排：稳定内容在前，追问往来只出现一次。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from travel_agent.planning.requirements.understanding.prompts import (
    initial_understanding_messages,
    understanding_context_payload,
)


def _state(**overrides):
    values = dict(
        constraint_pack={},
        preset_context="",
        session_anchor=None,
        controlled_trip_identity=None,
        current_requirements={"destination": "杭州"},
        refinement_context="",
        user_query="改成三天",
        understanding_qa=[],
        pending_intent_amendments=[],
        applied_intent_amendment_ids=set(),
        plan_gate_amendment=None,
        current_time="2026-11-05",
        messages=[],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_latest_expression_is_last_and_stable_context_comes_first() -> None:
    payload = understanding_context_payload(
        _state(preset_context="亲子出行", understanding_qa=[{"q": "几人", "a": "三人"}])
    )

    keys = list(payload)

    assert keys[-1] == "用户旅行想法"
    assert keys.index("其他背景") < keys.index("已有旅行理解") < keys.index("此前问答")


def test_followup_context_does_not_repeat_the_new_input() -> None:
    refinement = "旅行者：先看看杭州\n助手：已为你规划两天\n旅行者：改成三天"

    payload = understanding_context_payload(_state(refinement_context=refinement))

    assert payload["本轮追问上下文"] == "旅行者：先看看杭州\n助手：已为你规划两天"
    assert payload["用户旅行想法"] == "改成三天"


def test_replanning_does_not_attach_the_raw_conversation_again() -> None:
    human = SimpleNamespace(type="human", content="先看看杭州")
    ai = SimpleNamespace(type="ai", content="已为你规划两天")

    replanning = initial_understanding_messages(
        _state(refinement_context="旅行者：先看看杭州\n助手：已为你规划两天", messages=[human, ai])
    )
    fresh = initial_understanding_messages(_state(messages=[human, ai]))

    assert not any("近期对话" in message["content"] for message in replanning[1:])
    assert any("近期对话" in message["content"] for message in fresh[1:])
    assert json.loads(replanning[-1]["content"])["用户旅行想法"] == "改成三天"
