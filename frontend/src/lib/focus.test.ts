import { describe, expect, it } from 'vitest';
import { nextTrapIndex } from './focus';

describe('nextTrapIndex', () => {
  it('wraps forward and backward', () => {
    expect(nextTrapIndex(0, 3, false)).toBe(1);
    expect(nextTrapIndex(2, 3, false)).toBe(0);
    expect(nextTrapIndex(0, 3, true)).toBe(2);
  });

  it('enters from the correct edge when focus is outside', () => {
    expect(nextTrapIndex(-1, 3, false)).toBe(0);
    expect(nextTrapIndex(-1, 3, true)).toBe(2);
  });

  it('handles empty and single-item lists', () => {
    expect(nextTrapIndex(0, 0, false)).toBe(0);
    expect(nextTrapIndex(0, 1, false)).toBe(0);
    expect(nextTrapIndex(0, 1, true)).toBe(0);
  });
});
