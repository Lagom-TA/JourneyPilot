import { describe, expect, it } from 'vitest';
import { appReducer, type AppState } from '../context/AppContext';
import type { UsageUpdateEvent, RunCostSummary } from '../types/api';
import { buildCostLedgerView } from './costLedger';

describe('live token accounting', () => {
  const event: UsageUpdateEvent = {
    type: 'usage_update', run_id: 'run-test', call_id: 'call-test', node: null, agent: null,
    input_tokens: 100, output_tokens: 20, total_tokens: 120, cost_usd: 0.1,
    estimated: false, usage_complete: true,
  };

  it('counts an SSE replay once and keeps separate attempts', () => {
    const first = appReducer({ runCostLive: null } as AppState, { type: 'USAGE_UPDATE', payload: event });
    expect(appReducer(first, { type: 'USAGE_UPDATE', payload: event })).toBe(first);
    const second = appReducer(first, { type: 'USAGE_UPDATE', payload: { ...event, call_id: 'retry-test' } });
    expect(second.runCostLive?.callCount).toBe(2);
    expect(second.runCostLive?.totalTokens).toBe(240);
  });

  it('labels an incomplete call without implying zero cost', () => {
    const state = appReducer({ runCostLive: null } as AppState, {
      type: 'USAGE_UPDATE', payload: { ...event, input_tokens: null, output_tokens: null,
        total_tokens: null, cost_usd: null, usage_complete: false },
    });
    const view = buildCostLedgerView(null, state.runCostLive);
    expect(view?.tiles.find(tile => tile.field === 'total_cost_usd')?.value).toBeNull();
    expect(view?.tiles.find(tile => tile.field === 'total_tokens')?.value).toBeNull();
    expect(view?.notices.some(notice => notice.text.includes('缺少完整计量'))).toBe(true);
  });

  it('shows an incomplete bill even when no captured row has committed', () => {
    const summary = {
      run_id: 'run-test', call_count: 0, record_failed: 1, pending_call_count: 1,
      capture_complete: false, token_usage_complete: false, cost_complete: false,
      total_tokens: null, total_cost_usd: null, currency: 'USD',
      estimated_call_count: 0, estimated_ratio: 0, error_call_count: 0,
      cost_coverage_ratio: 0, by_node: [],
    } as unknown as RunCostSummary;
    const view = buildCostLedgerView(summary, null);
    expect(view?.tiles.find(tile => tile.field === 'total_tokens')?.value).toBeNull();
    expect(view?.notices.some(notice => notice.text.includes('账单尚不完整'))).toBe(true);
    const failed = buildCostLedgerView({ ...summary, spool_write_failed: 1 }, null);
    expect(failed?.notices.some(notice => notice.text.includes('持久记录出现故障'))).toBe(true);
  });
});
