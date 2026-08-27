/**
 * Agent Timeline / 责任视图：把固定 LangGraph 工作流的节点责任边界，翻译成用户能理解的
 * 5 个责任阶段（规划 → 调研 → 校验 → 评审 → 合成）。
 *
 * - 数据走 SSE 结构化事件字段（thinkingSteps[].agentName，= 后端 agent_name），不解析自然语言。
 * - 5 阶段写死、始终全列，体现「固定责任边界」——不暗示动态生成任意 Agent 团队（JP-03-03 §8）。
 * - 只给阶段状态 + 职责 + 必要的补研原因；不展示模型内部思考 / token / 延迟 / 工具全量
 *   （那些留在现有 chat 原始 trace，本视图是另一个 altitude）。
 *
 * 阶段映射对齐后端 `src/travel_agent/utils/display_names.py` 与 LangGraph 图结构
 * （workflows/travel_planning.py）；阶段职责文案对齐 JP-02-05 工作流职责语义。
 */
import type { ThinkingStep } from '../types/chat';

export type StageId = 'planning' | 'research' | 'verify' | 'review' | 'synthesis';
export type StageStatus = 'pending' | 'active' | 'done';

export interface StageDef {
  id: StageId;
  label: string;
  /** 用户可读的职责一句话 */
  responsibility: string;
}

/** 固定 5 阶段（顺序即工作流责任边界，始终全列） */
export const STAGE_DEFS: StageDef[] = [
  { id: 'planning', label: '规划', responsibility: '理解你的需求，拆解调研计划并分派任务' },
  { id: 'research', label: '调研', responsibility: '并行调研目的地、交通、住宿，编排每日行程' },
  { id: 'verify', label: '准入', responsibility: '校验候选的约束、来源、天气与现实身份' },
  { id: 'review', label: '成行', responsibility: '验证相邻交通、行程拓扑与完整交付质量' },
  { id: 'synthesis', label: '交付', responsibility: '生成统一投影并原子保存正式旅行结果' },
];

/**
 * 工作流节点 → 责任阶段，一个节点一行。
 *
 * 一行同时给出内部名和中文显示名，`AGENT_TO_STAGE` 从这里生成两个键 —— 因为线上
 * `agent_name` 发的是**显示名**（`api/routes/chat_stream_handlers.py:202/218/244`），
 * 而数据库里翻回来的历史会话可能还存着更早那版的内部名，两种都要认得。
 *
 * 写成一行两名是为了让「只改一半」这件事不可能发生：以前两半是分开的两段字面量，
 * 结果中文那半漂到了后端从来没发过的名字上（`候选准入` / `交付质量` / `交付投影` /
 * `原子交付` 四个键从未在 `display_names.py` 里存在过，`git log -S` 查不到任何提交），
 * 于是「准入」这一阶段在时间线上永远亮不起来，而没有任何测试会红。
 *
 * `agentStages.test.ts` 拿这张表跟后端 `utils/display_names.py` 双向对差集。
 * 后端那张表覆盖图上每个节点由 INV-NODE-001 保证，所以这两条接起来就是
 * 「图上每个节点都进得了时间线」。
 */
const NODE_STAGES: ReadonlyArray<readonly [node: string, display: string, stage: StageId]> = [
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
  ['candidate_gate', '候选校验', 'verify'],
  ['artifact_gate', '产物校验', 'review'],
  ['intent_fidelity_gate', '意图校验', 'review'],
  ['delivery_quality_gate', '交付校验', 'review'],
  ['budget_estimate', '预算估算', 'synthesis'],
  ['delivery_projector', '交付内容', 'synthesis'],
  ['delivery_finalizer', '交付定稿', 'synthesis'],
];

/**
 * 时间线**不收**的节点，逐个列出理由 —— 留空集会让 `agentStages.test.ts` 的差集
 * 断言把「漏了一个」和「有意不收」混为一谈。
 *
 * - `fast_answer_agent`：快答是单步问答，不构成深度工作流（见文件头 JP-03-03 §8）。
 */
export const NON_WORKFLOW_NODES: ReadonlySet<string> = new Set(['fast_answer_agent']);

/** 后端 agent_name → 责任阶段。内部名与显示名都收，两个键必然同阶段。 */
export const AGENT_TO_STAGE: Record<string, StageId> = Object.fromEntries(
  NODE_STAGES.flatMap(([node, display, stage]) => [
    [node, stage],
    [display, stage],
  ]),
);

export function getStageIdForAgent(agentName: string): StageId | null {
  const { base } = parseAgentRound(agentName);
  return AGENT_TO_STAGE[base] ?? null;
}

const STAGE_INDEX: Record<StageId, number> = {
  planning: 0,
  research: 1,
  verify: 2,
  review: 3,
  synthesis: 4,
};

/** 去掉补研轮次后缀 `_rN`（对齐 display_names.py 的 `_rN` 约定），返回基础 agent 名 + 轮次 */
function parseAgentRound(agentName: string): { base: string; round: number } {
  const m = /^(.+?)_r(\d+)$/.exec(agentName);
  if (m) return { base: m[1], round: parseInt(m[2], 10) };
  const display = /^(.+?)（第(\d+)轮补充）$/.exec(agentName);
  if (display) return { base: display[1], round: parseInt(display[2], 10) };
  return { base: agentName, round: 0 };
}

export interface StageView extends StageDef {
  status: StageStatus;
  startedAt?: Date;
  endedAt?: Date;
  elapsedMs?: number;
  stalled?: boolean;
  /** 该阶段触发过的补研轮次（>0 时显示「补充调研 · 第N轮」） */
  refinementRound?: number;
  refinementReason?: string;
}

export interface DerivedStages {
  stages: StageView[];
  /** 是否构成深度工作流（≥2 阶段被触达）；fast 单步问答 → false，不渲染 */
  hasDeepWorkflow: boolean;
}

export interface StageSignals {
  isStreaming: boolean;
  isSynthesizing: boolean;
  /** 最终回答是否已开始产出（synthesizer chat_chunk 到达）——用于推导合成阶段状态 */
  answerStarted: boolean;
}

/**
 * 从 thinkingSteps 派生 5 阶段责任视图。
 *
 * 合成阶段特殊处理：synthesizer 产出的是最终回答（chat_chunk），不产 thinkingStep，
 * 因此用 isSynthesizing / answerStarted 推导其状态，而非靠 step 命中。
 */
export function deriveStages(steps: ThinkingStep[], signals: StageSignals): DerivedStages {
  const touched = new Set<StageId>();
  let lastStageIndex = -1;
  let maxRound = 0;
  const roundByStage: Partial<Record<StageId, number>> = {};
  const timingByStage: Partial<Record<StageId, { startedAt: Date; endedAt?: Date }>> = {};

  for (const step of steps) {
    const { base, round } = parseAgentRound(step.agentName || '');
    const stage = AGENT_TO_STAGE[base];
    if (!stage) continue;
    touched.add(stage);
    lastStageIndex = STAGE_INDEX[stage];
    const startedAt = step.timestamp instanceof Date ? step.timestamp : new Date(step.timestamp);
    const endedAt = step.endTime instanceof Date ? step.endTime : step.endTime ? new Date(step.endTime) : undefined;
    const current = timingByStage[stage];
    if (!current || startedAt < current.startedAt) {
      timingByStage[stage] = { startedAt, endedAt: endedAt ?? current?.endedAt };
    } else if (endedAt && (!current.endedAt || endedAt > current.endedAt)) {
      current.endedAt = endedAt;
    }
    if (round > 0) {
      maxRound = Math.max(maxRound, round);
      roundByStage[stage] = Math.max(roundByStage[stage] ?? 0, round);
    }
  }

  const { isStreaming, isSynthesizing, answerStarted } = signals;

  // 合成阶段状态：synthesizing / 回答已开始流式 → active；流式结束且有回答 → done
  const synthesisActive = isSynthesizing || (isStreaming && answerStarted);
  const synthesisDone = !isStreaming && answerStarted;

  // 计算「当前头部」阶段与其是否 active
  let headIndex: number;
  let headActive: boolean;
  if (synthesisDone) {
    headIndex = STAGE_INDEX.synthesis;
    headActive = false; // 全部完成
  } else if (synthesisActive) {
    headIndex = STAGE_INDEX.synthesis;
    headActive = true; // 合成进行中
  } else if (lastStageIndex >= 0) {
    headIndex = lastStageIndex;
    headActive = isStreaming;
  } else {
    headIndex = -1;
    headActive = false;
  }

  const now = Date.now();
  const stages: StageView[] = STAGE_DEFS.map((def) => {
    const idx = STAGE_INDEX[def.id];
    let status: StageStatus;
    if (headIndex < 0) {
      status = 'pending';
    } else if (idx < headIndex) {
      status = 'done';
    } else if (idx === headIndex) {
      status = headActive ? 'active' : 'done';
    } else {
      // 头部之后：补研可能回访过更晚阶段 → 触达过则 done，否则 pending
      status = touched.has(def.id) ? 'done' : 'pending';
    }

    const timing = timingByStage[def.id];
    const elapsedMs =
      timing?.startedAt
        ? (timing.endedAt?.getTime() ?? (status === 'active' ? now : timing.startedAt.getTime())) -
          timing.startedAt.getTime()
        : undefined;
    const baseView: StageView = {
      ...def,
      status,
      startedAt: timing?.startedAt,
      endedAt: timing?.endedAt,
      elapsedMs,
      stalled: status === 'active' && elapsedMs !== undefined && elapsedMs > 60_000,
    };
    const refinementRound = roundByStage[def.id];
    if (refinementRound) {
      return {
        ...baseView,
        refinementRound,
        refinementReason: '部分信息时效或证据待补充，已自动追加一轮调研核实',
      };
    }
    return baseView;
  });

  // 确定性 Gate 触发 Worker 定向补研时，在成行阶段显示轮次摘要。
  if (maxRound > 0) {
    const review = stages[STAGE_INDEX.review];
    if (!review.refinementRound) {
      review.refinementRound = maxRound;
      review.refinementReason = '校验发现需补充的信息，已触发补充调研';
    }
  }

  return { stages, hasDeepWorkflow: touched.size >= 2 };
}
