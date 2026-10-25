import { type RunCostLive, type CostGroupBreakdown, type RunCostSummary, type ToolContextSaving } from "../types/cost";
import { formatCost, formatCount, formatDuration, formatPercent, formatTokens, formatTokensCompact, READOUT_PLACEHOLDER } from "../../../lib/format";
import { formatAgentLabel } from "../../travel/model/travelProgress";
export type LedgerField = keyof RunCostSummary;
export const ON_SCREEN_LEDGER_FIELDS = [
    'call_count',
    'total_tokens',
    'total_input_tokens',
    'total_output_tokens',
    'total_cached_input_tokens',
    'total_cache_write_input_tokens',
    'total_reasoning_output_tokens',
    'total_cost_usd',
    'estimated_ratio',
    'estimated_call_count',
    'cost_coverage_ratio',
    'error_call_count',
    'record_failed',
    'by_node',
    'tool_context_saving',
] as const satisfies readonly LedgerField[];
export const UNIT_LEDGER_FIELDS: Record<string, string> = {
    currency: '作为 total_cost_usd 的符号印在同一个读数里（$ / ¥ / €），不占自己的格。',
};
export const OFF_SCREEN_LEDGER_FIELDS: Record<string, string> = {
    pending_call_count: '待落库数量通过 record_failed 的完整性提示展示。',
    spool_write_failed: '持久捕获失败通过 record_failed 的完整性提示展示。',
    capture_complete: '捕获完整性参与完整费用判断。',
    total_request_input_tokens_estimate: '请求大小估算用于内部诊断；账单用量由模型 usage 决定。',
    total_tool_schema_tokens_estimate: '逐次请求的工具 schema 估算用于优化分析，不代表已计费 Token。',
    logical_call_count: '内部用于将重试归入同一次逻辑调用；模型调用数包含每次实际尝试。',
    token_usage_complete: '计量是否完整由缺失用量提示表达。',
    cost_complete: '成本是否完整由部分成本提示表达。',
    partial_usage_call_count: '用于诊断部分用量，与计量完整性提示共用。',
    missing_usage_call_count: '用于诊断缺失用量，与计量完整性提示共用。',
    cache_read_usage_complete: '缓存细分缺失由计量提示表达。',
    cache_write_usage_complete: '缓存细分缺失由计量提示表达。',
    reasoning_usage_complete: '推理细分缺失由计量提示表达。',
    cache_hit_ratio: '内部按 Token 加权的缓存命中率用于下一轮优化分析。',
    run_id: '内部键。2026-07-24 的用户裁决（用户前台信息边界 §5）明写「run_id 不得出现在用户文本、' +
        '卡片、弹窗、错误、历史条目或用户可见 SSE 模型中」—— 这一条不在「把成本台账接回来」的' +
        '推翻范围内，所以它只用来对齐 run（哪份台账属于哪条消息），一个字都不印。',
    wall_ms: '**已经在屏幕上了** —— 思维链折叠头的定格总耗时就是它（`MessageBubble` 把它当 ' +
        '`serverTotalMs` 传下去）。同一个数在两处各印一遍，读者第一反应是「这两个为什么不一样」。' +
        '一个数一个家。',
    total_latency_ms: '逐次调用延迟的**求和**，与 wall_ms 回答同一个问题（这轮花了多久）而口径不同：' +
        '并发跑的两次调用在它里面加两遍，在 wall_ms 里只占一段。两个都印等于请读者' +
        '自己去猜哪个是真的。per-node 的那一份仍在「按环节」行里 —— 那里它回答的是' +
        '「哪个环节慢」，不是「这轮多久」。',
    by_agent: '与 by_node **同一份数据**：`run_control.py:513-514` 的节点包装器把 `current_agent` ' +
        '设成节点名本身，所以除了外层那个 `workflow` 兜底，两个分组逐行相同。印两份分解就是' +
        '「同一份数据有两个分组方式」的呈现版。上屏的那一份取 by_node —— 合同 §7.1 说的是「per-node 成本分解」。',
    bottleneck_by_cost: '后端从 by_node 取的成本 top3。by_node 已经按成本降序上屏并画了条形，' +
        '最贵的那个环节就在第一行 —— 再开一段「瓶颈 Top 3」是把同一个事实说第二遍。',
    bottleneck_by_latency: '同上，延迟维度的 top3。按环节那几行行尾已经带各自的耗时。',
    priced_call_count: '与 cost_coverage_ratio 同一个事实（有价调用占比）。比率上屏，因为它直接回答' +
        '「这个成本数覆盖了多少」；再印一个分子，读者得自己做除法。',
    unpriced_call_count: '同上，是 call_count − priced_call_count 的另一种说法。',
};
export type CostLedgerSource = 'settled' | 'live';
export interface CostLedgerTile {
    field: LedgerField;
    label: string;
    value: number | null;
    display: string;
    estimated: boolean;
    accent: boolean;
}
export interface CostLedgerRow {
    field: LedgerField;
    label: string;
    display: string;
}
export interface CostLedgerBreakdownRow {
    key: string;
    label: string;
    tokens: string;
    cost: string;
    calls: string;
    latency: string;
    barShare: number;
}
export interface CostLedgerBreakdown {
    field: LedgerField;
    rows: CostLedgerBreakdownRow[];
    rest: number;
}
export interface CostLedgerSaving {
    field: LedgerField;
    ratio: string;
    savedTokens: string;
    modeLabel: string;
    exposure: string;
}
export type CostLedgerNoticeTone = 'warning' | 'neutral';
export interface CostLedgerNotice {
    field: LedgerField | 'currency';
    tone: CostLedgerNoticeTone;
    text: string;
}
export interface CostLedgerView {
    source: CostLedgerSource;
    tiles: CostLedgerTile[];
    rows: CostLedgerRow[];
    breakdown: CostLedgerBreakdown | null;
    saving: CostLedgerSaving | null;
    notices: CostLedgerNotice[];
    estimated: boolean;
    activeLabel: string | null;
}
const BREAKDOWN_ROW_LIMIT = 5;
function nodeLabel(row: CostGroupBreakdown): string {
    const key = row.node ?? row.agent ?? '';
    if (!key || key === 'unknown')
        return '未归因调用';
    if (key === 'workflow')
        return '图边界调用';
    return formatAgentLabel(key).label;
}
function breakdownKey(row: CostGroupBreakdown, index: number): string {
    return `${row.node ?? row.agent ?? 'unknown'}#${index}`;
}
function barShares(rows: CostGroupBreakdown[]): number[] {
    const max = rows.reduce((peak, row) => Math.max(peak, row.total_tokens ?? 0), 0);
    if (max <= 0)
        return rows.map(() => 0);
    return rows.map((row) => (row.total_tokens ?? 0) / max);
}
function savingModeLabel(mode: ToolContextSaving['mode']): string {
    switch (mode) {
        case 'deferred':
            return '按需加载';
        case 'mixed':
            return '混合加载';
        default:
            return '全部加载';
    }
}
function projectSettled(summary: RunCostSummary): CostLedgerView {
    const estimated = summary.estimated_call_count > 0;
    const costKnown = summary.total_cost_usd != null;
    const tiles: CostLedgerTile[] = [
        {
            field: 'call_count',
            label: '模型调用',
            value: summary.call_count,
            display: formatCount(summary.call_count),
            estimated: false,
            accent: false,
        },
        {
            field: 'total_tokens',
            label: 'Token',
            value: summary.total_tokens,
            display: formatTokensCompact(summary.total_tokens),
            estimated,
            accent: false,
        },
        {
            field: 'total_cost_usd',
            label: '成本',
            value: summary.total_cost_usd,
            display: formatCost(summary.total_cost_usd, summary.currency),
            estimated: estimated && summary.total_cost_usd != null,
            accent: true,
        },
        {
            field: 'estimated_ratio',
            label: '估算占比',
            value: summary.estimated_ratio,
            display: formatPercent(summary.estimated_ratio),
            estimated: false,
            accent: false,
        },
    ];
    const rows: CostLedgerRow[] = [
        {
            field: 'total_input_tokens',
            label: '输入',
            display: `${formatTokens(summary.total_input_tokens)} tok`,
        },
        {
            field: 'total_output_tokens',
            label: '输出',
            display: `${formatTokens(summary.total_output_tokens)} tok`,
        },
        {
            field: 'total_cached_input_tokens',
            label: '缓存命中',
            display: `${formatTokens(summary.total_cached_input_tokens)} tok`,
        },
        {
            field: 'total_cache_write_input_tokens',
            label: '缓存写入',
            display: `${formatTokens(summary.total_cache_write_input_tokens)} tok`,
        },
        {
            field: 'total_reasoning_output_tokens',
            label: '推理输出',
            display: `${formatTokens(summary.total_reasoning_output_tokens)} tok`,
        },
        {
            field: 'cost_coverage_ratio',
            label: '价格覆盖',
            display: formatPercent(summary.cost_coverage_ratio),
        },
        {
            field: 'estimated_call_count',
            label: '估算调用',
            display: `${formatCount(summary.estimated_call_count)} / ${formatCount(summary.call_count)}`,
        },
        {
            field: 'error_call_count',
            label: '出错调用',
            display: formatCount(summary.error_call_count),
        },
    ];
    const nodes = summary.by_node.slice(0, BREAKDOWN_ROW_LIMIT);
    const shares = barShares(nodes);
    const breakdown: CostLedgerBreakdown | null = summary.by_node.length
        ? {
            field: 'by_node',
            rows: nodes.map((row, index) => ({
                key: breakdownKey(row, index),
                label: nodeLabel(row),
                tokens: `${formatTokens(row.total_tokens)} tok`,
                cost: formatCost(row.cost_usd, summary.currency),
                calls: formatCount(row.call_count),
                latency: formatDuration(row.latency_ms),
                barShare: shares[index],
            })),
            rest: summary.by_node.length - nodes.length,
        }
        : null;
    const saving = summary.tool_context_saving
        ? {
            field: 'tool_context_saving' as LedgerField,
            ratio: formatPercent(summary.tool_context_saving.tool_context_saving),
            savedTokens: `${formatTokens(summary.tool_context_saving.schema_tokens_saved)} tok`,
            modeLabel: savingModeLabel(summary.tool_context_saving.mode),
            exposure: `${formatCount(summary.tool_context_saving.tools_exposed_initial)}/${formatCount(summary.tool_context_saving.tools_full_baseline)}`,
        }
        : null;
    const notices: CostLedgerNotice[] = [];
    if (summary.record_failed || summary.capture_complete === false) {
        notices.push({
            field: 'record_failed',
            tone: 'warning',
            text: summary.spool_write_failed || (summary.capture_complete === false && !summary.pending_call_count)
                ? '用量持久记录出现故障，账单可能不完整。'
                : `有 ${formatCount(summary.record_failed)} 条调用的成本待落库，账单尚不完整。`,
        });
    }
    if (!costKnown && summary.call_count > 0) {
        notices.push({
            field: 'currency',
            tone: 'warning',
            text: '用量或计价信息不足，暂时无法计算本轮成本。',
        });
    }
    if (summary.token_usage_complete === false || summary.cost_complete === false) {
        notices.push({ field: 'token_usage_complete', tone: 'warning',
            text: '部分调用缺少完整计量，当前显示已知用量和成本。' });
    }
    if (summary.cache_read_usage_complete === false || summary.cache_write_usage_complete === false
        || summary.reasoning_usage_complete === false) {
        notices.push({ field: 'cache_write_usage_complete', tone: 'warning',
            text: '部分缓存或推理细分未返回，缺失值以占位符表示，累计值仅覆盖已知部分。' });
    }
    return {
        source: 'settled',
        tiles,
        rows,
        breakdown,
        saving,
        notices,
        estimated,
        activeLabel: null,
    };
}
function projectLive(live: RunCostLive): CostLedgerView {
    const estimated = live.estimatedCount > 0;
    const tiles: CostLedgerTile[] = [
        {
            field: 'call_count',
            label: '模型调用',
            value: live.callCount,
            display: formatCount(live.callCount),
            estimated: false,
            accent: false,
        },
        {
            field: 'total_tokens',
            label: 'Token',
            value: live.hasTotalUsage === false ? null : live.totalTokens,
            display: formatTokensCompact(live.hasTotalUsage === false ? null : live.totalTokens),
            estimated,
            accent: false,
        },
        {
            field: 'total_cost_usd',
            label: '成本',
            value: live.costKnown ? live.totalCostUsd : null,
            display: live.costKnown ? formatCost(live.totalCostUsd, 'USD') : READOUT_PLACEHOLDER,
            estimated: estimated && live.costKnown,
            accent: true,
        },
    ];
    const rows: CostLedgerRow[] = [
        {
            field: 'total_input_tokens',
            label: '输入',
            display: `${formatTokens(live.hasInputUsage === false ? null : live.totalInputTokens)} tok`,
        },
        {
            field: 'total_output_tokens',
            label: '输出',
            display: `${formatTokens(live.hasOutputUsage === false ? null : live.totalOutputTokens)} tok`,
        },
        {
            field: 'estimated_call_count',
            label: '估算调用',
            display: `${formatCount(live.estimatedCount)} / ${formatCount(live.callCount)}`,
        },
    ];
    const notices: CostLedgerNotice[] = [];
    if (!live.costKnown && live.callCount > 0) {
        notices.push({
            field: 'currency',
            tone: 'warning',
            text: '用量或计价信息不足，暂时只累计已知用量。',
        });
    }
    if (live.incompleteCount) {
        notices.push({ field: 'token_usage_complete', tone: 'warning',
            text: '部分调用缺少完整计量，当前显示已知用量和成本。' });
    }
    const activeInternal = live.lastAgent ?? live.lastNode;
    return {
        source: 'live',
        tiles,
        rows,
        breakdown: null,
        saving: null,
        notices,
        estimated,
        activeLabel: activeInternal ? formatAgentLabel(activeInternal).label : null,
    };
}
export function buildCostLedgerView(summary: RunCostSummary | null | undefined, live: RunCostLive | null | undefined): CostLedgerView | null {
    if (summary && (summary.call_count > 0 || summary.record_failed || summary.capture_complete === false)) {
        return projectSettled(summary);
    }
    if (live && live.callCount > 0) {
        return projectLive(live);
    }
    return null;
}
export function costLedgerBlurb(view: CostLedgerView): string {
    return view.source === 'live' ? '这轮的模型用量正在累计' : '这轮的模型用量与成本台账';
}
