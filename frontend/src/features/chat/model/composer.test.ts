import { describe, expect, it } from 'vitest';
import { composerState } from './composer';

const base = { isStreaming: false, hasInput: false, hasTripRun: false, runCancellable: false };

describe('composerState', () => {
  it('sends when idle', () => {
    expect(composerState({ ...base, hasInput: true })).toEqual({ action: 'send', showStop: false, sendDisabled: false });
    expect(composerState(base)).toEqual({ action: 'send', showStop: false, sendDisabled: true });
  });

  it('stops a streaming lightweight answer without a Trip Run', () => {
    expect(composerState({ ...base, isStreaming: true, hasInput: true })).toEqual({ action: 'stop', showStop: true, sendDisabled: false });
  });

  it('stops a cancellable Trip Run while input is empty', () => {
    expect(composerState({ ...base, isStreaming: true, hasTripRun: true, runCancellable: true })).toEqual({ action: 'stop', showStop: true, sendDisabled: false });
  });

  it('sends a supplement while a cancellable Trip Run is streaming with input', () => {
    expect(composerState({ ...base, isStreaming: true, hasInput: true, hasTripRun: true, runCancellable: true })).toEqual({ action: 'supplement', showStop: false, sendDisabled: false });
  });
});
