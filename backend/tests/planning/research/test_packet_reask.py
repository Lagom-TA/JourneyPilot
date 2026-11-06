"""首次解析失败时按同一批证据重新请求一次，最多一次，且不吞掉重新请求自身的错误。"""

import json

import pytest

from tests.fixtures.research_packets import make_packet
from travel_agent.planning.research.output.finalization import parse_research_packet_or_reask
from travel_agent.planning.research.output.policy import ResearchPacketOutputError

_KWARGS = {"expected_worker": "destination_researcher", "expected_run_id": "run_test"}


def _valid_output():
    payload = make_packet().model_dump(mode="json")
    payload.update(source_records=[], fact_assertions=[], field_provenance=[])
    candidate = payload["candidates"][0]
    candidate.pop("candidate_kind")
    candidate.update(fact_assertion_ids=[], source_record_ids=[], field_paths=[])
    return json.dumps(payload)


class _Reask:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.reasons = []

    async def __call__(self, reason):
        self.reasons.append(reason)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


async def test_a_valid_first_output_never_asks_again():
    reask = _Reask()

    packet = await parse_research_packet_or_reask(_valid_output(), reask=reask, **_KWARGS)

    assert packet.candidates[0].candidate_id == "visit_a"
    assert reask.reasons == []


async def test_an_unparseable_first_output_is_replaced_by_one_new_answer():
    reask = _Reask(_valid_output())

    packet = await parse_research_packet_or_reask("这不是 JSON", reask=reask, **_KWARGS)

    assert packet.candidates[0].candidate_id == "visit_a"
    assert len(reask.reasons) == 1 and reask.reasons[0]


async def test_a_second_unparseable_output_fails_without_a_third_attempt():
    reask = _Reask("仍然不是 JSON", "不应被取用")

    with pytest.raises(ResearchPacketOutputError):
        await parse_research_packet_or_reask("这不是 JSON", reask=reask, **_KWARGS)

    assert len(reask.reasons) == 1
    assert reask.replies == ["不应被取用"]


async def test_an_error_while_asking_again_is_not_wrapped_or_retried():
    reask = _Reask(RuntimeError("研究窗口已关闭"))

    with pytest.raises(RuntimeError, match="研究窗口已关闭"):
        await parse_research_packet_or_reask("这不是 JSON", reask=reask, **_KWARGS)

    assert len(reask.reasons) == 1


async def test_the_reason_passed_to_the_model_is_bounded():
    reask = _Reask(_valid_output())

    await parse_research_packet_or_reask("x" * 50_000, reask=reask, **_KWARGS)

    assert len(reask.reasons[0]) <= 300
