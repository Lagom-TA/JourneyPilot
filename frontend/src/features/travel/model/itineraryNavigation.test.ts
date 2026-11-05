import { describe, expect, it } from 'vitest';
import { isUnscheduledItem, tripSegments, unresolvedForDay } from './itineraryNavigation';
import { type DaySummaryVM } from './itineraryPresentation';
import { type PublicDeliveryBundle } from '../types/delivery';

function day(number: number, destination: string): DaySummaryVM {
  return { dayId: `day-${number}`, day: number, dateLabel: `12月${number}日`, weekdayLabel: null, destinationLabel: destination, theme: '慢游', weather: null, nodes: [], hiddenNodeCount: 0 };
}

describe('trip segments', () => {
  it('merges consecutive stays while preserving separate return visits', () => {
    const result = tripSegments([day(1, '成都'), day(2, '成都'), day(3, '乐山'), day(4, '成都')]);
    expect(result.map((segment) => [segment.label, segment.days.map((value) => value.day), segment.dateLabel])).toEqual([
      ['成都', [1, 2], '12月1日 — 12月2日'], ['乐山', [3], '12月3日'], ['成都', [4], '12月4日'],
    ]);
    expect(new Set(result.map((segment) => segment.id)).size).toBe(3);
    expect(tripSegments([])).toEqual([]);
  });
});

describe('day-specific unresolved items', () => {
  const bundle = {
    workspace: { itinerary: {
      day_plans: [{ day_id: 'six', day: 6, date: '2026-12-10' }, { day_id: 'sixteen', day: 16, date: '2026-12-20' }],
      unresolved: ['第 6 天下午尚未安排具体活动。', '2026-12-10 餐饮至住宿的接驳尚未核实。', '第 16 天尚未安排。', '全程公共信息。'],
    } },
  } as PublicDeliveryBundle;

  it('matches day numbers or dates without mixing day six with day sixteen', () => {
    expect(unresolvedForDay(bundle, 'six')).toEqual(['第 6 天下午尚未安排具体活动。', '2026-12-10 餐饮至住宿的接驳尚未核实。']);
    expect(unresolvedForDay(bundle, 'missing')).toEqual([]);
  });

  it('distinguishes unscheduled activities from information gaps', () => {
    expect(isUnscheduledItem('第 6 天下午尚未安排具体活动。')).toBe(true);
    expect(isUnscheduledItem('接驳尚未核实。')).toBe(false);
  });
});
