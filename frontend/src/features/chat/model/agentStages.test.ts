import { describe, expect, it } from "vitest";
import { deriveActivityStages, deriveActivityTitle, deriveStages, filterStepsForActivityStage, getActivityStageIdForAgent, getStageIdForAgent, latestActivityStageId, latestActivityStageWithSteps, parseAgentRound } from "./agentStages";
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
    it('只在服务端确认完成后将全部阶段标为完成', () => {
        const signals = { isStreaming: false, isSynthesizing: false, answerStarted: true };
        expect(deriveStages([], signals).stages.every(stage => stage.status === 'pending')).toBe(true);
        expect(deriveStages([], { ...signals, completed: true }).stages.every(stage => stage.status === 'done')).toBe(true);
        expect(deriveStages([step('delivery_projector')], { ...signals, answerStarted: false, completed: false }).stages.find(stage => stage.id === 'synthesis')?.status).toBe('pending');
    });
    it.each([
        ['中文节点', '目的地调研', 'research'],
        ['内部节点', 'delivery_finalizer', 'synthesis'],
        ['中文补研节点', '目的地调研（第2轮补充）', 'research'],
        ['内部补研节点', 'destination_researcher_r2', 'research'],
    ] as const)('%s 映射到 %s', (_label, agentName, stage) => {
        expect(getStageIdForAgent(agentName)).toBe(stage);
    });
    it('把实际节点投影到阶段状态', () => {
        const { stages, hasDeepWorkflow } = deriveStages([step('planner'), step('目的地调研（第2轮补充）')], { isStreaming: true, isSynthesizing: false, answerStarted: false });
        expect(hasDeepWorkflow).toBe(true);
        expect(stages.find((stage) => stage.id === 'planning')?.status).toBe('done');
        expect(stages.find((stage) => stage.id === 'research')?.status).toBe('active');
    });
    it('解析中英文节点名与补充轮次', () => {
        expect(parseAgentRound('destination_researcher_r2')).toEqual({ base: 'destination_researcher', round: 2 });
        expect(parseAgentRound('目的地调研（第3轮补充）')).toEqual({ base: '目的地调研', round: 3 });
        expect(parseAgentRound('目的地调研(第4轮)')).toEqual({ base: '目的地调研', round: 4 });
    });
    it('按真实步骤投影当前过程标题，并允许补充轮次回退', () => {
        const base = { isStreaming: true, isSynthesizing: false, answerStarted: false };
        expect(deriveActivityTitle({ ...base, steps: [] })).toBe('整理旅行需求');
        expect(deriveActivityTitle({ ...base, steps: [step('requirements_preparer')] })).toBe('整理旅行需求');
        expect(deriveActivityTitle({ ...base, steps: [step('目的地调研（第2轮补充）')] })).toBe('查找旅行资料');
        expect(deriveActivityTitle({ ...base, steps: [step('安排查询'), step('行程规划')] })).toBe('安排每天路线');
        // 路线开始后迟到的研究事件不回退阶段。
        expect(deriveActivityTitle({ ...base, steps: [step('行程规划'), step('目的地调研')] })).toBe('安排每天路线');
        // 真正重新整理需求的补充轮次可以回退。
        expect(deriveActivityTitle({ ...base, steps: [step('行程规划'), step('整理需求（第2轮补充）')] })).toBe('整理旅行需求');
        expect(deriveActivityTitle({ ...base, steps: [step('delivery_projector')] })).toBe('生成完整计划');
        expect(deriveActivityTitle({ ...base, steps: [step('行程规划')], runStatus: 'completed' })).toBe('旅行规划已完成');
        expect(deriveActivityTitle({ ...base, steps: [step('行程规划')], runStatus: 'failed' })).toBe('旅行规划未完成');
        expect(deriveActivityTitle({ ...base, steps: [step('行程规划')], runStatus: 'cancelled' })).toBe('旅行规划已取消');
    });
    it('快答节点不进入深度阶段', () => {
        const { stages, hasDeepWorkflow } = deriveStages([step('fast_answer_agent')], { isStreaming: true, isSynthesizing: false, answerStarted: false });
        expect(getStageIdForAgent('fast_answer_agent')).toBeNull();
        expect(getStageIdForAgent('旅行顾问')).toBeNull();
        expect(hasDeepWorkflow).toBe(false);
        expect(stages.every((stage) => stage.status === 'pending')).toBe(true);
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
    it('按阶段过滤时保留顺序，并单独给出最近有内容的阶段', () => {
        const steps = [step('requirements_preparer'), step('目的地调研'), step('交通查询'), step('行程规划')];
        expect(filterStepsForActivityStage(steps, 'research').map(item => item.agentName)).toEqual(['目的地调研', '交通查询']);
        expect(filterStepsForActivityStage(steps, 'delivery')).toEqual([]);
        expect(latestActivityStageWithSteps(steps)).toBe('route');
        expect(latestActivityStageWithSteps(steps.slice(0, 3))).toBe('research');
        expect(latestActivityStageWithSteps([step('fast_answer_agent')])).toBeNull();
    });
});
describe('four-stage activity projection', () => {
    it('识别真实公开中文名、旧别名与 dispatcher', () => {
        expect(getActivityStageIdForAgent('理解旅行需求')).toBe('requirements');
        expect(getActivityStageIdForAgent('等待你的回答')).toBe('requirements');
        expect(getActivityStageIdForAgent('安排查询')).toBe('research');
        expect(getActivityStageIdForAgent('理解旅行需求（第2轮补充）')).toBe('requirements');
        // 旧夹具仍可读，但新事件使用后端真实公开名。
        expect(getActivityStageIdForAgent('理解需求')).toBe('requirements');
        expect(getActivityStageIdForAgent('等待回答')).toBe('requirements');
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
