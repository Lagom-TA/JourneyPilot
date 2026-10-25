import { publicProgressText } from "./researchProgress";
import { type SSEEvent } from "../types/events";
import { type ThinkingStep, type ToolCategory, type ToolExecutionStatus } from "../types/messages";
import { truncate } from "../../../lib/utils";
export type ToolStatus = NonNullable<ThinkingStep['toolStatus']>;
const CAPABILITY_DECLARATION_STATUSES: readonly ToolExecutionStatus[] = [
    'not_applicable',
    'reference_only',
];
export function isCapabilityDeclaration(status: string | undefined): boolean {
    return CAPABILITY_DECLARATION_STATUSES.includes(status as ToolExecutionStatus);
}
export function thinkingStepStatusFromToolResult(status: SSEEvent['status']): NonNullable<ThinkingStep['toolStatus']> {
    if (isCapabilityDeclaration(status))
        return 'capability_declared';
    if (status === 'degraded')
        return 'degraded';
    if (status === 'success')
        return 'completed';
    return 'failed';
}
const TOOL_STATUS_LABELS: Record<ToolStatus, string> = {
    running: '进行中',
    completed: '已完成',
    degraded: '已完成（备用通道）',
    failed: '未完成',
    capability_declared: '能力边界 · 仅参考资料',
};
export function toolStatusLabel(status: ThinkingStep['toolStatus']): string {
    return status ? TOOL_STATUS_LABELS[status] : '';
}
type DisplayKind = 'web_search' | 'web_page' | 'place_search' | 'geocode' | 'weather' | 'route' | 'flight' | 'train' | 'currency' | 'knowledge' | 'calculation' | 'internal' | 'data' | 'other';
interface ArgsMap {
    [key: string]: string;
}
export interface ToolDisplay {
    kind: DisplayKind;
    categoryLabel: string;
    actionText: string;
    subject: string | null;
    technicalLabel: string;
    status: ToolStatus;
}
const KIND_LABELS: Record<DisplayKind, string> = {
    web_search: '联网搜索',
    web_page: '网页读取',
    place_search: '地点搜索',
    geocode: '地点定位',
    weather: '天气查询',
    route: '路线查询',
    flight: '航班搜索',
    train: '火车查询',
    currency: '汇率换算',
    knowledge: '资料库检索',
    calculation: '预算计算',
    internal: '整理规划',
    data: '旅行数据',
    other: '数据连接',
};
const RUNNING_VERB: Record<DisplayKind, string> = {
    web_search: '正在搜索',
    web_page: '正在读取网页',
    place_search: '正在搜索地点',
    geocode: '正在定位',
    weather: '正在查询天气',
    route: '正在核对路线',
    flight: '正在查询航班',
    train: '正在查询火车',
    currency: '正在换算',
    knowledge: '正在检索资料库',
    calculation: '正在计算',
    internal: '正在整理',
    data: '正在读取旅行数据',
    other: '正在调用数据连接',
};
const DONE_VERB: Record<DisplayKind, string> = {
    web_search: '已读取联网资料',
    web_page: '已读取网页',
    place_search: '已读取地点资料',
    geocode: '已定位',
    weather: '已读取天气',
    route: '已核对路线',
    flight: '已读取航班信息',
    train: '已读取火车信息',
    currency: '已完成换算',
    knowledge: '已读取资料库',
    calculation: '已完成计算',
    internal: '已整理',
    data: '已读取旅行数据',
    other: '已读取数据',
};
const FAILED_VERB: Record<DisplayKind, string> = {
    web_search: '搜索未完成',
    web_page: '网页读取未完成',
    place_search: '地点搜索未完成',
    geocode: '定位未完成',
    weather: '天气查询未完成',
    route: '路线查询未完成',
    flight: '航班查询未完成',
    train: '火车查询未完成',
    currency: '换算未完成',
    knowledge: '资料库检索未完成',
    calculation: '计算未完成',
    internal: '整理未完成',
    data: '旅行数据读取未完成',
    other: '数据连接未完成',
};
const CAPABILITY_VERB: Record<DisplayKind, string> = {
    web_search: '联网资料未覆盖该日期',
    web_page: '网页数据未覆盖该日期',
    place_search: '地点数据未覆盖该日期',
    geocode: '定位数据未覆盖该日期',
    weather: '天气数据未覆盖该日期',
    route: '路线数据未覆盖该日期',
    flight: '航班数据未覆盖该日期',
    train: '车票数据未覆盖该日期',
    currency: '汇率数据未覆盖该日期',
    knowledge: '资料库未覆盖该日期',
    calculation: '该日期不适用本次计算',
    internal: '该步不适用',
    data: '旅行数据未覆盖该日期',
    other: '该数据源未覆盖该日期',
};
function normalizeToolName(toolName: string | undefined): string {
    return (toolName || '').toLowerCase().replace(/[\s:]+/g, '_');
}
function trimQuotes(value: string): string {
    return value.trim().replace(/^['"]|['"]$/g, '').trim();
}
function argsFromJson(raw: string): ArgsMap | null {
    try {
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
            return null;
        return Object.fromEntries(Object.entries(parsed)
            .filter(([, value]) => value != null && typeof value !== 'object')
            .map(([key, value]) => [key.toLowerCase(), String(value)]));
    }
    catch {
        return null;
    }
}
export function parseToolArgs(raw: string | undefined): ArgsMap {
    if (!raw?.trim())
        return {};
    const trimmed = raw.trim();
    const json = argsFromJson(trimmed);
    if (json)
        return json;
    const entries: ArgsMap = {};
    const parts = trimmed.split(/,\s+(?=[\w.-]+\s*=)/);
    for (const part of parts) {
        const idx = part.indexOf('=');
        if (idx <= 0)
            continue;
        const key = part.slice(0, idx).trim().toLowerCase();
        const value = trimQuotes(part.slice(idx + 1));
        if (key && value)
            entries[key] = value;
    }
    return entries;
}
function firstArg(args: ArgsMap, keys: string[]): string | null {
    for (const key of keys) {
        const value = args[key.toLowerCase()];
        if (value && value !== 'null' && value !== 'undefined')
            return value;
    }
    return null;
}
function hostFromUrl(value: string | null): string | null {
    if (!value)
        return null;
    try {
        const url = new URL(value);
        const path = url.pathname.split('/').filter(Boolean)[0];
        return path ? `${url.hostname}/${path}` : url.hostname;
    }
    catch {
        return value.replace(/^https?:\/\//, '').split(/[?#]/)[0].split('/').slice(0, 2).join('/');
    }
}
function routeSubject(args: ArgsMap): string | null {
    const origin = firstArg(args, ['from_name', 'origin', 'from', 'from_city', 'departure', 'departure_city', 'source']);
    const destination = firstArg(args, ['to_name', 'destination', 'to', 'to_city', 'arrival', 'arrival_city', 'target']);
    const date = firstArg(args, ['date', 'departure_date', 'travel_date']);
    if (origin && destination)
        return [truncate(origin, 18), '->', truncate(destination, 18), date ? `· ${date}` : ''].join(' ').trim();
    return firstArg(args, ['route', 'query', 'q']);
}
function classifyTool(toolName: string | undefined, category: ToolCategory | undefined): DisplayKind {
    const name = normalizeToolName(toolName);
    if (/search_tools/.test(name))
        return 'internal';
    if (/tavily_extract|extract|fetch|crawler|crawl|firecrawl|browser/.test(name))
        return 'web_page';
    if (/tavily|brave|duckduckgo|free_web_search|web_search|google_search|search_web/.test(name))
        return 'web_search';
    if (/maps?_weather|forecast|weather/.test(name))
        return 'weather';
    if (/maps?_(geo|geocode)|geocode/.test(name))
        return 'geocode';
    if (/direction|route|transit|driving|walking|directions/.test(name))
        return 'route';
    if (/global_place_search|maps?_(text|around|search|place|poi)|amap|poi/.test(name))
        return 'place_search';
    if (/flight|duffel|offer/.test(name))
        return 'flight';
    if (/train|rail|station|12306/.test(name))
        return 'train';
    if (/currency|exchange|forex|frankfurter/.test(name))
        return 'currency';
    if (/knowledge|rag|retriev|vector|document/.test(name))
        return 'knowledge';
    if (category === 'calculation')
        return 'calculation';
    if (category === 'internal')
        return 'internal';
    if (category === 'data')
        return 'data';
    return category === 'search' ? 'web_search' : 'other';
}
function subjectForKind(kind: DisplayKind, args: ArgsMap): string | null {
    switch (kind) {
        case 'web_search':
        case 'place_search':
        case 'knowledge':
            return firstArg(args, ['query', 'q', 'search_query', 'keywords', 'keyword', 'text']);
        case 'web_page':
            return hostFromUrl(firstArg(args, ['url', 'uri', 'link', 'href', 'website']));
        case 'geocode':
            return firstArg(args, ['address', 'location', 'query', 'city']);
        case 'weather':
            return firstArg(args, ['city', 'location', 'query']);
        case 'route':
        case 'flight':
        case 'train':
            return routeSubject(args);
        case 'currency': {
            const amount = firstArg(args, ['amount']);
            const from = firstArg(args, ['from', 'base', 'base_currency']);
            const to = firstArg(args, ['to', 'target', 'to_currency', 'target_currency', 'to_currencies']);
            if (amount && from && to)
                return `${amount} ${from} -> ${to}`;
            return from && to ? `${from} -> ${to}` : null;
        }
        default:
            return firstArg(args, ['query', 'q', 'name', 'title', 'city', 'address']);
    }
}
function statusForStep(step: ThinkingStep): ToolStatus {
    if (step.toolStatus === 'failed')
        return 'failed';
    if (step.toolStatus === 'capability_declared')
        return 'capability_declared';
    if (step.toolStatus === 'running' || (!step.toolStatus && !step.endTime))
        return 'running';
    if (step.toolStatus === 'degraded' || step.toolDegraded)
        return 'degraded';
    return 'completed';
}
export function describeToolStep(step: ThinkingStep): ToolDisplay {
    const kind = classifyTool(step.toolName, step.toolCategory);
    const args = parseToolArgs(step.toolArgs);
    const subject = subjectForKind(kind, args);
    const status = statusForStep(step);
    const verb = status === 'running'
        ? RUNNING_VERB[kind]
        : status === 'failed'
            ? FAILED_VERB[kind]
            : status === 'capability_declared'
                ? CAPABILITY_VERB[kind]
                : DONE_VERB[kind];
    const actionText = subject ? `${verb}「${truncate(subject, 44)}」` : verb;
    return {
        kind,
        categoryLabel: KIND_LABELS[kind],
        actionText,
        subject: subject ? truncate(subject, 44) : null,
        technicalLabel: step.toolName || KIND_LABELS[kind],
        status,
    };
}
function looksLikeMachinePayload(text: string): boolean {
    const trimmed = text.trimStart();
    return !publicProgressText(trimmed);
}
export function toolResultText(step: Pick<ThinkingStep, 'toolResult'>): string | null {
    const text = step.toolResult?.trim();
    if (!text || looksLikeMachinePayload(text))
        return null;
    return text;
}
export function toolSourceLabel(toolName: string | undefined): string {
    const name = (toolName || '').trim();
    if (!name)
        return KIND_LABELS.other;
    return KIND_LABELS[classifyTool(name, undefined)];
}
export function countToolSources(steps: ThinkingStep[]): number {
    const kinds = new Set<DisplayKind>();
    for (const step of steps) {
        if (!step.toolName)
            continue;
        kinds.add(classifyTool(step.toolName, step.toolCategory));
    }
    return kinds.size;
}
export function describeToolGroup(steps: ThinkingStep[]): ToolDisplay {
    const last = steps[steps.length - 1];
    const base = describeToolStep(last);
    const completed = steps.filter((step) => step.toolStatus !== 'running').length;
    const failed = last.toolStatus === 'failed';
    const running = last.toolStatus === 'running';
    const capability = last.toolStatus === 'capability_declared';
    const actionText = running
        ? base.actionText
        : failed
            ? `有 ${steps.length} 次调用未完全完成`
            : capability
                ? '未覆盖该日期，仅取到参考资料'
                : `已完成 ${completed || steps.length} 次查询`;
    return { ...base, actionText, status: failed ? 'failed' : base.status };
}
