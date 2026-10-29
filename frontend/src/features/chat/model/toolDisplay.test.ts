import { describe, expect, it } from "vitest";
import { describeToolStep, toolResultText } from "./toolDisplay";
import { type ThinkingStep } from "../types/messages";
function step(toolResult: string | undefined): Pick<ThinkingStep, 'toolResult'> {
    return { toolResult };
}
describe('toolResultText', () => {
    it('保留旅行者可读的摘要', () => {
        expect(toolResultText(step('找到 4 个结果：深圳湾公园、红树林、人才公园…'))).toBe('找到 4 个结果：深圳湾公园、红树林、人才公园…');
    });
    it('拒绝带空白前缀的 JSON、嵌套数组载荷，但不误伤正文里的花括号', () => {
        for (const payload of [
            '{"success": true, "provider": "nominatim"}',
            '\n  {"success": true}',
            '[{"text": "{\\"success\\": true}"}]',
        ]) {
            expect(toolResultText(step(payload))).toBeNull();
        }
        expect(toolResultText(step('找到 3 条网页：什么是 {json}'))).toBe('找到 3 条网页：什么是 {json}');
    });
    it('没有摘要时不渲染空内容', () => {
        expect(toolResultText(step(undefined))).toBeNull();
        expect(toolResultText(step('   '))).toBeNull();
    });
    it('内部能力搜索不把内部工具标识当作查询主题', () => {
        const display = describeToolStep({ id: 'internal', agentName: '整理旅行需求', content: '', stepName: '', timestamp: new Date(), isToolCall: true, toolName: 'search_tools', toolCategory: 'internal', toolArgs: JSON.stringify({ query: 'global_place_search 地点' }), toolResult: '已选择适合本次行程的地点与交通资料', toolStatus: 'completed' });
        expect(display.kind).toBe('internal');
        expect(display.categoryLabel).toBe('整理规划');
        expect(display.subject).toBeNull();
        expect(display.fullSubject).toBeNull();
        expect(display.actionText).not.toContain('global_place_search');
    });
    it('保留未截断的查询主题供展开后阅读', () => {
        const query = '杭州西湖周边适合雨天慢慢散步、喝咖啡并避开人群的路线与街区，并给出上午、午后和傍晚三个时间段的具体安排';
        const display = describeToolStep({ id: 'long', agentName: '目的地调研', content: '', stepName: '', timestamp: new Date(), isToolCall: true, toolName: 'global_place_search', toolArgs: JSON.stringify({ query }), toolStatus: 'completed' });
        expect(display.subject).not.toBe(query);
        expect(display.fullSubject).toBe(query);
    });
});
