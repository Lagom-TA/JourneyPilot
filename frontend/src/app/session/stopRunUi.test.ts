import { describe, expect, it } from 'vitest';
import { stopRunUiState } from './stopRunUi';

describe('stopRunUiState', () => {
  it('keeps the stopped composer for an accepted Trip Run cancel', () => {
    expect(stopRunUiState({ hasRun: true, accepted: true, hadPendingDecision: true })).toEqual({ inputMode: 'stopped', markLastInterrupted: false });
  });

  it('returns to the normal composer for a lightweight answer stop', () => {
    expect(stopRunUiState({ hasRun: false, accepted: true, hadPendingDecision: false })).toEqual({ inputMode: 'normal', markLastInterrupted: true });
  });

  it('does not mark the answer interrupted when cancellation was not accepted', () => {
    expect(stopRunUiState({ hasRun: true, accepted: false, hadPendingDecision: false })).toEqual({ inputMode: 'normal', markLastInterrupted: false });
  });
});
