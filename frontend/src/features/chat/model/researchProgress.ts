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
/** 公开工作说明由服务端按整句校验；前端显示时只截断长度，不重复校验文本形式。 */
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
    // “安排查询”事件只表示并行调研已开始，归入资料阶段，不归入需求整理组。
    dispatcher: ['dispatch', '安排查询'],
    destination_researcher: ['destination', '目的地调研'],
    transport_researcher: ['transport', '交通查询'],
    accommodation_researcher: ['stay', '住宿查询'],
    itinerary_planner: ['itinerary', '行程规划'],
};
for (const entry of Object.values(WORKERS))
    WORKERS[entry[1]] = entry;
/**
 * 按行动归属分组成员卡片。`stageStatus` 由工作台的四阶段状态传入：
 * 只有 active 阶段的未完成组可显示为 running；done 阶段中，最后一条进度状态为 failed 的组保留 failed，其余组显示为 completed。
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
        // 需求整理组使用 planning 作为分组 ID。未传入阶段状态时，普通聊天依据后续分组判断是否结束；
        // 工作台仍按 stage 过滤。
        const id = worker?.[0] ?? (activityStage === 'requirements' ? 'planning' : activityStage ?? 'planning');
        const title = worker?.[1] ?? (activityStage ? ACTIVITY_STAGE_TITLES[activityStage] : '整理旅行需求');
        const stage = activityStage ?? 'requirements';
        const group = groups.get(id) || { id, title, stage, steps: [], status: 'running' as const };
        group.steps.push(step);
        groups.set(id, group);
    }
    return [...groups.values()].map((group) => {
        // 公开工作说明不代表调研步骤已完成；判断组完成时间时跳过这类说明。
        const last = [...group.steps].reverse().find(step => !isWorkExplanationStep(step));
        const activeTool = group.steps.some(s => s.isToolCall && s.toolStatus === 'running');
        const lifecycle = [...group.steps].reverse().find(s => s.progressStatus);
        // 普通聊天未传入阶段状态时，规划组后出现其他分组即视为已结束；工作台按阶段状态判断。
        // “安排查询”只表示并行调研已开始，同阶段的其他行动出现后，该组即结束。
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
