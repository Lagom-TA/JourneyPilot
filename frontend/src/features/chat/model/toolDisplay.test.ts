import { describe, expect, it } from "vitest";
import { dedupeToolSteps, describeToolStep, groupToolSteps, isNoResultSummary, isPublicActivityStep, toolResultText } from "./toolDisplay";
import { type ThinkingStep } from "../types/messages";
function step(toolResult: string | undefined): Pick<ThinkingStep, 'toolResult'> {
    return { toolResult };
}
describe('toolResultText', () => {
    it('拒绝带空白前缀的 JSON、嵌套数组载荷，但不误伤正文里的花括号', () => {
        for (const payload of [
            '{"success": true, "provider": "nominatim"}',
            '\n  {"success": true}',
            '[{"text": "{\\"success\\": true}"}]',
        ]) {
            expect(toolResultText(step(payload))).toBeNull();
        }
        expect(toolResultText(step('找到 3 条网页：什么是 {json}'))).toContain('{json}');
    });
    it('内部能力搜索不把内部工具标识当作查询主题', () => {
        const display = describeToolStep({ id: 'internal', agentName: '整理旅行需求', content: '', stepName: '', timestamp: new Date(), isToolCall: true, toolName: 'search_tools', toolCategory: 'internal', toolArgs: JSON.stringify({ query: 'global_place_search 地点' }), toolResult: '已选择适合本次行程的地点与交通资料', toolStatus: 'completed' });
        expect(display.kind).toBe('internal');
        expect(display.subject).toBeNull();
        expect(display.fullSubject).toBeNull();
        expect(display.actionText).not.toContain('global_place_search');
    });
    it('输入只展示已知字段的中文标签，不展示内部能力 query', () => {
        const place = describeToolStep({ id: 'place', agentName: '目的地调研', content: '', stepName: '', timestamp: new Date(), isToolCall: true, toolName: 'global_place_search', toolArgs: JSON.stringify({ query: '西湖', lang: 'zh' }), toolStatus: 'completed' });
        expect(place.inputs).toHaveLength(1);
        expect(place.inputs[0].value).toBe('西湖');
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
        const projected = JSON.stringify({ inputs: internal.inputs, subject: internal.subject, fullSubject: internal.fullSubject });
        for (const name of ['global_place_search', 'brave_web_search', 'tavily_search']) {
            expect(projected).not.toContain(name);
        }
        expect(projected).toContain('附近景点');
        const normal = '杭州西湖周边适合雨天慢慢散步、喝咖啡并避开人群的路线与街区，并给出上午、午后和傍晚三个时间段的具体安排';
        const display = place(normal);
        expect(display.inputs).toEqual([{ label: '查询内容', value: normal }]);
        expect(display.fullSubject).toBe(normal);
    });
    it('激活摘要按工具语义转成中文能力，内部名不会漏出', () => {
        const text = toolResultText(step('激活工具：global_place_search, knowledge_search')) ?? '';
        const web = toolResultText(step('激活工具：brave_local_search, brave_web_search, firecrawl_search, free_web_search, tavily_search')) ?? '';
        for (const internal of ['global_place_search', 'knowledge_search', 'brave_local_search', 'brave_web_search', 'firecrawl_search', 'free_web_search', 'tavily_search']) {
            expect(web).not.toContain(internal);
            expect(text).not.toContain(internal);
        }
    });
    it('普通摘要中的内部标识也按中文能力替换', () => {
        const text = toolResultText(step('tavily_search 未返回结果，改用 free_web_search')) ?? '';
        expect(text).not.toContain('tavily_search');
        expect(text).not.toContain('free_web_search');
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
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'knowledge_search', toolStatus: 'completed', toolResult: '读到 2 段资料库资料', resultPreview: [{ title: '资料' }] }))).toBe(true);
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'knowledge_search', toolStatus: 'degraded', toolResult: '没有匹配的结果' }))).toBe(true);
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'global_place_search', toolStatus: 'completed', toolResult: '没有匹配的结果' }))).toBe(true);
        expect(isPublicActivityStep(base({ isToolCall: true, toolName: 'hotel_search', toolStatus: 'capability_declared', toolResult: '最远可查 11-15，你的 11-20 尚未进入窗口' }))).toBe(true);
    });
});
describe('groupToolSteps', () => {
    const tool = (id: string, toolName: string | undefined = 'global_place_search', extra: Partial<ThinkingStep> = {}): ThinkingStep => ({
        id, toolCallId: id, toolName, isToolCall: true, agentName: '交通查询', content: '', stepName: '', timestamp: new Date('2026-01-01'), toolStatus: 'completed', ...extra,
    });
    it('按真实名称聚合相邻调用，保留不同参数、结果、状态与来源', () => {
        const first = tool('a', 'global_place_search', { toolArgs: 'query=西湖', toolResult: '找到西湖', resultPreview: [{ title: '西湖', url: 'https://example.com/a' }] });
        const second = tool('b', 'GLOBAL_PLACE_SEARCH', { toolArgs: 'query=灵隐寺', toolResult: '找到灵隐寺', fromCache: true, resultPreview: [{ title: '灵隐寺', url: 'https://example.com/b' }] });
        const third = tool('c', 'global_place_search', { toolStatus: 'running', toolArgs: 'query=雷峰塔' });
        const other = tool('d', 'maps_weather');
        const result = groupToolSteps([first, second, third, other]);
        expect(result).toHaveLength(2);
        expect(result[0]).toMatchObject({ kind: 'tool_group', key: 'a', toolName: 'global_place_search', steps: [first, second, third] });
        if (result[0].kind !== 'tool_group') throw new Error('expected group');
        expect(result[0].steps[0]).toBe(first);
        expect(result[0].steps[1]).toBe(second);
        expect(result[0].callEvents).toEqual([[first], [second], [third]]);
        expect(result[1]).toMatchObject({ kind: 'step', step: other });
    });
    it('同参数同结果的不同 ID 也是独立调用', () => {
        const first = tool('a', 'get-tickets', { toolArgs: 'date=2026-01-01', toolResult: '找到 1 条车次' });
        const second = { ...first, id: 'b', toolCallId: 'b' };
        const result = groupToolSteps([first, second]);
        expect(result[0]).toMatchObject({ kind: 'tool_group', steps: [first, second] });
    });
    it('说明、里程碑和不同工具均打断相邻分组', () => {
        const note = tool('note', undefined, { isToolCall: false, kind: 'work_explanation', content: '继续确认。' });
        const milestone = tool('milestone', undefined, { isToolCall: false, progressStatus: 'completed' });
        const steps = [tool('a'), note, tool('b'), milestone, tool('c'), tool('d', 'maps_weather'), tool('e')];
        expect(groupToolSteps(steps).map(item => item.kind)).toEqual(steps.map(() => 'step'));
    });
    it('不同工具的重放事件也会打断相邻分组', () => {
        const first = tool('a', 'maps_weather');
        const second = tool('b', 'get-tickets');
        const replay = { ...first, id: 'a-replay' };
        const third = tool('c', 'get-tickets');
        const items = groupToolSteps([first, second, replay, third]);
        expect(items.map(item => item.kind)).toEqual(['step', 'step', 'step']);
        if (items[0].kind !== 'step') throw new Error('expected step');
        expect(items[0].events).toEqual([first, replay]);
    });
    it('状态更新、追加调用和延迟补充 toolCallId 不改变首 ID 组键', () => {
        const first = tool('step-a', 'get-tickets', { toolCallId: undefined, toolStatus: 'running' });
        const second = tool('b', 'get-tickets', { toolStatus: 'running' });
        const before = groupToolSteps([first, second]);
        const updated = { ...first, toolCallId: 'call-a', toolStatus: 'completed' as const, toolResult: '找到车次' };
        const after = groupToolSteps([updated, { ...second, toolStatus: 'completed' }, tool('c', 'get-tickets')]);
        expect(before[0]).toMatchObject({ kind: 'tool_group', key: 'step-a' });
        expect(after[0]).toMatchObject({ kind: 'tool_group', key: 'step-a', steps: [updated, expect.anything(), expect.anything()] });
    });
    it('同一 toolCallId 重放仅算一次，同时保留输入、结果、来源及原始事件', () => {
        const start = tool('step-a', 'get-tickets', { toolCallId: 'call-a', toolStatus: 'running', toolArgs: 'fromStation=北京南' });
        const result = tool('step-result', 'get-tickets', { toolCallId: 'call-a', toolStatus: 'completed', toolArgs: undefined, toolResult: '找到车次', resultPreview: [{ title: 'G1', url: 'https://example.com/g1' }] });
        const replay = { ...start, id: 'step-replay' };
        const next = tool('b', 'get-tickets', { toolStatus: 'running' });
        const groups = groupToolSteps([start, next, result, replay]);
        expect(groups).toHaveLength(1);
        if (groups[0].kind !== 'tool_group') throw new Error('expected group');
        expect(groups[0].key).toBe('step-a');
        expect(groups[0].steps).toHaveLength(2);
        expect(groups[0].steps[0]).toMatchObject({ id: 'step-a', toolCallId: 'call-a', toolStatus: 'completed', toolArgs: 'fromStation=北京南', toolResult: '找到车次', resultPreview: result.resultPreview });
        expect(groups[0].callEvents).toEqual([[start, result, replay], [next]]);
    });
    it('缺失或未知名称、内部调用、无稳定 ID 及非工具均不聚合', () => {
        for (const patch of [
            { toolName: undefined }, { toolName: ' ' }, { toolName: 'unknown' }, { toolName: '未知工具' },
            { toolName: 'search_tools' }, { toolCategory: 'internal' as const }, { id: '', toolCallId: '' }, { isToolCall: false },
        ]) {
            const first = tool('a', 'global_place_search', patch);
            const second = tool('b', 'global_place_search', patch);
            expect(groupToolSteps([first, second]).map(item => item.kind)).toEqual(['step', 'step']);
        }
    });
});

describe('铁路工具展示', () => {
    it.each(['get-tickets', 'get-interline-tickets', '12306-train:get-tickets', 'GET_TICKETS'])('将 %s 映射为火车查询并展示车站参数', (toolName) => {
        const display = describeToolStep({ id: 'rail', agentName: '交通查询', content: '', stepName: '', timestamp: new Date(), isToolCall: true, toolName, toolCategory: 'data', toolStatus: 'running', toolArgs: JSON.stringify({ fromStation: '北京南', toStation: '上海虹桥', date: '2026-12-01' }) });
        expect(display.kind).toBe('train');
        expect(display.categoryLabel).toBe('班次查询');
        expect(display.actionText).toContain('正在查询火车');
        expect(display.subject).toBe('北京南 → 上海虹桥 · 2026-12-01');
        expect(display.inputs).toEqual([{ label: '出发地', value: '北京南' }, { label: '目的地', value: '上海虹桥' }, { label: '日期', value: '2026-12-01' }]);
    });
    it('摘要不展示机器标识或原始参数字段', () => {
        expect(toolResultText(step('激活工具：get-tickets, get-interline-tickets'))).toBe('已启用：班次查询');
        expect(toolResultText(step('get-tickets 未返回结果，改用 get-interline-tickets'))).toBe('班次查询 未返回结果，改用 班次查询');
        expect(toolResultText(step('fromStation=北京南, toStation=上海虹桥'))).toBeNull();
        expect(toolResultText(step('tool_call_id=123'))).toBeNull();
    });
});

describe('tool row semantics', () => {
    const base = (extra: Partial<ThinkingStep>): ThinkingStep => ({ id: 's', agentName: '目的地调研', content: '', stepName: '', timestamp: new Date(), ...extra });
    it('recognizes no-result summaries', () => {
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
