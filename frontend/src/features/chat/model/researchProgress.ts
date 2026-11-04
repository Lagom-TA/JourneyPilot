import { type ThinkingStep } from "../types/messages";
import {
    ACTIVITY_STAGE_TITLES,
    getActivityStageIdForAgent,
    parseAgentRound,
    type ActivityStageId,
    type ActivityStageStatus,
} from "./agentStages";
export function publicProgressText(value: string | undefined): string {
    const text = value?.trim() || '';
    if (/\{\s*(?:["}[]|$)|```|<think|"[\w_]+"\s*:|research_packet_id/.test(text) || /^[{[]/.test(text))
        return '';
    return text.slice(0, 300);
}
/** 服务端已整句校验的公开工作说明；前端只做长度兜底，不再二次形态过滤。 */
export function isWorkExplanationStep(step: ThinkingStep): boolean {
    return step.kind === 'work_explanation';
}
export function workExplanationText(value: string | undefined): string {
    return (value?.trim() || '').slice(0, 160);
}
export interface ResearchGroup {
    id: string;
    title: string;
    stage: ActivityStageId;
    steps: ThinkingStep[];
    status: 'running' | 'completed' | 'stopped' | 'failed';
}
const WORKERS: Record<string, [
    string,
    string
]> = {
    // dispatcher 只宣告并行调研开始；它属于资料阶段，不能落回需求整理组。
    dispatcher: ['dispatch', '安排查询'],
    destination_researcher: ['destination', '目的地调研'],
    transport_researcher: ['transport', '交通查询'],
    accommodation_researcher: ['stay', '住宿查询'],
    itinerary_planner: ['itinerary', '行程规划'],
};
for (const entry of Object.values(WORKERS))
    WORKERS[entry[1]] = entry;
/**
 * 按行动归属分组成员卡片。`stageStatus` 由工作台的四阶段投影传入：
 * 阶段不是 active 时，任何组都不得再显示“进行中”；阶段 done 时把遗留的
 * running 收口为 completed，failed/stopped 则如实保留。
 */
export function researchGroups(
    steps: ThinkingStep[],
    live: boolean,
    interrupted: boolean,
    stageStatus?: ActivityStageStatus,
): ResearchGroup[] {
    const groups = new Map<string, ResearchGroup>();
    for (const step of steps) {
        const { base } = parseAgentRound(step.agentName);
        const activityStage = getActivityStageIdForAgent(base);
        const worker = WORKERS[base];
        // 需求整理的兜底组沿用旧的 planning id，普通聊天的 passed 启发式才继续生效；
        // stage 字段仍用于工作台按四阶段过滤。
        const id = worker?.[0] ?? (activityStage === 'requirements' ? 'planning' : activityStage ?? 'planning');
        const title = worker?.[1] ?? (activityStage ? ACTIVITY_STAGE_TITLES[activityStage] : '整理旅行需求');
        const stage = activityStage ?? 'requirements';
        const group = groups.get(id) || { id, title, stage, steps: [], status: 'running' as const };
        group.steps.push(step);
        groups.set(id, group);
    }
    return [...groups.values()].map((group) => {
        // 公开说明不是生命周期步骤：它不能把“最后一步有 endTime”误判成组已完成。
        const last = [...group.steps].reverse().find(step => !isWorkExplanationStep(step));
        const activeTool = group.steps.some(s => s.isToolCall && s.toolStatus === 'running');
        const lifecycle = [...group.steps].reverse().find(s => s.progressStatus);
        // 普通聊天没有阶段投影，保留“规划组后面出现其他组即已结束”的旧启发式；
        // 工作台按阶段过滤后不能再用其他阶段是否存在来判断本阶段。
        // dispatcher 只是一次性宣告，后续 worker 出现即视为已结束，不会永远转圈。
        const sameStageOther = [...groups.values()].some(other => other.id !== group.id && other.stage === group.stage);
        const passed = (stageStatus === undefined
            && group.id === 'planning'
            && [...groups.keys()].some(id => id !== 'planning'))
            || (group.id === 'dispatch' && sameStageOther);
        const done = !activeTool && (passed || lifecycle?.progressStatus === 'completed' || (!lifecycle && Boolean(last?.endTime)));
        let status: ResearchGroup['status'];
        if (lifecycle?.progressStatus === 'failed') {
            status = 'failed';
        }
        else if (stageStatus === 'failed') {
            status = done ? 'completed' : 'failed';
        }
        else if (stageStatus === 'stopped') {
            status = done ? 'completed' : 'stopped';
        }
        else if (stageStatus === 'done') {
            status = 'completed';
        }
        else if (stageStatus === 'pending') {
            status = done ? 'completed' : 'stopped';
        }
        else if (stageStatus === 'active') {
            status = done ? 'completed' : live ? 'running' : 'stopped';
        }
        else {
            status = interrupted && !done ? 'stopped' : done || !live && !interrupted ? 'completed' : 'running';
        }
        return { ...group, status };
    });
}
