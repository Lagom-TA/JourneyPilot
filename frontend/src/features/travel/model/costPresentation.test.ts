import { describe, expect, it } from 'vitest';
import { formatTripCostSummary } from './costPresentation';

function cost(overrides: Record<string, unknown>) {
  return {
    known_subtotal_cny: null,
    estimated_total_cny: null,
    priced_component_count: 0,
    budget_relevant_component_count: 0,
    coverage: 'none' as const,
    ...overrides,
  };
}

describe('旅行费用展示', () => {
  it('没有金额时不生成费用文案', () => {
    expect(formatTripCostSummary(cost({}))).toBeNull();
  });
});
