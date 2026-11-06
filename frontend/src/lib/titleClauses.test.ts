import { describe, expect, it } from 'vitest';
import { splitTitleClauses } from './titleClauses';

describe('splitTitleClauses', () => {
  it('keeps the colon with the clause it ends', () => {
    expect(splitTitleClauses('杭州两日：灵隐钟声与湖塔夜色')).toEqual(['杭州两日：', '灵隐钟声与湖塔夜色']);
    expect(splitTitleClauses('Hangzhou: Lingyin bells')).toEqual(['Hangzhou:', ' Lingyin bells']);
  });

  it('returns one clause when there is no colon', () => {
    expect(splitTitleClauses('苏州两日慢游')).toEqual(['苏州两日慢游']);
  });

  it('never drops or reorders characters', () => {
    const title = '成都：慢慢逛：吃一周';
    expect(splitTitleClauses(title).join('')).toBe(title);
    expect(splitTitleClauses('：开头')).toEqual(['：', '开头']);
    expect(splitTitleClauses('')).toEqual(['']);
  });
});
