import { describe, expect, it } from 'vitest';
import { parseTripBudget } from './tripIdentityValidation';

describe('旅行预算输入', () => {
  it('空白表示未填写预算', () => {
    expect(parseTripBudget('')).toEqual({ value: null, error: null });
    expect(parseTripBudget('   ')).toEqual({ value: null, error: null });
  });

  it('接受带千位分隔符的正金额', () => {
    expect(parseTripBudget('12,000')).toEqual({ value: 12000, error: null });
    expect(parseTripBudget('８，０００')).toEqual({ value: null, error: '总预算请输入大于 0 的金额' });
  });

  it('拒绝零、负数和非数字', () => {
    for (const raw of ['0', '-1', 'abc']) {
      expect(parseTripBudget(raw).error).toBe('总预算请输入大于 0 的金额');
    }
  });
});
