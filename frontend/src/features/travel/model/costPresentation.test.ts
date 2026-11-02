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
  it('优先展示完整的全程估算', () => {
    expect(formatTripCostSummary(cost({ estimated_total_cny: 11600, known_subtotal_cny: 1488 }))).toBe('全程约 ¥11,600');
  });

  it('只有部分已列价格时不冒充全程总费用', () => {
    expect(formatTripCostSummary(cost({ known_subtotal_cny: 1488 }))).toBe('已列费用约 ¥1,488');
  });

  it('没有金额时不生成费用文案', () => {
    expect(formatTripCostSummary(cost({}))).toBeNull();
  });
});
