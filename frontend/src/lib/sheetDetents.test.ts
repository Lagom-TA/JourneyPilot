import { describe, expect, it } from 'vitest';
import { releaseSheet, sheetOffset } from './sheetDetents';

describe('sheet release', () => {
  it('settles near the release position for a slow drag', () => {
    expect(releaseSheet(736, 30, 0, 55)).toBe(92);
    expect(releaseSheet(736, 280, 0, 92)).toBe(55);
    expect(releaseSheet(736, 680, 0, 55)).toBe(0);
  });

  it('uses the release velocity to choose a reachable anchor', () => {
    expect(releaseSheet(736, 190, -400, 55)).toBe(92);
    expect(releaseSheet(736, 460, 400, 55)).toBe(0);
  });

  it('steps down through the two detents on a fast downward flick', () => {
    expect(releaseSheet(736, 50, 1100, 92)).toBe(55);
    expect(releaseSheet(736, 300, 1100, 55)).toBe(0);
    expect(releaseSheet(736, 500, -1100, 55)).toBe(92);
  });

  it('keeps the same visible proportions when the containing workspace resizes', () => {
    expect(sheetOffset(736, 92)).toBe(0);
    expect(sheetOffset(736, 0)).toBe(736);
    expect(sheetOffset(736, 55) / 736).toBeCloseTo(sheetOffset(420, 55) / 420);
  });
});
