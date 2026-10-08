/**
 * 后端工作流节点 → 思考球（thinking-orbs）动画状态。
 *
 * 球是「agent 此刻在做什么」的唯一活动指示：登机牌票根、思维链标题、折叠态的登记条
 * 都读同一个派生值，所以「还在忙」在整屏上只有一种节奏，而不是七处各转各的圈。
 *
 * 映射按节点**语义**给，不按阶段机械分：交通衔接是 `connecting`，编排每日行程是
 * `weaving`，所有门（gate）都是 `solving`，交付投影是 `composing`，定稿是 `shaping`。
 * 表里两个键（内部名 / 显示名）从同一行生成，理由与 `agentStages.ts` 的 `NODE_STAGES`
 * 逐字相同：线上发的是显示名，数据库里翻回来的历史会话可能还是内部名。
 *
 * 没登记的节点退回它所属责任阶段的默认球；连阶段都没有的退回 `working`。
 */
import type { OrbState } from 'thinking-orbs';
import type { ThinkingStep } from '../types/chat';
import { getStageIdForAgent, parseAgentRound, type StageId } from './agentStages';

const NODE_ORBS: ReadonlyArray<readonly [node: string, display: string, orb: OrbState]> = [
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
  ['candidate_gate', '候选校验', 'solving'],
  ['artifact_gate', '产物校验', 'solving'],
  ['intent_fidelity_gate', '意图校验', 'solving'],
  ['delivery_quality_gate', '交付校验', 'solving'],
  ['budget_estimate', '预算估算', 'solving'],
  ['delivery_projector', '交付内容', 'composing'],
  ['delivery_finalizer', '交付定稿', 'shaping'],
  ['fast_answer_agent', '快速回答', 'composing'],
];

const AGENT_TO_ORB: Record<string, OrbState> = Object.fromEntries(
  NODE_ORBS.flatMap(([node, display, orb]) => [
    [node, orb],
    [display, orb],
  ]),
);

const STAGE_FALLBACK_ORB: Record<StageId, OrbState> = {
  planning: 'working',
  research: 'searching',
  verify: 'solving',
  review: 'solving',
  synthesis: 'composing',
};

/** 单个 agent 名 → 球状态；补研轮次后缀（`_rN` / `（第N轮补充）`）先剥掉。 */
export function orbStateForAgent(agentName: string): OrbState {
  const { base } = parseAgentRound(agentName);
  const direct = AGENT_TO_ORB[base];
  if (direct) return direct;
  const stage = getStageIdForAgent(base);
  return stage ? STAGE_FALLBACK_ORB[stage] : 'working';
}

export interface OrbSignals {
  isStreaming: boolean;
  isSynthesizing: boolean;
  /** 最终回答是否已开始产出（synthesizer chat_chunk 到达） */
  answerStarted: boolean;
  /** 运行挂起等用户决定（计划审批门 / 补充信息） */
  awaitingInput?: boolean;
}

/**
 * 从思考步与运行信号派生此刻的球状态。
 *
 * 优先级：等用户 > 正在写最终回答 > 最近一个有名字的步 > 刚开始（还没有步）> 静止。
 * 「最近一步」按数组顺序取最后一个有 `agentName` 的步，不看它是否已结束：一步结束、
 * 下一步还没到的空当里，球停在上一步的动作上比跳回通用态更连贯。
 */
export function deriveOrbState(steps: ThinkingStep[], signals: OrbSignals): OrbState {
  if (signals.awaitingInput) return 'breathing';
  if (signals.isSynthesizing || (signals.isStreaming && signals.answerStarted)) return 'composing';
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    const name = steps[index]?.agentName;
    if (name) return orbStateForAgent(name);
  }
  return signals.isStreaming ? 'listening' : 'breathing';
}

/** 球的可读名字：`aria-label` 与任何想在球旁边写一句话的地方，读这一份。 */
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
