import { describe, expect, it } from "vitest";
import { publicProgressText, researchGroups } from "./researchProgress";
import { appReducer } from "../../../app/state/appReducer";
import { type AppState } from "../../../app/state/state";
import { type ThinkingStep } from "../types/messages";
import { describeToolStep } from "./toolDisplay";
const step = (agentName: string, extra: Partial<ThinkingStep> = {}): ThinkingStep => ({ id: agentName, agentName, content: '', stepName: '', timestamp: new Date(), ...extra });
describe('public research activity', () => {
    it('blocks old JSON records even after a natural-language prefix', () => {
        expect(publicProgressText('正在分派并行调研任务{"contract_version":"journeypilot.research_packet.v5"}')).toBe('');
        expect(publicProgressText('```json\n{"candidates":[]}')).toBe('');
        expect(publicProgressText('找到 1 个结果')).toBe('找到 1 个结果');
    });
    it('keeps simultaneous workers separate and does not finish one when another emits', () => {
        const steps = [step('目的地调研', { progressStatus: 'running' }), step('交通查询', { progressStatus: 'running' }), step('目的地调研', { progressStatus: 'completed', endTime: new Date() })];
        expect(researchGroups(steps, true, false).map(g => [g.title, g.status])).toEqual([['目的地调研', 'completed'], ['交通查询', 'running']]);
        expect(researchGroups(steps, false, true)[1].status).toBe('stopped');
        expect(researchGroups([...steps, step('交通查询', { progressStatus: 'failed' })], true, false)[1].status).toBe('failed');
    });
    it('ignores raw deltas and finishes only same-agent non-tool steps', () => {
        const steps = [step('任务分发'), step('交通查询', { isToolCall: true, toolStatus: 'running' })];
        const state = { thinkingSteps: steps, currentMessages: [] } as unknown as AppState;
        expect(appReducer(state, { type: 'FINISH_LAST_THINKING_STEP', payload: { agentName: '目的地调研', endTime: new Date() } })).toBe(state);
        expect(appReducer(state, { type: 'UPDATE_LAST_TOOL_STEP', payload: { toolCallId: 'unknown', agentName: '目的地调研', toolStatus: 'completed' } })).toBe(state);
    });
    it('labels real place/route tools and respects explicit terminal status', () => {
        expect(describeToolStep(step('目的地调研', { toolName: 'global_place_search', toolStatus: 'completed' })).kind).toBe('place_search');
        const route = describeToolStep(step('交通查询', { toolName: 'global_route_search', toolStatus: 'completed', toolArgs: '{"from_name":"长春站","to_name":"市中心"}' }));
        expect(route.status).toBe('completed');
        expect(route.subject).toContain('长春站');
    });
});
