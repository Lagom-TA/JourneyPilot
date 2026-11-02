import { describe, expect, it } from 'vitest';
import { followupComposerState, type FollowupComposerInput } from './followupComposer';

const base: FollowupComposerInput = {
  runStatus: 'completed',
  isStreaming: false,
  readOnly: false,
  gatePending: false,
  pendingUnderstanding: false,
  pendingRouteConfirmation: false,
};

describe('followupComposerState', () => {
  it('offers a composer in every writable terminal state', () => {
    for (const runStatus of ['completed', 'failed', 'cancelled', 'interrupted'] as const) {
      expect(followupComposerState({ ...base, runStatus }).visible, runStatus).toBe(true);
    }
    expect(followupComposerState({ ...base, runStatus: 'interrupted', canResume: true }).hint).toContain('继续');
  });

  it('allows supplements during a running trip', () => {
    expect(followupComposerState({ ...base, runStatus: 'running', isStreaming: true }).visible).toBe(true);
    expect(followupComposerState({ ...base, runStatus: 'running', isStreaming: false }).visible).toBe(true);
    expect(followupComposerState({ ...base, runStatus: 'awaiting_input' }).visible).toBe(false);
  });

  it('does not stack a second input on a pending gate, intake or route confirmation', () => {
    expect(followupComposerState({ ...base, gatePending: true }).visible).toBe(false);
    expect(followupComposerState({ ...base, pendingUnderstanding: true }).visible).toBe(false);
    expect(followupComposerState({ ...base, pendingRouteConfirmation: true }).visible).toBe(false);
  });

  it('never writes into a read-only history run', () => {
    expect(followupComposerState({ ...base, readOnly: true }).visible).toBe(false);
  });

  it('explains each terminal state without promising outside the current workspace', () => {
    expect(followupComposerState({ ...base, runStatus: 'completed' }).hint).toContain('规划已生成');
    expect(followupComposerState({ ...base, runStatus: 'failed' }).hint).toContain('没有完成');
    expect(followupComposerState({ ...base, runStatus: 'cancelled' }).hint).toContain('已取消');
    expect(followupComposerState({ ...base, runStatus: 'interrupted', canResume: false }).hint).toContain('返回新旅行');
    expect(followupComposerState({ ...base, runStatus: 'interrupted', canResume: true }).hint).toContain('从最近的位置继续');
  });
});
