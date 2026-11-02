import { type ThinkingStep } from "../types/messages";
export type StageId = 'planning' | 'research' | 'synthesis';
export type StageStatus = 'pending' | 'active' | 'done';
export interface StageDef {
    id: StageId;
    label: string;
    responsibility: string;
}
export const STAGE_DEFS: StageDef[] = [
    { id: 'planning', label: '规划', responsibility: '理解你的需求，整理旅行信息并准备相关查询' },
    { id: 'research', label: '调研', responsibility: '查询目的地、交通和住宿，安排每日行程' },
    { id: 'synthesis', label: '交付', responsibility: '汇总旅行内容并保存完整计划' },
];
const NODE_STAGES: ReadonlyArray<readonly [
    node: string,
    display: string,
    stage: StageId
]> = [
    ['scope_clarifier', '需求确认', 'planning'],
    ['understanding_agent', '理解需求', 'planning'],
    ['understanding_gate', '等待回答', 'planning'],
    ['requirements_preparer', '整理需求', 'planning'],
    ['research_plan_generator', '研究生成', 'planning'],
    ['minimum_delivery_draft_builder', '行程框架', 'planning'],
    ['intent_amendment_router', '要求更新', 'planning'],
    ['destination_geo_resolver', '目的地定位', 'planning'],
    ['weather_context_builder', '天气信息', 'planning'],
    ['trip_summary_card_brief', '旅行摘要', 'planning'],
    ['planner', '制定计划', 'planning'],
    ['plan_gate', '确认方案', 'planning'],
    ['dispatcher', '安排查询', 'planning'],
    ['destination_researcher', '目的地调研', 'research'],
    ['transport_researcher', '交通查询', 'research'],
    ['accommodation_researcher', '住宿查询', 'research'],
    ['itinerary_planner', '行程规划', 'research'],
    ['delivery_projector', '整理行程', 'synthesis'],
    ['delivery_finalizer', '保存计划', 'synthesis'],
];
export const AGENT_TO_STAGE: Record<string, StageId> = Object.fromEntries(NODE_STAGES.flatMap(([node, display, stage]) => [
    [node, stage],
    [display, stage],
]));
export function getStageIdForAgent(agentName: string): StageId | null {
    const { base } = parseAgentRound(agentName);
    return AGENT_TO_STAGE[base] ?? null;
}
const STAGE_INDEX: Record<StageId, number> = {
    planning: 0,
    research: 1,
    synthesis: 2,
};
export function parseAgentRound(agentName: string): {
    base: string;
    round: number;
} {
    const name = agentName.trim();
    const m = /^(.+?)_r(\d+)$/.exec(name);
    if (m)
        return { base: m[1], round: parseInt(m[2], 10) };
    const display = /^(.+?)[（(]第(\d+)轮(?:补充)?[）)]$/.exec(name);
    if (display)
        return { base: display[1], round: parseInt(display[2], 10) };
    return { base: name, round: 0 };
}
export type ActivityStageId = 'requirements' | 'research' | 'route' | 'delivery';
const ACTIVITY_STAGE_BY_NODE: Record<string, ActivityStageId> = {
    scope_clarifier: 'requirements',
    understanding_agent: 'requirements',
    understanding_gate: 'requirements',
    requirements_preparer: 'requirements',
    research_plan_generator: 'requirements',
    minimum_delivery_draft_builder: 'requirements',
    intent_amendment_router: 'requirements',
    destination_geo_resolver: 'requirements',
    weather_context_builder: 'requirements',
    trip_summary_card_brief: 'requirements',
    planner: 'requirements',
    plan_gate: 'requirements',
    dispatcher: 'research',
    destination_researcher: 'research',
    transport_researcher: 'research',
    accommodation_researcher: 'research',
    itinerary_planner: 'route',
    delivery_projector: 'delivery',
    delivery_finalizer: 'delivery',
};
for (const [node, display, stage] of NODE_STAGES) {
    if (stage === 'planning')
        ACTIVITY_STAGE_BY_NODE[display] = 'requirements';
    else if (stage === 'synthesis')
        ACTIVITY_STAGE_BY_NODE[display] = 'delivery';
    else
        ACTIVITY_STAGE_BY_NODE[display] = node === 'itinerary_planner' || display === '行程规划' ? 'route' : 'research';
}
ACTIVITY_STAGE_BY_NODE['安排查询'] = 'research';
export function getActivityStageIdForAgent(agentName: string): ActivityStageId | null {
    return ACTIVITY_STAGE_BY_NODE[parseAgentRound(agentName).base] ?? null;
}
export const ACTIVITY_STAGE_TITLES: Record<ActivityStageId, string> = {
    requirements: '整理旅行需求',
    research: '查找旅行资料',
    route: '安排每天路线',
    delivery: '生成完整计划',
};
const ACTIVITY_STAGE_RANK: Record<ActivityStageId, number> = { requirements: 0, research: 1, route: 2, delivery: 3 };
function latestPopulatedActivityStage(steps: ThinkingStep[]): ActivityStageId | null {
    let current: ActivityStageId | null = null;
    for (const step of steps) {
        const stage = getActivityStageIdForAgent(step.agentName || '');
        if (!stage)
            continue;
        // 新补充轮次会重新整理需求；研究按串行推进，较晚到达的工具事件不应把已进入的路线/生成阶段拉回。
        if (stage === 'requirements') {
            current = stage;
            continue;
        }
        // 组合反馈的返研轮次确实回到了研究：过程区焦点跟着回到研究，
        // 重做结束后继续组合的步骤会把焦点再次推进到路线。
        if (stage === 'research' && parseAgentRound(step.agentName || '').round > 0) {
            current = stage;
            continue;
        }
        if (!current || ACTIVITY_STAGE_RANK[stage] > ACTIVITY_STAGE_RANK[current])
            current = stage;
    }
    return current;
}
/** 最新一次真正留下行动事件的阶段；不看 Run 状态，用于按阶段过滤过程。 */
export function latestActivityStageWithSteps(steps: ThinkingStep[]): ActivityStageId | null {
    return latestPopulatedActivityStage(steps);
}
/**
 * 当前最新活动阶段。门与等待确认归到需求整理，完成、合成与开始输出归到交付；
 * 其余情况按事件顺序取最近进入的阶段。
 */
export function latestActivityStageId(args: {
    steps: ThinkingStep[];
    isStreaming: boolean;
    isSynthesizing: boolean;
    answerStarted: boolean;
    runStatus?: string | null;
    gatePending?: boolean;
}): ActivityStageId | null {
    if (args.gatePending || args.runStatus === 'awaiting_input')
        return 'requirements';
    if (args.runStatus === 'completed' || args.isSynthesizing || args.answerStarted)
        return 'delivery';
    return latestPopulatedActivityStage(args.steps) ?? (args.isStreaming ? 'requirements' : null);
}
export function filterStepsForActivityStage(steps: ThinkingStep[], stage: ActivityStageId): ThinkingStep[] {
    return steps.filter(step => getActivityStageIdForAgent(step.agentName || '') === stage);
}
export function deriveActivityTitle(args: {
    steps: ThinkingStep[];
    isStreaming: boolean;
    isSynthesizing: boolean;
    answerStarted: boolean;
    runStatus?: string | null;
    gatePending?: boolean;
    interrupted?: boolean;
}): string {
    if (args.gatePending)
        return '等待确认研究方案';
    switch (args.runStatus) {
        case 'awaiting_input': return '等待确认研究方案';
        case 'cancel_requested': return '正在停止规划';
        case 'cancelled': return '旅行规划已取消';
        case 'interrupted': return '旅行规划已中断';
        case 'failed': return '旅行规划未完成';
        case 'completed': return '旅行规划已完成';
    }
    if (args.interrupted)
        return '旅行规划已中断';
    if (args.isSynthesizing || (args.isStreaming && args.answerStarted))
        return ACTIVITY_STAGE_TITLES.delivery;
    const current = latestPopulatedActivityStage(args.steps);
    if (current)
        return ACTIVITY_STAGE_TITLES[current];
    return args.isStreaming ? ACTIVITY_STAGE_TITLES.requirements : '旅行规划记录';
}
export interface StageView extends StageDef {
    status: StageStatus;
    startedAt?: Date;
    endedAt?: Date;
    elapsedMs?: number;
    stalled?: boolean;
}
export interface DerivedStages {
    stages: StageView[];
    hasDeepWorkflow: boolean;
}
export interface StageSignals {
    isStreaming: boolean;
    isSynthesizing: boolean;
    answerStarted: boolean;
    completed?: boolean;
}
export function deriveStages(steps: ThinkingStep[], signals: StageSignals): DerivedStages {
    const touched = new Set<StageId>();
    let lastStageIndex = -1;
    const timingByStage: Partial<Record<StageId, {
        startedAt: Date;
        endedAt?: Date;
    }>> = {};
    for (const step of steps) {
        const { base } = parseAgentRound(step.agentName || '');
        const stage = AGENT_TO_STAGE[base];
        if (!stage)
            continue;
        touched.add(stage);
        lastStageIndex = STAGE_INDEX[stage];
        const startedAt = step.timestamp instanceof Date ? step.timestamp : new Date(step.timestamp);
        const endedAt = step.endTime instanceof Date ? step.endTime : step.endTime ? new Date(step.endTime) : undefined;
        const current = timingByStage[stage];
        if (!current || startedAt < current.startedAt) {
            timingByStage[stage] = { startedAt, endedAt: endedAt ?? current?.endedAt };
        }
        else if (endedAt && (!current.endedAt || endedAt > current.endedAt)) {
            current.endedAt = endedAt;
        }
    }
    const { isStreaming, isSynthesizing, answerStarted } = signals;
    const synthesisActive = isSynthesizing || (isStreaming && answerStarted);
    const synthesisDone = signals.completed === true;
    let headIndex: number;
    let headActive: boolean;
    if (synthesisDone) {
        headIndex = STAGE_INDEX.synthesis;
        headActive = false;
    }
    else if (synthesisActive) {
        headIndex = STAGE_INDEX.synthesis;
        headActive = true;
    }
    else if (lastStageIndex >= 0) {
        headIndex = lastStageIndex;
        headActive = isStreaming;
    }
    else {
        headIndex = -1;
        headActive = false;
    }
    const now = Date.now();
    const stages: StageView[] = STAGE_DEFS.map((def) => {
        const idx = STAGE_INDEX[def.id];
        let status: StageStatus;
        if (headIndex < 0) {
            status = 'pending';
        }
        else if (idx < headIndex) {
            status = 'done';
        }
        else if (idx === headIndex) {
            status = headActive ? 'active' : synthesisDone ? 'done' : 'pending';
        }
        else {
            status = touched.has(def.id) ? 'done' : 'pending';
        }
        const timing = timingByStage[def.id];
        const elapsedMs = timing?.startedAt
            ? (timing.endedAt?.getTime() ?? (status === 'active' ? now : timing.startedAt.getTime())) -
                timing.startedAt.getTime()
            : undefined;
        return {
            ...def,
            status,
            startedAt: timing?.startedAt,
            endedAt: timing?.endedAt,
            elapsedMs,
            stalled: status === 'active' && elapsedMs !== undefined && elapsedMs > 60000,
        };
    });
    return { stages, hasDeepWorkflow: touched.size >= 2 };
}
