import { describe, expect, it } from 'vitest';
import { followupComposerState, type FollowupComposerInput } from './followupComposer';

const base: FollowupComposerInput = {
  runStatus: 'completed',
  isStreaming: false,
  hasDelivery: true,
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
    expect(followupComposerState({ ...base, runStatus: 'interrupted', canResume: true }).visible).toBe(true);
  });

  it('only accepts queued messages during a run after delivery', () => {
    expect(followupComposerState({ ...base, runStatus: 'running', isStreaming: true }).visible).toBe(true);
    expect(followupComposerState({ ...base, runStatus: 'running', hasDelivery: false, isStreaming: true }).visible).toBe(false);
    expect(followupComposerState({ ...base, runStatus: 'running', hasDelivery: false, isStreaming: false }).visible).toBe(false);
    expect(followupComposerState({ ...base, runStatus: 'completed', hasDelivery: false, isStreaming: true }).visible).toBe(false);
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

  it('only explains the queue when a delivered trip is still running', () => {
    for (const runStatus of ['completed', 'failed', 'cancelled', 'interrupted'] as const) {
      expect(followupComposerState({ ...base, runStatus }).hint).toBe('');
    }
    expect(followupComposerState({ ...base, runStatus: 'running', isStreaming: true }).hint).toContain('当前回复结束后');
  });
});
