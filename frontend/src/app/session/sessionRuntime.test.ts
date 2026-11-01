import { afterEach, describe, expect, it, vi } from 'vitest';
import { initialState } from '../state/initialState';
import { appReducer } from '../state/appReducer';
import type { AppAction, AppState } from '../state/state';
import { createSessionRuntimeSnapshot, type ActiveStreamHandle, type SessionRuntimeSnapshot } from './runtimeSnapshot';
import { createStreamOwnership } from './streamOwnership';
import { createStreamEvents } from './streamEvents';
import { createStreamFrameBatch } from '../../features/chat/model/streamFrameBatch';
import { createDeliveryProtocol } from '../../features/travel/model/deliveryProtocol';
import type { Message } from '../../features/chat/types/messages';
import type { UsageUpdateEvent } from '../../features/chat/types/cost';
import { DELIVERY_BUNDLE_CONTRACT_VERSION, type PublicDeliveryBundle } from '../../features/travel/types/delivery';
import { TRIP_WORKSPACE_CONTRACT_VERSION } from '../../features/travel/types/workspace';

const message = (id: string, content = id): Message => ({ id, role: 'assistant', content, displayContent: content, timestamp: new Date('2026-10-25T08:00:00Z') });
const stateFor = (id: string): AppState => ({ ...initialState, currentSessionId: id, currentMessages: [message(id)], currentTripRunId: `run-${id}`, currentTripRunStatus: 'running', isStreaming: true });
const usage: UsageUpdateEvent = { type: 'usage_update', run_id: 'run-A', call_id: 'call-1', node: null, agent: null, input_tokens: 10, output_tokens: 5, total_tokens: 15, cost_usd: 0.03, estimated: false };
const deliveryBundle = (revision = 1): PublicDeliveryBundle => {
  const cost = { known_subtotal_cny: null, estimated_total_cny: null, priced_component_count: 0, budget_relevant_component_count: 0, coverage: 'none' as const, budget_cap_cny: null, budget_status: 'unknown' as const, llm_estimated_total_cny: null };
  return {
    manifest: { contract_version: DELIVERY_BUNDLE_CONTRACT_VERSION, run_id: 'run-A', generation_id: 'generation-A', bundle_id: `bundle-${revision}`, workspace_revision: revision, fact_data_revision: revision, weather_data_revision: revision, created_at: '2026-10-25T08:00:00Z' },
    workspace: { contract_version: TRIP_WORKSPACE_CONTRACT_VERSION, run_id: 'run-A', generation_id: 'generation-A', workspace_revision: revision,
      itinerary: { itinerary_id: 'itinerary-A', title: '离线旅行交付', destination_ids: [], duration_days: 1, day_plans: [], visit_stops: [], dining_stops: [], lodging_stays: [], transport_legs: [], custom_blocks: [], cost_summary: cost, highlights: [], important_notes: [], unresolved: [] },
      selection_slots: [], weather_proposal_decisions: [], weather_adjustments: [] },
    report_projection: { source_workspace_revision: revision, source_fact_data_revision: revision, source_weather_data_revision: revision, status: 'ready',
      document: { title: '离线旅行报告', overview: '仅使用本地测试数据', destinations: [], duration_days: 1, cost_summary: cost, cost_coverage_statement: null, days: [], selections: [], weather: [], highlights: [], important_notes: [], unresolved: [] }, citations: [], generated_at: '2026-10-25T08:00:00Z' },
    map_projection: { source_workspace_revision: revision, content: { places: [], routes: [] } },
    source_index: { source_fact_data_revision: revision, content: { citations: [] } }, provider_environment: { sandbox_note: null },
  };
};
afterEach(() => vi.unstubAllGlobals());

describe('session runtime behavior', () => {
  it('restores all session-owned fields together without replacing global preferences', () => {
    const first = appReducer(stateFor('A'), { type: 'CONFIRM_DELIVERY_BUNDLE', payload: deliveryBundle() });
    const snapshot = createSessionRuntimeSnapshot(appReducer(first, { type: 'USAGE_UPDATE', payload: usage }));
    const visible = { ...stateFor('B'), activeView: 'presets' as const, activePresetId: 'preset-B', sidebarCollapsed: false, conversationEpoch: 20, deliverableView: 'full_report' as const };
    const restored = appReducer(visible, { type: 'RESTORE_SESSION_RUNTIME', payload: snapshot });
    expect(restored).toMatchObject({ currentSessionId: 'A', currentTripRunId: 'run-A', deliveryBundle: first.deliveryBundle, currentMessages: first.currentMessages, activeView: 'presets', activePresetId: 'preset-B', sidebarCollapsed: false, conversationEpoch: 21, deliverableView: 'interactive_itinerary' });
    expect(restored.runCostLive?.totalTokens).toBe(15);
    for (const key of ['deliverableView', 'activeView', 'activePresetId', 'sidebarCollapsed', 'sessions']) expect(snapshot).not.toHaveProperty(key);
    expect(appReducer(restored, { type: 'SET_SESSION_ID', payload: 'server-id' }).conversationEpoch).toBe(21);
  });

  it('keeps hidden stream updates and delivery in its cached session using the root reducer', () => {
    const currentStateRef = { current: stateFor('B') };
    const activeStreamRef = { current: { token: 'stream-A', sessionId: 'A', runId: 'run-A', controller: null } as ActiveStreamHandle | null };
    const cache = { current: new Map<string, SessionRuntimeSnapshot>([['A', createSessionRuntimeSnapshot(stateFor('A'))]]) };
    const dispatch = vi.fn();
    const owner = createStreamOwnership('stream-A', 'A', 0, 'run-A', null, activeStreamRef, currentStateRef, cache, dispatch);
    owner.scopedDispatch({ type: 'UPDATE_LAST_MESSAGE', payload: { content: 'A 的后台回答', displayContent: 'A 的后台回答' } });
    owner.scopedDispatch({ type: 'USAGE_UPDATE', payload: usage });
    owner.scopedDispatch({ type: 'CONFIRM_DELIVERY_BUNDLE', payload: deliveryBundle() });
    expect(dispatch).not.toHaveBeenCalled();
    expect(currentStateRef.current.currentMessages[0].content).toBe('B');
    const cached = cache.current.get('A')!;
    expect(cached.currentMessages[0].content).toBe('A 的后台回答');
    expect(cached.runCostLive?.callCount).toBe(1);
    expect(cached.deliveryBundle?.manifest.bundle_id).toBe('bundle-1');
    expect(appReducer(currentStateRef.current, { type: 'RESTORE_SESSION_RUNTIME', payload: cached }).currentMessages[0].content).toBe('A 的后台回答');
  });

  it('understanding questions bind to the run, survive awaiting completion and clear on resume', () => {
    const currentStateRef: { current: AppState } = { current: { ...stateFor('A'), isStreaming: false, currentTripRunStatus: null } };
    const activeStreamRef = { current: { token: 'stream-A', sessionId: 'A', runId: null, controller: null } as ActiveStreamHandle | null };
    const cache = { current: new Map<string, SessionRuntimeSnapshot>() };
    const dispatches: AppAction[] = [];
    const dispatch = vi.fn((action: AppAction) => dispatches.push(action));
    const assistant = { ...message('assistant-understanding'), content: '', displayContent: '' };
    const owner = createStreamOwnership('stream-A', 'A', 0, null, null, activeStreamRef, currentStateRef, cache, dispatch);
    const frame = createStreamFrameBatch(owner.scopedDispatch, assistant as Message);
    const events = createStreamEvents(owner, assistant as Message, '想去青岛放松几天', null, '正在理解你的旅行想法', currentStateRef, () => {}, frame);
    events.handleEvent({ type: 'chat_start', message_id: 'assistant-understanding', session_id: 'A', run_id: 'run-A', route_decision: { route: 'trip_planning', confidence: 1, alternatives: [], signals: [], requires_trip_draft: true, requires_confirmation: false } });
    events.handleEvent({
      type: 'understanding_questions', run_id: 'run-A', gate: 'understanding', run_status: 'awaiting_input',
      payload: {
        gate: 'understanding', revision: 1, approval_token: 'token-1',
        questions: [{ id: 'pace', question: '节奏？', kind: 'single', options: [{ id: 'slow', label: '慢慢逛' }] }],
      },
    });
    events.handleEvent({ type: 'chat_complete', run_id: 'run-A', run_status: 'awaiting_input', ts_ms: 5 });
    let state = currentStateRef.current;
    for (const action of dispatches) state = appReducer(state, action);
    expect(state.understandingQuestions).toMatchObject({ runId: 'run-A', revision: 1, approvalToken: 'token-1' });
    expect(state.currentTripRunStatus).toBe('awaiting_input');
    // 回答提交后的新一轮事件清空问题卡并恢复流式状态。
    dispatches.length = 0;
    const resume = createStreamEvents(owner, assistant as Message, '已回答理解问题', 'run-A', '正在继续理解', currentStateRef, () => {}, frame, 'answer');
    resume.handleEvent({ type: 'thinking', message_id: 'assistant-understanding', run_id: 'run-A', agent_name: '理解旅行需求', step_name: '理解旅行需求', content: '继续理解', progress_status: 'running' });
    let resumed = currentStateRef.current;
    for (const action of dispatches) resumed = appReducer(resumed, action);
    expect(resumed.understandingQuestions).toBeNull();
  });

  it('does not publish stale-token frames into the visible session', () => {
    const current = stateFor('A');
    const dispatch = vi.fn();
    const owner = createStreamOwnership('old', 'A', 0, 'run-A', null, { current: { token: 'new', sessionId: 'A', runId: 'run-A', controller: null } }, { current }, { current: new Map() }, dispatch);
    owner.scopedDispatch({ type: 'ADD_MESSAGE', payload: message('late') });
    owner.updateActiveStreamHandle({ runId: 'stale' });
    expect(dispatch).not.toHaveBeenCalled();
    expect(owner.isCurrentStream()).toBe(false);
  });

  it('deduplicates cost replay with identity preservation and resets accounting on a new run', () => {
    const first = appReducer(stateFor('A'), { type: 'USAGE_UPDATE', payload: usage });
    expect(appReducer(first, { type: 'USAGE_UPDATE', payload: usage })).toBe(first);
    const next = appReducer(first, { type: 'USAGE_UPDATE', payload: { ...usage, run_id: 'run-B' } });
    expect(next.runCostLive).toMatchObject({ runId: 'run-B', callCount: 1, totalTokens: 15, totalCostUsd: 0.03 });
  });

  it('keeps the delivered trip visible while a new revision is running', () => {
    const delivered = appReducer(stateFor('A'), { type: 'CONFIRM_DELIVERY_BUNDLE', payload: deliveryBundle() });
    const pending = appReducer(delivered, { type: 'SET_CURRENT_TRIP_RUN', payload: { runId: 'revision-A', status: 'running', preserveDelivery: true } });
    expect(pending.currentTripRunId).toBe('revision-A');
    expect(pending.deliveryBundle).toBe(delivered.deliveryBundle);
    const next = deliveryBundle();
    next.manifest.run_id = 'revision-A';
    next.workspace.run_id = 'revision-A';
    expect(appReducer(pending, { type: 'CONFIRM_DELIVERY_BUNDLE', payload: next }).deliveryBundle).toBe(next);
  });

  it('rejects backward/mixed bundle revision vectors without changing object identity', () => {
    const current = appReducer(stateFor('A'), { type: 'CONFIRM_DELIVERY_BUNDLE', payload: deliveryBundle(3) });
    expect(appReducer(current, { type: 'CONFIRM_DELIVERY_BUNDLE', payload: deliveryBundle(2) })).toBe(current);
    const mixed = deliveryBundle(4); mixed.manifest.weather_data_revision = 2;
    expect(appReducer(current, { type: 'CONFIRM_DELIVERY_BUNDLE', payload: mixed })).toBe(current);
    expect(appReducer(current, { type: 'CONFIRM_DELIVERY_BUNDLE', payload: deliveryBundle(4) }).deliveryBundle?.manifest.bundle_id).toBe('bundle-4');
  });

  it('keeps thinking/message updates coupled, no-op identities intact, and clears a session atomically', () => {
    const empty = stateFor('A');
    expect(appReducer(empty, { type: 'FINISH_LAST_THINKING_STEP', payload: { endTime: new Date() } })).toBe(empty);
    const stepped = appReducer(empty, { type: 'ADD_THINKING_STEP', payload: { id: 'tool', agentName: '交通查询', content: '', stepName: '查询', timestamp: new Date(), isToolCall: true, toolCallId: 'call', toolStatus: 'running' } });
    const finished = appReducer(stepped, { type: 'UPDATE_LAST_TOOL_STEP', payload: { toolCallId: 'call', toolStatus: 'completed', serverDurationMs: 42 } });
    expect(finished.currentMessages[0].thinkingSteps).toBe(finished.thinkingSteps);
    expect(finished.thinkingSteps[0].serverDurationMs).toBe(42);
    expect(appReducer(finished, { type: 'UPDATE_LAST_TOOL_STEP', payload: { toolCallId: 'missing' } })).toBe(finished);
    const cleared = appReducer({ ...finished, isSynthesizing: true, canvasOpen: true, deliverableView: 'full_report' }, { type: 'CLEAR_CHAT' });
    expect(cleared).toMatchObject({ currentSessionId: null, currentTripRunId: null, currentMessages: [], thinkingSteps: [], runCostLive: null, isStreaming: false, isSynthesizing: false, canvasOpen: false, deliverableView: 'interactive_itinerary', conversationEpoch: 1, tripRunRefreshKey: 1 });
  });

  it('remaps placeholder IDs, clears entry labels, ignores unknown/raw thought events and finalizes the answer', () => {
    let state = { ...stateFor('A'), currentMessages: [message('temporary', '')] };
    const currentStateRef = { current: state };
    const dispatch = (action: AppAction) => { state = appReducer(state, action); currentStateRef.current = state; };
    const owner = createStreamOwnership('token', 'A', 0, null, null, { current: { token: 'token', sessionId: 'A', runId: null, controller: null } }, currentStateRef, { current: new Map() }, dispatch);
    const assistant = { ...message('temporary', ''), pendingStatusText: '准备中' };
    state.currentMessages[0] = assistant;
    const frame = createStreamFrameBatch(owner.scopedDispatch, assistant);
    const events = createStreamEvents(owner, assistant, '请求', 'run-A', '准备中', currentStateRef, vi.fn(), frame);
    events.handleEvent({ type: 'chat_start', session_id: 'A', message_id: 'persisted' });
    events.handleEvent({ type: 'agent_thinking', content: 'private delta' });
    events.handleEvent(JSON.parse('{"type":"future_unknown","content":"ignored"}'));
    expect(state.currentMessages[0].id).toBe('persisted');
    expect(state.thinkingSteps).toHaveLength(0);
    events.handleEvent({ type: 'thinking', agent_name: '任务分发', step_name: '准备回答' });
    expect(state.currentMessages[0].pendingStatusText).toBeUndefined();
    events.handleEvent({ type: 'chat_chunk', content: '初稿' });
    events.handleEvent({ type: 'chat_complete', final_content: '最终回答' });
    expect(state.currentMessages[0]).toMatchObject({ content: '最终回答', displayContent: '最终回答', streamCompleted: true });
  });

  it('batches usage before text and flushes queued frames before finalization', () => {
    let callback: FrameRequestCallback | undefined;
    const cancel = vi.fn();
    vi.stubGlobal('window', { requestAnimationFrame: vi.fn((cb: FrameRequestCallback) => { callback = cb; return 1; }), cancelAnimationFrame: cancel });
    const dispatch = vi.fn(), assistant = message('A', '正文');
    const frame = createStreamFrameBatch(dispatch, assistant);
    frame.queueAssistantUpdate(); frame.queueUsage(usage);
    expect(dispatch).not.toHaveBeenCalled();
    expect(callback).toBeDefined();
    frame.flushFrameNow();
    expect(cancel).toHaveBeenCalledWith(1);
    expect(dispatch.mock.calls.map(call => call[0].type)).toEqual(['USAGE_UPDATE', 'UPDATE_LAST_MESSAGE']);
  });

  it('accepts terminal-before-ready only with matching identity and forward sequence', () => {
    const bundle = deliveryBundle(), ready = vi.fn(), finalized = vi.fn();
    const protocol = createDeliveryProtocol({ sessionId: 'A', runId: 'run-A' }, ready, finalized);
    protocol.acceptDeliveryTerminal({ type: 'run_terminal', event_seq: 2, run_id: 'run-A', bundle_id: 'bundle-1', status: 'completed' });
    expect(finalized).not.toHaveBeenCalled();
    protocol.acceptDeliveryReady({ type: 'delivery_ready', event_seq: 1, run_id: 'run-A', bundle_id: 'bundle-1', bundle, manifest: bundle.manifest });
    expect(ready).toHaveBeenCalledOnce(); expect(finalized).toHaveBeenCalledOnce();
    expect(protocol.finalized).toBe(true);
    const invalid = createDeliveryProtocol({ sessionId: 'A', runId: 'run-A' }, vi.fn(), vi.fn());
    invalid.acceptDeliveryReady({ type: 'delivery_ready', event_seq: 3, run_id: 'run-A', bundle_id: 'bundle-1', bundle, manifest: bundle.manifest });
    expect(() => invalid.acceptDeliveryTerminal({ type: 'run_terminal', event_seq: 2, run_id: 'run-A', bundle_id: 'bundle-1', status: 'completed' })).toThrow();
    expect(invalid.error).toBeTruthy();
  });
});
