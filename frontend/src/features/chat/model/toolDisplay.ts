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
export function isNoResultSummary(value: string | null | undefined): boolean {
    const text = (value || '').trim();
    return !text || /没有匹配|没有返回|未找到|未取到|无结果|没有可公开|(?:找到|返回|搜索到|获取到)\s*0\s*(?:条|个|项)|^0\s*(?:条|个|项)/.test(text);
}
/**
 * 过程区只公开正常、可追溯的旅行行动。
 * search_tools 是内部能力选择，不是旅行行动；知识库/网页的“查过但没收录”
 * 也不逐条占位。地点/路线/班次/天气的空结果仍是旅行约束，必须保留。
 * 失败工具与失败阶段进展不进入活动列表；Run 级失败仍由状态区单独表达。
 */
export function isPublicActivityStep(step: ThinkingStep): boolean {
    if (!step.isToolCall)
        return step.progressStatus !== 'failed';
    if (step.toolStatus === 'failed')
        return false;
    if (step.toolName && /(^|[_:])search_tools($|[_:])/i.test(step.toolName))
        return false;
    // 还在执行的工具没有结果可判断，不能因为“暂时为空”就先藏掉。
    if (step.toolStatus === 'running' || (!step.toolStatus && !step.endTime))
        return true;
    const kind = classifyTool(step.toolName, step.toolCategory);
    if (kind === 'knowledge' || kind === 'web_search' || kind === 'web_page') {
        const degraded = step.toolStatus === 'degraded' || step.toolDegraded === true;
        const capability = step.toolStatus === 'capability_declared';
        const hasPreview = (step.resultPreview?.length ?? 0) > 0;
        if (!degraded && !capability && !hasPreview && isNoResultSummary(step.toolResult))
            return false;
    }
    return true;
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
    degraded: '备用来源',
    failed: '未完成',
    capability_declared: '暂不可查',
};
export function toolStatusLabel(status: ThinkingStep['toolStatus']): string {
    return status ? TOOL_STATUS_LABELS[status] : '';
}
type DisplayKind = 'web_search' | 'web_page' | 'place_search' | 'geocode' | 'weather' | 'route' | 'flight' | 'train' | 'currency' | 'knowledge' | 'calculation' | 'internal' | 'data' | 'other';
interface ArgsMap {
    [key: string]: string;
}
export interface ToolInputField {
    label: string;
    value: string;
}
export interface ToolDisplay {
    kind: DisplayKind;
    categoryLabel: string;
    actionText: string;
    subject: string | null;
    fullSubject: string | null;
    inputs: ToolInputField[];
    technicalLabel: string;
    status: ToolStatus;
}
const KIND_LABELS: Record<DisplayKind, string> = {
    web_search: '网页搜索',
    web_page: '网页读取',
    place_search: '地点搜索',
    geocode: '地点定位',
    weather: '天气查询',
    route: '路线查询',
    flight: '班次查询',
    train: '班次查询',
    currency: '汇率换算',
    knowledge: '资料库检索',
    calculation: '预算计算',
    internal: '整理规划',
    data: '旅行数据',
    other: '查询旅行信息',
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
    other: '正在读取旅行资料',
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
    other: '旅行资料读取未完成',
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
        return [truncate(origin, 18), '→', truncate(destination, 18), date ? `· ${date}` : ''].join(' ').trim();
    return firstArg(args, ['route', 'query', 'q']);
}
function classifyTool(toolName: string | undefined, category: ToolCategory | undefined): DisplayKind {
    const name = normalizeToolName(toolName);
    if (/search_tools/.test(name))
        return 'internal';
    if (/search|query/.test(name) && /tavily|brave|duckduckgo|firecrawl|free_web|web|google/.test(name))
        return 'web_search';
    if (/tavily_extract|extract|scrape|fetch|crawler|crawl|browser/.test(name))
        return 'web_page';
    if (/tavily|brave|duckduckgo|free_web_search|web_search|google_search|search_web|firecrawl/.test(name))
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
    return 'other';
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
                return `${amount} ${from} → ${to}`;
            return from && to ? `${from} → ${to}` : null;
        }
        case 'internal':
            // search_tools 的 query 是内部能力标识，不能当作旅行者可读的查询主题。
            return null;
        default:
            return firstArg(args, ['query', 'q', 'name', 'title', 'city', 'address']);
    }
}
function inputFieldsForKind(kind: DisplayKind, args: ArgsMap): ToolInputField[] {
    const fields: ToolInputField[] = [];
    const add = (label: string, keys: string[]) => {
        const value = publicToolArgText(firstArg(args, keys));
        if (!value || fields.some(field => field.value === value))
            return;
        fields.push({ label, value });
    };
    switch (kind) {
        case 'web_search':
        case 'place_search':
        case 'knowledge':
            add('查询内容', ['query', 'q', 'search_query', 'keywords', 'keyword', 'text']);
            break;
        case 'web_page':
            add('网页地址', ['url', 'uri', 'link', 'href', 'website']);
            break;
        case 'geocode':
        case 'weather':
            add('地点', ['address', 'location', 'city', 'query']);
            add('日期', ['date', 'forecast_date']);
            break;
        case 'route':
        case 'flight':
        case 'train':
            add('出发地', ['from_name', 'origin', 'from', 'from_city', 'departure', 'departure_city', 'source']);
            add('目的地', ['to_name', 'destination', 'to', 'to_city', 'arrival', 'arrival_city', 'target']);
            add('日期', ['date', 'departure_date', 'travel_date']);
            add('路线', ['route', 'query', 'q']);
            break;
        case 'currency':
            add('金额', ['amount']);
            add('原币种', ['from', 'base', 'base_currency']);
            add('目标币种', ['to', 'target', 'to_currency', 'target_currency', 'to_currencies']);
            break;
        case 'internal':
            // search_tools 的 query 是内部能力标识，不作为旅行者输入展示。
            break;
        case 'calculation':
        case 'data':
        case 'other':
            add('查询内容', ['query', 'q', 'search_query', 'keywords', 'keyword', 'text']);
            add('地点', ['city', 'location', 'address']);
            add('日期', ['date', 'departure_date', 'travel_date']);
            break;
    }
    return fields;
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
    const subject = publicToolArgText(subjectForKind(kind, args));
    const status = statusForStep(step);
    // 能力声明只说明“这一步暂不可查”，具体限制必须来自后端 result_summary，
    // 不能在前端用“未覆盖该日期”之类的泛化结论代替。
    const verb = status === 'running'
        ? RUNNING_VERB[kind]
        : status === 'failed'
            ? FAILED_VERB[kind]
            : status === 'capability_declared'
                ? '暂不可查'
                : DONE_VERB[kind];
    const actionText = subject ? `${verb}「${truncate(subject, 44)}」` : verb;
    return {
        kind,
        categoryLabel: KIND_LABELS[kind],
        actionText,
        subject: subject ? truncate(subject, 44) : null,
        fullSubject: subject,
        inputs: inputFieldsForKind(kind, args),
        technicalLabel: KIND_LABELS[kind],
        status,
    };
}
function looksLikeMachinePayload(text: string): boolean {
    const trimmed = text.trimStart();
    return !publicProgressText(trimmed);
}
function aliasForInternalIdentifier(value: string): string {
    return KIND_LABELS[classifyTool(value, undefined)];
}
const INTERNAL_IDENTIFIER = /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/gi;
const PROVIDER_IDENTIFIER = /\b(?:brave|tavily|firecrawl|duckduckgo|nominatim|amap|duffel|frankfurter)\b/gi;
function activationSummary(text: string): string | null {
    const match = /^激活工具\s*[：:]\s*([\s\S]*)$/.exec(text);
    if (!match)
        return null;
    const raw = match[1].trim();
    if (!raw || raw === '未匹配到工具')
        return raw === '未匹配到工具' ? raw : '已启用本次规划所需能力';
    const aliases = [...new Set(raw
            .split(/[,，、\s]+/)
            .map(token => token.trim())
            .filter(Boolean)
            .map(aliasForInternalIdentifier))];
    return aliases.length ? `已启用：${aliases.join('、')}` : '已启用本次规划所需能力';
}
function sanitizeInternalIdentifiers(text: string): string {
    return text
        .replace(INTERNAL_IDENTIFIER, token => aliasForInternalIdentifier(token))
        .replace(PROVIDER_IDENTIFIER, token => aliasForInternalIdentifier(token));
}
const TECHNICAL_INPUT_FIELDS = /\b(?:contract_version|research_packet_id|tool_call_id|run_id|session_id|provider|status_code|args_summary|sanitized_result|raw_result)\b\s*[:=]/i;
const TECHNICAL_ERROR_TEXT = [
    /^\s*(?:error|exception|traceback|typeerror|valueerror|runtimeerror|keyerror|httpx?error|urllib3)\b/i,
    /\b(?:traceback \(most recent call last\)|stack trace|internal server error|service unavailable|bad gateway|gateway timeout)\b/i,
    /\b(?:errno|econnrefused|etimedout|enotfound|econnreset)\b/i,
    /\b(?:status|status_code|http status|http)\s*[:：=]?\s*[45]\d\d\b/i,
    /(?:请求|服务|接口|上游|工具)(?:调用|请求|响应)?失败\s*[：:].*(?:HTTP|状态码|[45]\d\d)/i,
    /\bFile\s+"[^"]+",\s*line\s+\d+/i,
    /\bat\s+[\w.$<>]+\s+\([^)]*:\d+:\d+\)/i,
];
function publicToolArgText(value: string | null | undefined): string | null {
    const text = publicProgressText(value || undefined);
    if (!text || TECHNICAL_INPUT_FIELDS.test(text) || TECHNICAL_ERROR_TEXT.some(pattern => pattern.test(text)))
        return null;
    return sanitizeInternalIdentifiers(text);
}
export function toolResultText(step: Pick<ThinkingStep, 'toolResult'>): string | null {
    const text = step.toolResult?.trim();
    if (!text || looksLikeMachinePayload(text))
        return null;
    const activation = activationSummary(text);
    if (activation)
        return activation;
    return sanitizeInternalIdentifiers(text);
}
const CHINESE_DIGITS: Record<string, number> = {
    一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9,
};
function parseCountValue(value: string): number | null {
    if (/^\d+$/.test(value))
        return parseInt(value, 10);
    if (value === '十')
        return 10;
    const tenIndex = value.indexOf('十');
    if (tenIndex >= 0) {
        const tens = tenIndex === 0 ? 1 : CHINESE_DIGITS[value[tenIndex - 1]];
        const ones = tenIndex === value.length - 1 ? 0 : CHINESE_DIGITS[value[tenIndex + 1]];
        return tens != null && ones != null ? tens * 10 + ones : null;
    }
    return CHINESE_DIGITS[value] ?? null;
}
export function toolResultCount(summary: string | null): number | null {
    if (!summary)
        return null;
    const match = /(?:找到|搜索到|返回|获取到|整理出|共)\s*(?:等|了)?\s*([0-9]+|[一二两三四五六七八九十]+)\s*(?:个|条|项|处|家|座|班)?\s*[^，。；:：\d]{0,12}?(?:结果|地点|网页|候选|路线|班次|住宿|资料|选项|来源)/.exec(summary);
    if (!match)
        return null;
    return parseCountValue(match[1]);
}
export function toolSourceLabel(toolName: string | undefined): string {
    const name = (toolName || '').trim();
    if (!name)
        return KIND_LABELS.other;
    return KIND_LABELS[classifyTool(name, undefined)];
}
function normalizedInvocationPart(value: string | undefined): string {
    return (value || '').replace(/\s+/g, ' ').trim();
}
/**
 * 相邻的同一工具、同一参数、同一结果只保留最后一次。Provider 重试或缓存命中
 * 常把同一查询写两遍；合并的是重复行，不合并不同来源的证据。
 */
export function dedupeToolSteps(steps: ThinkingStep[]): ThinkingStep[] {
    const out: ThinkingStep[] = [];
    for (const step of steps) {
        const previous = out[out.length - 1];
        const duplicate = previous
            && previous.isToolCall && step.isToolCall && step.toolName
            && previous.toolName === step.toolName
            && previous.toolStatus === step.toolStatus && step.toolStatus !== 'running'
            && normalizedInvocationPart(previous.toolArgs) === normalizedInvocationPart(step.toolArgs)
            && normalizedInvocationPart(previous.toolResult) === normalizedInvocationPart(step.toolResult)
            && JSON.stringify(previous.resultPreview ?? []) === JSON.stringify(step.resultPreview ?? []);
        if (duplicate) {
            out[out.length - 1] = {
                ...step,
                fromCache: step.fromCache || previous.fromCache,
            };
            continue;
        }
        out.push(step);
    }
    return out;
}
