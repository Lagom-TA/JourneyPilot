import { type ThinkingStep } from "../types/messages";
export type StageId = 'planning' | 'research' | 'synthesis';
export type StageStatus = 'pending' | 'active' | 'done';
export interface StageDef {
    id: StageId;
    label: string;
    responsibility: string;
}
export const STAGE_DEFS: StageDef[] = [
    { id: 'planning', label: '规划', responsibility: '理解你的需求，拆解调研计划并分派任务' },
    { id: 'research', label: '调研', responsibility: '并行调研目的地、交通、住宿，编排每日行程' },
    { id: 'synthesis', label: '交付', responsibility: '生成统一投影并原子保存正式旅行结果' },
];
const NODE_STAGES: ReadonlyArray<readonly [
    node: string,
    display: string,
    stage: StageId
]> = [
    ['supervisor', '智能调度', 'planning'],
    ['scope_clarifier', '需求确认', 'planning'],
    ['request_contract_normalizer', '需求合同', 'planning'],
    ['research_brief_builder', '调研简报', 'planning'],
    ['minimum_delivery_draft_builder', '行程骨架', 'planning'],
    ['intent_amendment_router', '要求更新', 'planning'],
    ['destination_geo_resolver', '目的地定位', 'planning'],
    ['weather_context_builder', '天气事实', 'planning'],
    ['trip_summary_card_brief', '旅行摘要', 'planning'],
    ['planner', '任务规划', 'planning'],
    ['plan_gate', '计划审批', 'planning'],
    ['dispatcher', '任务分发', 'planning'],
    ['destination_researcher', '目的地调研', 'research'],
    ['transport_researcher', '交通查询', 'research'],
    ['accommodation_researcher', '住宿查询', 'research'],
    ['itinerary_planner', '行程规划', 'research'],
    ['budget_estimate', '预算估算', 'synthesis'],
    ['delivery_projector', '交付内容', 'synthesis'],
    ['delivery_finalizer', '交付定稿', 'synthesis'],
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
    const m = /^(.+?)_r(\d+)$/.exec(agentName);
    if (m)
        return { base: m[1], round: parseInt(m[2], 10) };
    const display = /^(.+?)（第(\d+)轮补充）$/.exec(agentName);
    if (display)
        return { base: display[1], round: parseInt(display[2], 10) };
    return { base: agentName, round: 0 };
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
    const synthesisDone = !isStreaming && answerStarted;
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
            status = headActive ? 'active' : 'done';
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
