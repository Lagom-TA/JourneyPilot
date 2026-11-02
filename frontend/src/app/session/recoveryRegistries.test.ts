import { describe, expect, it } from 'vitest';
import { pruneRecoveryRegistries } from './recoveryRegistries';

function registries(runIds: string[]) {
  const cursorByRun = new Map(runIds.map((id, index) => [id, index]));
  return { cursorByRun, readyRuns: new Set(runIds.slice(0, 2)), finalizedRuns: new Set(runIds.slice(2)) };
}

describe('pruneRecoveryRegistries', () => {
  it('keeps only a bounded recent history', () => {
    const state = registries(['a', 'b', 'c', 'd', 'e']);
    pruneRecoveryRegistries(state, 'e', 3);
    expect([...state.cursorByRun.keys()]).toEqual(['c', 'd', 'e']);
    expect([...state.readyRuns]).toEqual([]);
    expect([...state.finalizedRuns]).toEqual(['c', 'd', 'e']);
  });

  it('never prunes the current run', () => {
    const state = registries(['a']);
    pruneRecoveryRegistries(state, 'a', 1);
    expect(state.cursorByRun.has('a')).toBe(true);
  });

  it('handles empty registries', () => {
    const state = registries([]);
    pruneRecoveryRegistries(state, null, 3);
    expect(state.cursorByRun.size).toBe(0);
  });
});
