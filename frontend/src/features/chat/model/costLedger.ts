import { type RunCostLive, type CostGroupBreakdown, type RunCostSummary, type ToolContextSaving } from "../types/cost";
import { formatCost, formatCount, formatDuration, formatPercent, formatTokens, formatTokensCompact, READOUT_PLACEHOLDER } from "../../../lib/format";
import { formatAgentLabel } from "../../travel/model/travelProgress";
export type LedgerField = keyof RunCostSummary;
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
