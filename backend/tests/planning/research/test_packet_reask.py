"""首次解析失败时按同一批证据重新请求一次，最多一次，且不吞掉重新请求自身的错误。"""

import json

import pytest

from tests.fixtures.research_packets import make_packet
from travel_agent.planning.research.output.finalization import parse_research_packet_or_reask
from travel_agent.planning.research.output.policy import ResearchPacketOutputError
from travel_agent.runtime.cancellation import RunCancelled

_KWARGS = {"expected_worker": "destination_researcher", "expected_run_id": "run_test"}


def _valid_output():
    payload = make_packet().model_dump(mode="json")
    payload.update(source_records=[], fact_assertions=[], field_provenance=[])
    candidate = payload["candidates"][0]
    candidate.pop("candidate_kind")
    candidate.update(fact_assertion_ids=[], source_record_ids=[], field_paths=[])
    return json.dumps(payload)


class _Model:
    """记录每次重新请求收到的消息；回复按顺序给出，异常实例则抛出。"""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    async def ainvoke(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


_MESSAGES = [
    {"role": "system", "content": "研究员"},
    {"role": "tool", "content": "地点观察", "tool_call_id": "call_1"},
]


async def _parse(raw, model):
    return await parse_research_packet_or_reask(raw, llm=model, messages=_MESSAGES, **_KWARGS)


async def test_a_valid_first_output_never_asks_again():
    model = _Model()

    packet = await _parse(_valid_output(), model)

    assert packet.candidates[0].candidate_id == "visit_a"
    assert model.requests == []


async def test_an_unparseable_first_output_is_replaced_by_one_new_answer():
    model = _Model(_valid_output())

    packet = await _parse("这不是 JSON", model)

    assert packet.candidates[0].candidate_id == "visit_a"
    (messages, kwargs), = model.requests
    assert kwargs == {"response_format": {"type": "json_object"}}
    # 工具观察以纯文本数据带入，最后一条是带失败原因的更正请求。
    assert messages[1]["role"] == "user" and "地点观察" in messages[1]["content"]
    assert "无法解析" in messages[-1]["content"] and messages[-1]["role"] == "user"


async def test_a_second_unparseable_output_fails_without_a_third_attempt():
    model = _Model("仍然不是 JSON", "不应被取用")

    with pytest.raises(ResearchPacketOutputError):
        await _parse("这不是 JSON", model)

    assert len(model.requests) == 1
    assert model.replies == ["不应被取用"]


async def test_an_error_while_asking_again_is_not_wrapped_or_retried():
    model = _Model(RuntimeError("研究窗口已关闭"))

    with pytest.raises(RuntimeError, match="研究窗口已关闭"):
        await _parse("这不是 JSON", model)

    assert len(model.requests) == 1


async def test_the_reason_passed_to_the_model_is_bounded():
    model = _Model(_valid_output())

    await _parse("x" * 50_000, model)

    (messages, _), = model.requests
    assert len(messages[-1]["content"]) < 600


async def test_a_failing_reask_degrades_to_an_output_error_only_when_asked_to():
    for flag, expected in ((True, ResearchPacketOutputError), (False, RuntimeError)):
        model = _Model(RuntimeError("研究窗口已关闭"))
        with pytest.raises(expected):
            await parse_research_packet_or_reask(
                "这不是 JSON", llm=model, messages=_MESSAGES, degrade_on_reask_error=flag, **_KWARGS
            )


async def test_cancellation_while_asking_again_is_never_swallowed():
    model = _Model(RunCancelled("run", "用户取消"))

    with pytest.raises(RunCancelled):
        await parse_research_packet_or_reask(
            "这不是 JSON", llm=model, messages=_MESSAGES, degrade_on_reask_error=True, **_KWARGS
        )

