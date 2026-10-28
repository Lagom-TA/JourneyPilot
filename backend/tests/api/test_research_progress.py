"""公开的调研活动不得暴露 worker 的结构化数据包。"""
import json

import pytest

from travel_agent.conversation.chat.presentation import ChatPresentation
from travel_agent.conversation.chat.progress_events import _handle_agent_activity, _handle_state_update
from travel_agent.conversation.chat.tool_events import _handle_tool_done, _handle_tool_start
from travel_agent.api.sse_projection import project_sse_payload
from travel_agent.tools.display import public_text, result_preview

PACKET = '正在分派并行调研任务{"contract_version":"journeypilot.research_packet.v5","candidates":[{"name":"伪满皇宫博物院"}]}'


def context():
    return ChatPresentation(message_id='m', session_id='s', mode='deep', use_deep_research=True)


@pytest.mark.parametrize('text', [PACKET, '```json\n{"candidates": []}', '{', '[{"name":"秘密"}]'])
def test_packets_are_never_public_text(text):
    assert public_text(text) == ''
    event = project_sse_payload({'type': 'thinking', 'content': text})
    assert event['content'] == ''


async def test_raw_stream_dropped_even_at_single_character_boundaries():
    ctx = context()
    for chunk in PACKET:
        assert project_sse_payload({'type': 'agent_thinking', 'content': chunk}) is None
    assert ctx.thinking_steps == []


def test_preview_is_bounded_idempotent_and_uses_only_public_facts():
    raw = {'sanitized_result': {'content': [{'type': 'text', 'text': json.dumps({'results': [
        {'name': '伪满皇宫博物院', 'address': '长春市宽城区光复北路', 'provider_audit_id': 'private', 'raw_body': 'private', 'url': 'https://example.org/museum'},
        {'name': '长影旧址', 'url': 'javascript:alert(1)'},
    ]}, ensure_ascii=False)}]}}
    rows = result_preview(raw)
    assert rows == [{'title': '伪满皇宫博物院', 'detail': '长春市宽城区光复北路', 'url': 'https://example.org/museum'}, {'title': '长影旧址'}]
    assert result_preview(rows) == rows
    assert len(result_preview([{'name': str(i)} for i in range(100)])) == 6
    assert result_preview({'unknown': {'secret': 'private'}}) == []


async def test_parallel_workers_and_tool_detail_survive_public_projection():
    ctx = context()
    for worker in ['destination_researcher', 'transport_researcher']:
        events = [e async for e in _handle_agent_activity(('agent_activity', worker, None), ctx)]
        assert project_sse_payload(events[0])['progress_status'] == 'running'
        await_events = _handle_tool_start(('tool_start', worker, {'name': 'global_place_search', 'tool_call_id': worker}), ctx)
        _ = [e async for e in await_events]
    info = {'name': 'global_place_search', 'tool_call_id': 'destination_researcher', 'summary': '找到 1 个结果', 'status': 'success', 'result_preview': [{'title': '伪满皇宫博物院', 'detail': '光复北路'}]}
    events = [e async for e in _handle_tool_done(('tool_done', 'destination_researcher', info), ctx)]
    event = project_sse_payload(events[0])
    assert event['result_preview'][0]['detail'] == '光复北路'
    tools = [s for s in ctx.thinking_steps if s.get('is_tool_call')]
    assert tools[0]['tool_status'] == 'completed'
    assert tools[1]['tool_status'] == 'running'
    events = [e async for e in _handle_state_update(('state', 'destination_researcher', {'messages': [PACKET]}), ctx)]
    progress = next(e for e in events if e['type'] == 'agent_progress')
    assert progress['progress_status'] == 'completed'
    assert 'contract_version' not in json.dumps(ctx.thinking_steps)


async def test_worker_packet_still_reaches_internal_consumer():
    from travel_agent.runtime.events import EventBuffer
    from travel_agent.tools.react import streaming_react_loop

    class LLM:
        async def astream_with_tools(self, messages, schemas):
            yield {'type': 'reasoning_delta', 'content': 'private internal reasoning'}
            for char in PACKET:
                yield {'type': 'text_delta', 'content': char}
            yield {'type': 'finish', 'content': PACKET, 'tool_calls': []}

    queue = EventBuffer()
    result = await streaming_react_loop(LLM(), [], [], queue, 'destination_researcher', max_iterations=1)
    assert result.content == PACKET
    assert await queue.get(timeout=0.1) == ('agent_activity', 'destination_researcher', None)
    with pytest.raises(TimeoutError):
        await queue.get(timeout=0.01)


async def test_lifecycle_starts_specialists_before_their_first_model_or_tool_call():
    from travel_agent.conversation.chat.progress_events import _handle_node_activity
    ctx = context()
    event = [e async for e in _handle_node_activity({'node': 'itinerary_planner', 'status': 'started', 'error_type': 'private'}, ctx)]
    assert event[0]['agent_name'] == '行程规划'
    assert event[0]['progress_status'] == 'running'
    assert 'error_type' not in event[0]
    # ReAct 回退路径不得重复创建卡片或启动里程碑。
    assert [e async for e in _handle_agent_activity(('agent_activity', 'itinerary_planner', None), ctx)] == []


def test_history_sanitizes_old_packets_and_preserves_new_details():
    from travel_agent.memory.chat_session import _project_events_to_messages
    rows = [
        {'event_type': 'message.assistant', 'payload': {'message_id': 'm', 'content': '行程已生成'}},
        {'event_type': 'thinking.step', 'payload': {'message_id': 'm', 'content': PACKET}},
        {'event_type': 'thinking.step', 'payload': {'message_id': 'm', 'is_tool_call': True, 'tool_result': '找到 1 个结果', 'result_preview': [{'title': '博物馆', 'detail': '光复北路'}], 'progress_status': 'completed'}},
    ]
    message = _project_events_to_messages(rows)[0]
    assert message['thinking_steps'][0]['content'] == ''
    assert message['thinking_steps'][1]['result_preview'] == [{'title': '博物馆', 'detail': '光复北路'}]


def test_worker_summary_uses_candidates_and_honors_failed_status():
    from travel_agent.planning.research.progress import worker_result
    update = {'research_packets': {'internal-key': {'worker_kind': 'destination_researcher', 'candidates': [{'name': '伪满皇宫博物院', 'address': '光复北路', 'candidate_id': 'internal-id'}]}}, 'messages': [PACKET]}
    assert worker_result('destination_researcher', update) == ('completed', '已整理 1 个地点候选', [{'title': '伪满皇宫博物院', 'detail': '光复北路'}])
    update['agent_status'] = {'destination_researcher': 'failed'}
    status, content, rows = worker_result('destination_researcher', update)
    assert status == 'failed' and rows == []
    assert 'internal' not in content and 'contract_version' not in content
