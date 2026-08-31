import { describe, expect, it } from 'vitest';

import { toolResultText } from './toolDisplay';
import type { ThinkingStep } from '../types/chat';

function step(toolResult: string | undefined): Pick<ThinkingStep, 'toolResult'> {
  return { toolResult };
}

/**
 * 产品面永远不印工具原始载荷：历史会话里的旧摘要也必须经过同一条过滤线。
 */
describe('toolResultText', () => {
  it('保留旅行者可读的摘要', () => {
    expect(toolResultText(step('找到 4 个结果：深圳湾公园、红树林、人才公园…'))).toBe(
      '找到 4 个结果：深圳湾公园、红树林、人才公园…',
    );
  });

  it('拒绝带空白前缀的 JSON、嵌套数组载荷，但不误伤正文里的花括号', () => {
    for (const payload of [
      '{"success": true, "provider": "nominatim"}',
      '\n  {"success": true}',
      '[{"text": "{\\"success\\": true}"}]',
    ]) {
      expect(toolResultText(step(payload))).toBeNull();
    }
    expect(toolResultText(step('找到 3 条网页：什么是 {json}'))).toBe(
      '找到 3 条网页：什么是 {json}',
    );
  });

  it('没有摘要时不渲染空内容', () => {
    expect(toolResultText(step(undefined))).toBeNull();
    expect(toolResultText(step('   '))).toBeNull();
  });
});
