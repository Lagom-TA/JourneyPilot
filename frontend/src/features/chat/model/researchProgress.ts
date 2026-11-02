import { type ThinkingStep } from "../types/messages";
import { parseAgentRound, getStageIdForAgent } from "./agentStages";
export function publicProgressText(value: string | undefined): string {
    const text = value?.trim() || '';
    if (/\{\s*(?:["}[]|$)|```|<think|"[\w_]+"\s*:|research_packet_id/.test(text) || /^[{[]/.test(text))
        return '';
    return text.slice(0, 300);
}
export interface ResearchGroup {
    id: string;
    title: string;
    steps: ThinkingStep[];
    status: 'running' | 'completed' | 'stopped' | 'failed';
}
const WORKERS: Record<string, [
    string,
    string
]> = {
    destination_researcher: ['destination', '目的地调研'],
    transport_researcher: ['transport', '交通查询'],
    accommodation_researcher: ['stay', '住宿查询'],
    itinerary_planner: ['itinerary', '行程规划'],
};
for (const entry of Object.values(WORKERS))
    WORKERS[entry[1]] = entry;
export function researchGroups(steps: ThinkingStep[], live: boolean, interrupted: boolean): ResearchGroup[] {
    const groups = new Map<string, ResearchGroup>();
    for (const step of steps) {
        const { base } = parseAgentRound(step.agentName);
        const stage = getStageIdForAgent(base);
        const [id, title] = WORKERS[base] || (stage === 'synthesis'
            ? ['delivery', '整理行程']
            : ['planning', '整理旅行需求']);
        const group = groups.get(id) || { id, title, steps: [], status: 'running' as const };
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
