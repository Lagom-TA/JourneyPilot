import { describe, expect, it } from 'vitest';
import { formatTripBudget, formatTripCostSummary } from './costPresentation';

function cost(overrides: Record<string, unknown>) {
  return {
    known_subtotal_cny: null,
    estimated_total_cny: null,
    priced_component_count: 0,
    budget_relevant_component_count: 0,
    coverage: 'none' as const,
    budget_cap_cny: null,
    budget_status: 'unknown' as const,
    llm_estimated_total_cny: null,
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

  it('总预算与全程费用分开呈现', () => {
    expect(formatTripBudget(cost({ budget_cap_cny: 12000 }))).toBe('总预算约 ¥12,000');
  });

  it('没有金额时不生成费用或预算文案', () => {
    expect(formatTripCostSummary(cost({}))).toBeNull();
    expect(formatTripBudget(cost({}))).toBeNull();
  });
});
