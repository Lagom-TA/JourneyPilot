"""公开工作说明的整句校验、SSE 投影与历史保留。"""

from __future__ import annotations

import pytest

from travel_agent.api.sse_projection import project_sse_payload
from travel_agent.conversation.chat.presentation import ChatPresentation
from travel_agent.conversation.chat.progress_events import _handle_work_explanation
from travel_agent.memory.chat_session import _project_events_to_messages
from travel_agent.public_note import PublicNoteStream, sanitize_public_note


def context():
    return ChatPresentation(message_id='m', session_id='s', mode='deep', use_deep_research=True)


def test_note_is_checked_as_complete_sentences():
    stream = PublicNoteStream()
    assert stream.feed("我先确认一下。") == [(0, "我先确认一下。")]
    assert stream.feed("联系 test@example.com 或 sk-live-SECRET123。") == []
    assert stream.blocked is True
    assert stream.flush() == []


def test_projection_keeps_safe_note_and_drops_unsafe():
    event = {"type": "work_explanation", "agent_name": "目的地调研", "node": "destination_researcher", "step_id": "work-note:x", "round": 1, "call_id": "llm_1", "seq": 0, "content": "我先确认一下地点。", "source": "model_public"}
    projected = project_sse_payload(event)
    assert projected["content"] == "我先确认一下地点。"
    assert projected["node"] == "destination_researcher"
    assert project_sse_payload({**event, "content": "联系 test@example.com"}) is None
    assert project_sse_payload({**event, "content": "{\"a\":1}"}) is None
    assert project_sse_payload({"type": "agent_thinking", "content": "私密推理"}) is None


@pytest.mark.asyncio
async def test_handler_persists_kind_and_history_keeps_note():
    ctx = context()
    events = [event async for event in _handle_work_explanation(("work_explanation", "destination_researcher", {"step_id": "work-note:r", "content": "我先确认一下地点。", "round": 1, "call_id": "llm_1", "seq": 0}), ctx)]
    assert events[0]["type"] == "work_explanation"
    assert ctx.thinking_steps[0]["kind"] == "work_explanation"
    rows = [
        {"event_type": "message.assistant", "payload": {"message_id": "m", "content": "完成"}},
        {"event_type": "thinking.step", "payload": {"message_id": "m", "step_id": "work-note:r", "kind": "work_explanation", "content": "我先确认一下地点。", "round": 1, "call_id": "llm_1", "seq": 0}},
    ]
    step = _project_events_to_messages(rows)[0]["thinking_steps"][0]
    assert step["kind"] == "work_explanation"
    assert step["content"] == "我先确认一下地点。"
    assert step["round"] == 1
    assert sanitize_public_note("我先确认一下地点。") == "我先确认一下地点。"


def test_secret_split_across_deltas_is_never_emitted():
    stream = PublicNoteStream()
    assert stream.feed("联系 sk-live-\n") == []
    assert stream.feed("SECRET123。") == []
    assert stream.blocked is True
