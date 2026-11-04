import { describe, expect, it } from "vitest";
import { dedupeToolSteps, describeToolStep, isNoResultSummary, isPublicActivityStep, toolResultCount, toolResultText, toolStatusLabel } from "./toolDisplay";
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
    it('已知工具使用同一组中文别名，未知工具也回退到中文类别', () => {
        const stepFor = (toolName: string, category: ThinkingStep['toolCategory'] = 'search') => ({ id: toolName, agentName: '目的地调研', content: '', stepName: '', timestamp: new Date(), isToolCall: true, toolName, toolCategory: category });
        expect(describeToolStep(stepFor('global_place_search')).categoryLabel).toBe('地点搜索');
        expect(describeToolStep(stepFor('knowledge_search')).categoryLabel).toBe('知识库检索');
        expect(describeToolStep(stepFor('brave_web_search')).categoryLabel).toBe('网页搜索');
        expect(describeToolStep(stepFor('firecrawl_search')).categoryLabel).toBe('网页搜索');
        expect(describeToolStep(stepFor('tavily_search')).categoryLabel).toBe('网页搜索');
        expect(describeToolStep(stepFor('some_new_mcp_tool')).categoryLabel).toBe('查询旅行信息');
        expect(describeToolStep(stepFor('some_new_mcp_tool', 'internal')).categoryLabel).toBe('整理规划');
    });
    it('输入只展示已知字段的中文标签，不展示内部能力 query', () => {
        const place = describeToolStep({ id: 'place', agentName: '目的地调研', content: '', stepName: '', timestamp: new Date(), isToolCall: true, toolName: 'global_place_search', toolArgs: JSON.stringify({ query: '西湖', lang: 'zh' }), toolStatus: 'completed' });
        expect(place.inputs).toEqual([{ label: '查询内容', value: '西湖' }]);
        const internal = describeToolStep({ id: 'internal', agentName: '整理旅行需求', content: '', stepName: '', timestamp: new Date(), isToolCall: true, toolName: 'search_tools', toolArgs: JSON.stringify({ query: 'global_place_search 地点' }), toolStatus: 'completed' });
        expect(internal.inputs).toEqual([]);
    });
    it('输入与折叠主题都经过公开投影，保留正常和长查询', () => {
        const place = (query: string) => describeToolStep({ id: 'place', agentName: '目的地调研', content: '', stepName: '', timestamp: new Date(), isToolCall: true, toolName: 'global_place_search', toolArgs: JSON.stringify({ query }), toolStatus: 'completed' });
        for (const payload of [
            '{"success":true,"provider":"tavily_search","sanitized_result":{}}',
            'research_packet_id=packet-1 tool_call_id=call-1',
            'contract_version=1',
            'Traceback (most recent call last): File "agent.py", line 42, in run',
            'HTTP 500: upstream provider failed',
        ]) {
            const display = place(payload);
            expect(display.inputs).toEqual([]);
            expect(display.subject).toBeNull();
            expect(display.fullSubject).toBeNull();
        }
        const internal = place('global_place_search brave_web_search 附近景点');
        expect(internal.inputs).toEqual([{ label: '查询内容', value: '地点搜索 网页搜索 附近景点' }]);
        expect(internal.fullSubject).toBe('地点搜索 网页搜索 附近景点');
        for (const name of ['global_place_search', 'brave_web_search', 'tavily_search']) {
            expect(internal.inputs[0].value).not.toContain(name);
            expect(internal.fullSubject).not.toContain(name);
        }
        const normal = '杭州西湖周边适合雨天慢慢散步、喝咖啡并避开人群的路线与街区，并给出上午、午后和傍晚三个时间段的具体安排';
        const display = place(normal);
        expect(display.inputs).toEqual([{ label: '查询内容', value: normal }]);
        expect(display.fullSubject).toBe(normal);
    });
    it('激活摘要按工具语义转成中文能力，内部名不会漏出', () => {
        const text = toolResultText(step('激活工具：global_place_search, knowledge_search'));
        expect(text).toBe('已启用：地点搜索、知识库检索');
        const web = toolResultText(step('激活工具：brave_local_search, brave_web_search, firecrawl_search, free_web_search, tavily_search'));
        expect(web).toContain('网页搜索');
        for (const internal of ['global_place_search', 'knowledge_search', 'brave_local_search', 'brave_web_search', 'firecrawl_search', 'free_web_search', 'tavily_search']) {
            expect(web).not.toContain(internal);
            expect(text).not.toContain(internal);
        }
        expect(toolResultText(step('未匹配到工具'))).toBe('未匹配到工具');
    });
    it('普通摘要中的内部标识也按中文能力替换', () => {
        const text = toolResultText(step('tavily_search 未返回结果，改用 free_web_search'));
        expect(text).not.toContain('tavily_search');
        expect(text).not.toContain('free_web_search');
        expect(text).toContain('网页搜索');
    });
    it('只从公开摘要中的明确总数取计数，不用预览长度', () => {
        expect(toolResultCount('找到 4 个结果：深圳湾公园、红树林')).toBe(4);
        expect(toolResultCount('找到 等 4 个地点：甲、乙')).toBe(4);
        expect(toolResultCount('搜索到 12 条结果')).toBe(12);
        expect(toolResultCount('返回 四条结果')).toBe(4);
        expect(toolResultCount('已返回部分结果')).toBeNull();
        expect(toolResultCount('找到 3 个适合安排进行程的地点')).toBe(3);
        expect(toolResultCount(null)).toBeNull();
    });
    it('保留未截断的查询主题供展开后阅读', () => {
        const query = '杭州西湖周边适合雨天慢慢散步、喝咖啡并避开人群的路线与街区，并给出上午、午后和傍晚三个时间段的具体安排';
        const display = describeToolStep({ id: 'long', agentName: '目的地调研', content: '', stepName: '', timestamp: new Date(), isToolCall: true, toolName: 'global_place_search', toolArgs: JSON.stringify({ query }), toolStatus: 'completed' });
        expect(display.subject).not.toBe(query);
        expect(display.fullSubject).toBe(query);
    });
});

describe('isPublicActivityStep', () => {
    const base = (extra: Partial<ThinkingStep>): ThinkingStep => ({ id: 's', agentName: '目的地调研', content: '', stepName: '', timestamp: new Date(), ...extra });
    it('排除失败工具、失败进展和全部内部能力激活', () => {
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'global_place_search', toolStatus: 'failed' }))).toBe(false);
        expect(isPublicActivityStep(base({ progressStatus: 'failed' }))).toBe(false);
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'search_tools', toolStatus: 'completed', toolResult: '未匹配到工具' }))).toBe(false);
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'search_tools', toolStatus: 'completed', toolResult: '激活工具：global_place_search' }))).toBe(false);
    });
    it('隐藏空知识库/网页，但保留地点空结果、备用来源与能力声明', () => {
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'knowledge_search', toolStatus: 'completed', toolResult: '没有匹配的结果' }))).toBe(false);
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'free_web_search', toolStatus: 'completed', toolResult: '没有匹配的结果' }))).toBe(false);
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'knowledge_search', toolStatus: 'running' }))).toBe(true);
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'knowledge_search', toolStatus: 'completed', toolResult: '读到 2 段知识库资料', resultPreview: [{ title: '资料' }] }))).toBe(true);
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'knowledge_search', toolStatus: 'degraded', toolResult: '没有匹配的结果' }))).toBe(true);
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'global_place_search', toolStatus: 'completed', toolResult: '没有匹配的结果' }))).toBe(true);
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'hotel_search', toolStatus: 'capability_declared', toolResult: '最远可查 11-15，你的 11-20 尚未进入窗口' }))).toBe(true);
    });
});
describe('tool row semantics', () => {
    const base = (extra: Partial<ThinkingStep>): ThinkingStep => ({ id: 's', agentName: '目的地调研', content: '', stepName: '', timestamp: new Date(), ...extra });
    it('状态词区分无结果、备用来源与暂不可查', () => {
        expect(toolStatusLabel('completed')).toBe('已完成');
        expect(toolStatusLabel('degraded')).toBe('备用来源');
        expect(toolStatusLabel('capability_declared')).toBe('暂不可查');
        expect(isNoResultSummary('没有匹配的结果')).toBe(true);
        expect(isNoResultSummary('找到 0 个结果')).toBe(true);
        expect(isNoResultSummary('找到 2 个结果')).toBe(false);
    });
    it('相邻同工具同参数同结果只保留最后一次', () => {
        const first = base({ id: 'a', isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"西湖"}', toolResult: '找到 1 个结果', fromCache: true });
        const second = base({ id: 'b', isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"西湖"}', toolResult: '找到 1 个结果' });
        const other = base({ id: 'c', isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"灵隐寺"}', toolResult: '找到 1 个结果' });
        const merged = dedupeToolSteps([first, second, other]);
        expect(merged.map(item => item.id)).toEqual(['b', 'c']);
        expect(merged[0].fromCache).toBe(true);
    });
    it('保留隔着工作说明的查询、并行查询与不同来源', () => {
        const first = base({ id: 'a', isToolCall: true, toolName: 'global_place_search', toolStatus: 'completed', toolArgs: 'query=西湖', toolResult: '找到 1 个结果' });
        const note = base({ id: 'note', kind: 'work_explanation', content: '继续确认地点。' });
        const second = { ...first, id: 'b' };
        expect(dedupeToolSteps([first, note, second]).map(item => item.id)).toEqual(['a', 'note', 'b']);
        expect(dedupeToolSteps([{ ...first, toolStatus: 'running' }, { ...second, toolStatus: 'running' }])).toHaveLength(2);
        expect(dedupeToolSteps([first, { ...second, resultPreview: [{ title: '另一来源' }] }])).toHaveLength(2);
    });
});
