import { type ThinkingStep } from "../types/messages";
import { parseAgentRound, getStageIdForAgent } from "./agentStages";
export function publicProgressText(value: string | undefined): string {
    const text = value?.trim() || '';
    if (/\{\s*(?:["}\[]|$)|```|<think|"[\w_]+"\s*:|contract_version|research_packet_id/.test(text) || /^[{[]/.test(text))
        return '';
    return text.slice(0, 300);
}
export interface ResearchGroup {
    id: string;
    title: string;
    description: string;
    steps: ThinkingStep[];
    status: 'running' | 'completed' | 'stopped' | 'failed';
}
const WORKERS: Record<string, [
    string,
    string,
    string
]> = {
    destination_researcher: ['destination', '目的地调研', '景点、美食与当地体验'],
    transport_researcher: ['transport', '交通查询', '往返方式与沿途衔接'],
    accommodation_researcher: ['stay', '住宿查询', '住宿位置与出行便利性'],
    itinerary_planner: ['itinerary', '行程规划', '每日安排与游览节奏'],
};
for (const entry of Object.values(WORKERS))
    WORKERS[entry[1]] = entry;
export function researchGroups(steps: ThinkingStep[], live: boolean, interrupted: boolean): ResearchGroup[] {
    const groups = new Map<string, ResearchGroup>();
    for (const step of steps) {
        const { base } = parseAgentRound(step.agentName);
        const stage = getStageIdForAgent(base);
        const [id, title, description] = WORKERS[base] || (stage === 'synthesis'
            ? ['delivery', '整理行程', '汇总调研，形成旅行方案']
            : ['planning', '需求与调度', '理解偏好，准备调研任务']);
        const group = groups.get(id) || { id, title, description, steps: [], status: 'running' as const };
        group.steps.push(step);
        groups.set(id, group);
    }
    return [...groups.values()].map((group) => {
        const last = group.steps[group.steps.length - 1];
        const activeTool = group.steps.some(s => s.isToolCall && s.toolStatus === 'running');
        const lifecycle = [...group.steps].reverse().find(s => s.progressStatus);
        const passed = group.id === 'planning' && [...groups.keys()].some(id => id !== 'planning');
        const done = !activeTool && (passed || lifecycle?.progressStatus === 'completed' || (!lifecycle && Boolean(last.endTime)));
        const status = lifecycle?.progressStatus === 'failed' ? 'failed' : interrupted && !done ? 'stopped' : done || !live && !interrupted ? 'completed' : 'running';
        return { ...group, status };
    });
}
