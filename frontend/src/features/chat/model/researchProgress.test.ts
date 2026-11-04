import { describe, expect, it } from "vitest";
import { publicProgressText, researchGroups } from "./researchProgress";
import { appReducer } from "../../../app/state/appReducer";
import { type AppState } from "../../../app/state/state";
import { type ThinkingStep } from "../types/messages";
import { describeToolStep } from "./toolDisplay";
const step = (agentName: string, extra: Partial<ThinkingStep> = {}): ThinkingStep => ({ id: agentName, agentName, content: '', stepName: '', timestamp: new Date(), ...extra });
describe('public research activity', () => {
    it('blocks old JSON records even after a natural-language prefix', () => {
        expect(publicProgressText('正在按顺序安排调研任务{"research_packet_id":"packet-1"}')).toBe('');
        expect(publicProgressText('```json\n{"candidates":[]}')).toBe('');
        expect(publicProgressText('找到 1 个结果')).toBe('找到 1 个结果');
    });
    it('projects stage cards without a fixed role description', () => {
        const [planning] = researchGroups([step('requirements_preparer', { progressStatus: 'running' })], true, false);
        expect(planning.title).toBe('整理旅行需求');
        expect('description' in planning).toBe(false);
    });
    it('keeps each worker lifecycle separate and does not finish one when another emits', () => {
        const steps = [step('目的地调研', { progressStatus: 'running' }), step('交通查询', { progressStatus: 'running' }), step('目的地调研', { progressStatus: 'completed', endTime: new Date() })];
        expect(researchGroups(steps, true, false).map(g => [g.title, g.status])).toEqual([['目的地调研', 'completed'], ['交通查询', 'running']]);
        expect(researchGroups(steps, false, true)[1].status).toBe('stopped');
        expect(researchGroups([...steps, step('交通查询', { progressStatus: 'failed' })], true, false)[1].status).toBe('failed');
    });
    it('ignores raw deltas, finishes same-agent non-tool steps, and skips unknown tool ids', () => {
        const steps = [step('任务分发'), step('交通查询', { isToolCall: true, toolStatus: 'running' })];
        const state = { thinkingSteps: steps, currentMessages: [] } as unknown as AppState;
        // 同 agent 的非工具步骤被结束：任务分发的这一步带上结束时间。
        const finished = appReducer(state, { type: 'FINISH_LAST_THINKING_STEP', payload: { agentName: '任务分发', endTime: new Date() } });
        expect(finished.thinkingSteps[0].endTime).toBeTruthy();
        expect(finished.thinkingSteps[1].endTime).toBeUndefined();
        // 未知 toolCallId 是幂等 no-op：状态原样返回。
        expect(appReducer(state, { type: 'UPDATE_LAST_TOOL_STEP', payload: { toolCallId: 'unknown', agentName: '目的地调研', toolStatus: 'completed' } })).toBe(state);
    });
    it('labels real place/route tools and respects explicit terminal status', () => {
        expect(describeToolStep(step('目的地调研', { toolName: 'global_place_search', toolStatus: 'completed' })).kind).toBe('place_search');
        const route = describeToolStep(step('交通查询', { toolName: 'global_route_search', toolStatus: 'completed', toolArgs: '{"from_name":"长春站","to_name":"市中心"}' }));
        expect(route.status).toBe('completed');
        expect(route.subject).toContain('长春站');
    });
});
describe('stage-scoped research groups', () => {
    it('把 dispatcher 归到资料阶段，而不是需求整理组', () => {
        const groups = researchGroups([step('安排查询'), step('目的地调研')], true, false);
        expect(groups.map(group => [group.id, group.stage])).toEqual([
            ['dispatch', 'research'],
            ['destination', 'research'],
        ]);
        expect(groups[0].title).toBe('安排查询');
    });
    it('阶段 done 时不再有组显示进行中', () => {
        const steps = [
            step('目的地调研', { progressStatus: 'running' }),
            step('目的地调研', { isToolCall: true, toolName: 'global_place_search', toolStatus: 'running' }),
        ];
        const groups = researchGroups(steps, true, false, 'done');
        expect(groups[0].status).toBe('completed');
    });
    it('阶段 failed/stopped 时保留非正常终态', () => {
        const running = [step('目的地调研', { isToolCall: true, toolName: 'global_place_search', toolStatus: 'running' })];
        expect(researchGroups(running, true, false, 'failed')[0].status).toBe('failed');
        expect(researchGroups(running, true, false, 'stopped')[0].status).toBe('stopped');
        const completed = [step('目的地调研', { progressStatus: 'completed', endTime: new Date() })];
        expect(researchGroups(completed, false, false, 'failed')[0].status).toBe('completed');
    });
    it('阶段 active 但没有实时流时，遗留 running 收口为 stopped', () => {
        const running = [step('目的地调研', { isToolCall: true, toolName: 'global_place_search', toolStatus: 'running' })];
        expect(researchGroups(running, false, false, 'active')[0].status).toBe('stopped');
    });
});
describe('generic chat grouping compatibility', () => {
    it('普通聊天里需求组在后续 worker 出现后仍收口为已结束', () => {
        const groups = researchGroups([
            step('requirements_preparer', { progressStatus: 'running' }),
            step('目的地调研', { progressStatus: 'running' }),
        ], true, false);
        expect(groups.find(group => group.id === 'planning')?.status).toBe('completed');
        expect(groups.find(group => group.id === 'destination')?.status).toBe('running');
    });
});
