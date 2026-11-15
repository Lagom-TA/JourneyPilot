import { describe, expect, it } from "vitest";
import { deriveActivityStages, getActivityStageIdForAgent, latestActivityStageId, parseAgentRound } from "./agentStages";
import { researchGroups } from "./researchProgress";
import { type ThinkingStep } from "../types/messages";
function step(agentName: string): ThinkingStep {
    return {
        id: agentName,
        agentName,
        content: '',
        stepName: agentName,
        timestamp: new Date('2026-01-01T00:00:00Z'),
    };
}
describe('agent stage projection', () => {
    it('解析中英文节点名与补充轮次', () => {
        expect(parseAgentRound('destination_researcher_r2')).toEqual({ base: 'destination_researcher', round: 2 });
        expect(parseAgentRound('目的地调研（第3轮补充）')).toEqual({ base: '目的地调研', round: 3 });
        expect(parseAgentRound('目的地调研(第4轮)')).toEqual({ base: '目的地调研', round: 4 });
    });
    it.each([
        ['交通查询（第 2 轮补充）', 2],
        ['交通查询(第 2 轮补充)', 2],
        [' 交通查询  （  第  12  轮 补充  ）  ', 12],
        ['交通查询 ( 第 3 轮 补充 )', 3],
        ['交通查询（第 4 轮 ）', 4],
        ['交通查询　（第　5　轮补充）', 5],
    ])('解析括号和轮次周围的空格：%s', (name, round) => {
        expect(parseAgentRound(name)).toEqual({ base: '交通查询', round });
    });
    it('不把非轮次后缀解析为补充轮次', () => {
        expect(parseAgentRound('交通查询（第 2 轮补充')).toEqual({ base: '交通查询（第 2 轮补充', round: 0 });
        expect(parseAgentRound('交通查询_r2_extra')).toEqual({ base: '交通查询_r2_extra', round: 0 });
    });
});
describe('activity stage filtering', () => {
    const base = { isStreaming: false, isSynthesizing: false, answerStarted: false };
    it('从事件顺序推导最新阶段，路线不会因迟到研究回退', () => {
        expect(latestActivityStageId({ ...base, steps: [] })).toBeNull();
        expect(latestActivityStageId({ ...base, isStreaming: true, steps: [] })).toBe('requirements');
        expect(latestActivityStageId({ ...base, steps: [step('requirements_preparer')] })).toBe('requirements');
        expect(latestActivityStageId({ ...base, steps: [step('目的地调研')] })).toBe('research');
        expect(latestActivityStageId({ ...base, steps: [step('目的地调研'), step('行程规划')] })).toBe('route');
        expect(latestActivityStageId({ ...base, steps: [step('行程规划'), step('目的地调研')] })).toBe('route');
        expect(latestActivityStageId({ ...base, steps: [step('行程规划'), step('整理需求（第2轮补充）')] })).toBe('requirements');
        expect(latestActivityStageId({ ...base, steps: [step('delivery_projector')] })).toBe('delivery');
    });
    it('返研重做轮把过程区焦点拉回研究，继续组合后回到路线', () => {
        expect(latestActivityStageId({ ...base, steps: [step('行程规划'), step('目的地调研（第2轮补充）')] })).toBe('research');
        expect(latestActivityStageId({ ...base, steps: [step('行程规划'), step('目的地调研（第2轮补充）'), step('行程规划')] })).toBe('route');
        // 首轮研究事件不触发回退，保持原有串行推进语义。
        expect(latestActivityStageId({ ...base, steps: [step('行程规划'), step('目的地调研')] })).toBe('route');
    });
    it('门与等待确认只在需求阶段生效，完成/合成/开始输出优先落到固定阶段', () => {
        const routeSteps = [step('行程规划')];
        expect(latestActivityStageId({ ...base, steps: [], gatePending: true })).toBe('requirements');
        expect(latestActivityStageId({ ...base, steps: [step('理解旅行需求')], gatePending: true })).toBe('requirements');
        // 研究/路线已经留下行动时，门是返工确认，不能把焦点拉回需求。
        expect(latestActivityStageId({ ...base, steps: routeSteps, gatePending: true })).toBe('route');
        expect(latestActivityStageId({ ...base, steps: routeSteps, runStatus: 'awaiting_input' })).toBe('route');
        expect(latestActivityStageId({ ...base, steps: routeSteps, runStatus: 'completed' })).toBe('delivery');
        expect(latestActivityStageId({ ...base, steps: routeSteps, isSynthesizing: true })).toBe('delivery');
        expect(latestActivityStageId({ ...base, steps: routeSteps, answerStarted: true })).toBe('delivery');
    });
});
describe('four-stage activity projection', () => {
    it('识别后端公开的中文名与 dispatcher', () => {
        expect(getActivityStageIdForAgent('理解旅行需求')).toBe('requirements');
        expect(getActivityStageIdForAgent('等待你的回答')).toBe('requirements');
        expect(getActivityStageIdForAgent('安排查询')).toBe('research');
        expect(getActivityStageIdForAgent('理解旅行需求（第2轮补充）')).toBe('requirements');
    });
    it('将研究方案及既有节点名归入需求阶段', () => {
        for (const name of ['research_plan_generator', '研究生成', '研究方案', '研究方案（第 2 轮补充）']) {
            expect(getActivityStageIdForAgent(name)).toBe('requirements');
        }
        expect(getActivityStageIdForAgent('研究方案以外')).toBeNull();
    });
    it('将带空格的补充轮次归入对应研究阶段', () => {
        for (const name of ['交通查询（第 2 轮补充）', '住宿查询 ( 第 3 轮 补充 )', '目的地调研（第 4 轮 ）']) {
            expect(getActivityStageIdForAgent(name)).toBe('research');
        }
    });
    it('研究方案与补充研究事件落入对应成员分组', () => {
        const groups = researchGroups([
            step('研究方案'),
            step('交通查询'),
            step('交通查询（第 2 轮补充）'),
            step('住宿查询 ( 第 3 轮 补充 )'),
        ], true, false);
        expect(groups.map(group => [group.id, group.stage, group.steps.map(item => item.agentName)])).toEqual([
            ['planning', 'requirements', ['研究方案']],
            ['transport', 'research', ['交通查询', '交通查询（第 2 轮补充）']],
            ['stay', 'research', ['住宿查询 ( 第 3 轮 补充 )']],
        ]);
    });
    it('已完成阶段在 Run 仍运行时保持 done，当前阶段才 active', () => {
        const projection = deriveActivityStages(
            [step('理解旅行需求'), step('目的地调研')],
            { isStreaming: true, isSynthesizing: false, answerStarted: false },
        );
        expect(projection.currentStage).toBe('research');
        expect(projection.stages.find(stage => stage.id === 'requirements')?.status).toBe('done');
        expect(projection.stages.find(stage => stage.id === 'research')?.status).toBe('active');
        expect(projection.stages.find(stage => stage.id === 'route')?.status).toBe('pending');
    });
    it('迟到研究事件不把焦点从路线拉回研究', () => {
        const projection = deriveActivityStages(
            [step('行程规划'), step('目的地调研')],
            { isStreaming: true, isSynthesizing: false, answerStarted: false },
        );
        expect(projection.currentStage).toBe('route');
        expect(projection.stages.find(stage => stage.id === 'research')?.status).toBe('done');
        expect(projection.stages.find(stage => stage.id === 'route')?.status).toBe('active');
    });
    it('失败、取消、中断落在当前阶段，不伪装成完成', () => {
        const steps = [step('理解旅行需求'), step('目的地调研')];
        const base = { isStreaming: false, isSynthesizing: false, answerStarted: false };
        const failed = deriveActivityStages(steps, { ...base, runStatus: 'failed' });
        expect(failed.currentStage).toBe('research');
        expect(failed.stages.find(stage => stage.id === 'requirements')?.status).toBe('done');
        expect(failed.stages.find(stage => stage.id === 'research')?.status).toBe('failed');
        for (const runStatus of ['cancelled', 'interrupted']) {
            const stopped = deriveActivityStages(steps, { ...base, runStatus });
            expect(stopped.currentStage).toBe('research');
            expect(stopped.stages.find(stage => stage.id === 'research')?.status).toBe('stopped');
        }
        const stopping = deriveActivityStages(steps, { ...base, isStreaming: true, runStatus: 'cancel_requested' });
        expect(stopping.stages.find(stage => stage.id === 'research')?.status).toBe('active');
    });
    it('补充轮次可以回到需求或研究', () => {
        const base = { isStreaming: true, isSynthesizing: false, answerStarted: false };
        expect(deriveActivityStages([step('行程规划'), step('整理需求（第2轮补充）')], base).currentStage).toBe('requirements');
        expect(deriveActivityStages([step('行程规划'), step('目的地调研（第2轮补充）')], base).currentStage).toBe('research');
        const transport = deriveActivityStages([step('行程规划'), step('交通查询（第 2 轮补充）')], base);
        expect(transport.currentStage).toBe('research');
        expect(transport.stages.find(stage => stage.id === 'research')?.status).toBe('active');
        expect(deriveActivityStages([step('行程规划'), step('研究方案（第 2 轮补充）')], base).currentStage).toBe('requirements');
    });
    it('等待用户门停在需求阶段，完成态全部收口', () => {
        const base = { isStreaming: false, isSynthesizing: false, answerStarted: false };
        const gate = deriveActivityStages([step('理解旅行需求')], { ...base, gatePending: true });
        expect(gate.currentStage).toBe('requirements');
        expect(gate.stages.find(stage => stage.id === 'requirements')?.status).toBe('active');
        const completed = deriveActivityStages([step('目的地调研')], { ...base, runStatus: 'completed' });
        expect(completed.stages.every(stage => stage.status === 'done')).toBe(true);
    });
    it('研究开始后的方案门不把已完成的需求阶段拉回进行中', () => {
        const base = { isStreaming: false, isSynthesizing: false, answerStarted: false };
        const gate = deriveActivityStages(
            [step('理解旅行需求'), step('目的地调研')],
            { ...base, gatePending: true },
        );
        expect(gate.currentStage).toBe('research');
        expect(gate.stages.find(stage => stage.id === 'requirements')?.status).toBe('done');
        expect(gate.stages.find(stage => stage.id === 'research')?.status).toBe('active');
    });
});
