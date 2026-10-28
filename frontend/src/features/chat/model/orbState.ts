import { type OrbState } from "thinking-orbs";
import { getStageIdForAgent, parseAgentRound, type StageId } from "./agentStages";
const NODE_ORBS: ReadonlyArray<readonly [
    node: string,
    display: string,
    orb: OrbState
]> = [
    ['supervisor', '智能调度', 'working'],
    ['scope_clarifier', '需求确认', 'listening'],
    ['request_contract_normalizer', '需求合同', 'listening'],
    ['research_brief_builder', '调研简报', 'composing'],
    ['minimum_delivery_draft_builder', '行程骨架', 'shaping'],
    ['intent_amendment_router', '要求更新', 'listening'],
    ['destination_geo_resolver', '目的地定位', 'searching'],
    ['weather_context_builder', '天气事实', 'searching'],
    ['trip_summary_card_brief', '旅行摘要', 'composing'],
    ['planner', '任务规划', 'working'],
    ['plan_gate', '计划审批', 'breathing'],
    ['dispatcher', '任务分发', 'connecting'],
    ['destination_researcher', '目的地调研', 'searching'],
    ['transport_researcher', '交通查询', 'connecting'],
    ['accommodation_researcher', '住宿查询', 'searching'],
    ['itinerary_planner', '行程规划', 'weaving'],
    ['budget_estimate', '预算估算', 'solving'],
    ['delivery_projector', '交付内容', 'composing'],
    ['delivery_finalizer', '交付定稿', 'shaping'],
    ['fast_answer_agent', '快速回答', 'composing'],
];
const AGENT_TO_ORB: Record<string, OrbState> = Object.fromEntries(NODE_ORBS.flatMap(([node, display, orb]) => [
    [node, orb],
    [display, orb],
]));
const STAGE_FALLBACK_ORB: Record<StageId, OrbState> = {
    planning: 'working',
    research: 'searching',
    synthesis: 'composing',
};
export function orbStateForAgent(agentName: string): OrbState {
    const { base } = parseAgentRound(agentName);
    const direct = AGENT_TO_ORB[base];
    if (direct)
        return direct;
    const stage = getStageIdForAgent(base);
    return stage ? STAGE_FALLBACK_ORB[stage] : 'working';
}
export const ORB_LABELS: Record<OrbState, string> = {
    working: '正在处理',
    searching: '正在查找资料',
    solving: '正在核对与求解',
    listening: '正在理解你的需求',
    connecting: '正在衔接交通与任务',
    weaving: '正在编排行程',
    composing: '正在生成内容',
    breathing: '等待中',
    shaping: '正在整理交付',
};
