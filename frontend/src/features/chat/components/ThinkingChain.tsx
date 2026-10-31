import { ArrowUpRight, Check, ChevronDown, Compass, FileCheck2, Map, MapPin, Pause, CircleAlert, Search, TrainFront, BedDouble } from "lucide-react";
import { type ThinkingStep } from "../types/messages";
import { describeToolStep, isPublicActivityStep, toolResultCount, toolResultText, toolStatusLabel } from "../model/toolDisplay";
import { publicProgressText, researchGroups, type ResearchGroup } from "../model/researchProgress";
import { deriveActivityTitle, parseAgentRound } from "../model/agentStages";
import { AgentOrb } from "./AgentOrb";
import { cn } from "../../../lib/utils";
import React, { useEffect, useId, useState } from 'react';
interface ThinkingChainProps {
    steps: ThinkingStep[];
    isGenerating: boolean;
    displayContent?: string;
    isSynthesizing: boolean;
    pendingStatusText?: string;
    variant?: 'default' | 'interrupted';
    serverTotalMs?: number | null;
    startedAt?: Date | string;
    regionId: string;
    layout?: 'default' | 'workspace';
    runStatus?: string | null;
    gatePending?: boolean;
    runKey?: string;
    initiallyExpanded?: boolean;
    forcedCollapsed?: boolean;
    collapseKey?: string;
    activityTitle?: string;
    emptyText?: string;
}
const ICONS = { planning: Compass, destination: MapPin, transport: TrainFront, stay: BedDouble, itinerary: Map, delivery: FileCheck2 };
// dispatcher 的 thinking 事件只宣告并行调研开始，没有 progress_status；它不是完成里程碑。
const TRANSIENT_STAGE_ACTIVITY_AGENTS = new Set(['安排查询']);
const PLACEHOLDER_PROGRESS = new Set([
    '正在整理需求并查询相关资料',
    '正在整理资料与下一步安排',
    '正在整理这一阶段的旅行资料',
    '本轮资料整理已结束',
    '本轮调研未完成，暂未形成可用结果',
]);
function informativeProgressText(value: string | undefined): string {
    const text = publicProgressText(value);
    return text && !PLACEHOLDER_PROGRESS.has(text) ? text : '';
}
function isTransientStageActivity(step: ThinkingStep): boolean {
    if (step.isToolCall || step.progressStatus)
        return false;
    return TRANSIENT_STAGE_ACTIVITY_AGENTS.has(parseAgentRound(step.agentName).base);
}
function safeUrl(value: string | undefined): string | undefined {
    try {
        const url = new URL(value || '');
        return /^https?:$/.test(url.protocol) && !url.username && !url.password ? url.href : undefined;
    }
    catch {
        return undefined;
    }
}
function ToolActivity({ step, stopped, open, onOpenChange }: {
    step: ThinkingStep;
    stopped: boolean;
    open: boolean;
    onOpenChange: (open: boolean) => void;
}) {
    const display = describeToolStep(step);
    const result = toolResultText(step);
    const resultCount = toolResultCount(result);
    const subject = publicProgressText(display.fullSubject || display.subject || undefined);
    const previews = (step.resultPreview || []).map(row => ({ title: publicProgressText(row.title), detail: publicProgressText(row.detail), url: safeUrl(row.url) })).filter(row => row.title);
    const running = display.status === 'running';
    const headline = subject || (result ? result : running ? display.actionText : display.categoryLabel);
    const statusText = running && stopped ? '已停止' : toolStatusLabel(display.status);
    // 结果只保留一行“返回 N 条结果 · 摘要”，避免展开后重复标题和分段。
    const resultLine = running
        ? ''
        : resultCount != null
            ? `${resultCount > 0 ? `返回 ${resultCount} 条结果` : '没有返回结果'}${result ? ` · ${result}` : ''}`
            : result || (display.status === 'failed' ? '本次行动未完成，没有可公开的结果。' : '没有可公开的结果。');
    const summary = <>
    <span className={cn('research-query-dot', running && !stopped && 'is-active', display.status === 'failed' && 'is-warning')}/>
    <span className="research-query-main min-w-0 flex-1"><span className="research-query-kind">{display.categoryLabel}</span>{headline !== display.categoryLabel && <span className="research-query-title" title={headline}>{headline}</span>}</span>
    <span className="research-query-status">{statusText}</span>
    <ChevronDown size={14} className="research-disclosure-icon shrink-0"/>
  </>;
    return <li className="research-query" data-testid="research-query">
    <details open={open} onToggle={(event) => {
            const next = event.currentTarget.open;
            if (next !== open)
                onOpenChange(next);
        }}>
      <summary className="research-query-summary">{summary}</summary>
      <div className="research-query-detail">
        <div className="research-tool-detail">
          <div className="research-tool-field" data-detail-section="input">
            {display.inputs.length > 0
            ? <dl className="research-tool-inputs">{display.inputs.map(field => <div key={`${field.label}-${field.value}`} className="research-tool-input-row">
                <dt className="research-tool-input-label">{field.label}</dt>
                <dd className="research-tool-input-value">{field.value}</dd>
              </div>)}</dl>
            : <p className="research-tool-empty">没有可公开的输入。</p>}
          </div>
          <div className="research-tool-field" data-detail-section="result">
            {running
            ? <p className="research-tool-empty">正在处理，结果返回后会显示在这里。</p>
            : <>
              {resultLine && <p className="research-tool-result-line">{resultLine}</p>}
              {previews.length > 0 && <div className="research-tool-sources">
                {previews.map((row, index) => <div key={index} className="research-source">
                  <div className="research-source-title">{row.url ? <a href={row.url} target="_blank" rel="noreferrer">{row.title}<ArrowUpRight size={13}/></a> : row.title}</div>
                  {row.detail && <p>{row.detail}</p>}
                  {row.url && <span className="research-source-domain">{new URL(row.url).hostname}</span>}
                </div>)}
              </div>}
            </>}
          </div>
        </div>
      </div>
    </details>
  </li>;
}
function AgentCard({ group, interrupted, layout, openToolIds, onToolOpenChange, onClearTools, duplicateTitle, runTerminal }: {
    group: ResearchGroup;
    interrupted: boolean;
    layout: 'default' | 'workspace';
    openToolIds: ReadonlySet<string>;
    onToolOpenChange: (id: string, open: boolean) => void;
    onClearTools: (ids: string[]) => void;
    duplicateTitle: boolean;
    runTerminal: boolean;
}) {
    const region = useId();
    const [open, setOpen] = useState(group.status === 'running');
    const previousStatus = React.useRef(group.status);
    const previousRunTerminal = React.useRef(runTerminal);
    React.useEffect(() => {
        const previous = previousStatus.current;
        previousStatus.current = group.status;
        if (previous === 'running' && group.status !== 'running') {
            setOpen(false);
            onClearTools(group.steps.map(step => step.id));
            return;
        }
        if (previous !== 'running' && group.status === 'running') {
            // 同一个 Run 的补充轮次会复用同一阶段分组；新一轮开始要重新展开，
            // 并清掉上一轮留下的工具详情展开状态。
            setOpen(true);
            onClearTools(group.steps.map(step => step.id));
        }
    }, [group.status, group.steps, onClearTools]);
    React.useEffect(() => {
        if (runTerminal && !previousRunTerminal.current) {
            setOpen(false);
            onClearTools(group.steps.map(step => step.id));
        }
        previousRunTerminal.current = runTerminal;
    }, [group.steps, onClearTools, runTerminal]);
    const Icon = ICONS[group.id as keyof typeof ICONS] || Compass;
    const tools = group.steps.filter(s => s.isToolCall);
    const progressSteps = group.steps.filter(s => !s.isToolCall && s.progressStatus);
    const runningTool = [...tools].reverse().find(s => s.toolStatus === 'running');
    const latestRunningProgress = [...progressSteps].reverse().find(s => s.progressStatus === 'running' && informativeProgressText(s.content));
    const latestCompletedProgress = [...progressSteps].reverse().find(s => s.progressStatus === 'completed' && informativeProgressText(s.content));
    const latestResult = [...tools].reverse().map(toolResultText).find(Boolean) || '';
    const summary = group.status === 'running'
        ? runningTool ? describeToolStep(runningTool).actionText
            : informativeProgressText(latestRunningProgress?.content) || informativeProgressText(latestCompletedProgress?.content) || latestResult
        : informativeProgressText(latestCompletedProgress?.content) || latestResult;
    const workspace = layout === 'workspace';
    const milestones = [...new Set(group.steps
        .filter(s => !s.isToolCall
        && s.progressStatus !== 'running'
        && !(group.status !== 'running' && isTransientStageActivity(s)))
        .map(s => informativeProgressText(s.content))
        .filter(Boolean))]
        .filter(text => workspace || text !== summary);
    const hasDetails = tools.length > 0 || milestones.length > 0;
    const issues = tools.filter(s => s.toolStatus === 'failed' || s.toolStatus === 'capability_declared').length;
    const status = <span className={cn('research-agent-state', group.status === 'running' && 'is-active')}>
      {group.status === 'failed' ? <CircleAlert size={11}/> : group.status === 'completed' ? <Check size={11}/> : group.status === 'stopped' ? <Pause size={11}/> : <span className="research-status-dot"/>}
      {group.status === 'failed' ? '未完成' : group.status === 'running' ? '进行中' : group.status === 'stopped' ? '已停止' : '已结束'}
    </span>;
    const content = workspace ? <>
    <span className="research-agent-icon"><Icon size={18} strokeWidth={1.6}/></span>
    <span className="research-agent-line">
      {duplicateTitle ? status : <span className="research-agent-title">{group.title}{status}</span>}
    </span>
    {hasDetails && <ChevronDown size={15} className={cn('research-agent-chevron', open && 'rotate-180')}/>}
  </> : <>
    <span className="research-agent-icon"><Icon size={18} strokeWidth={1.6}/></span>
    <span className="min-w-0 flex-1">
      <span className="research-agent-title">{group.title}{status}</span>
      {summary && <span className="research-agent-update" data-testid="research-agent-update">{summary}</span>}
      {(tools.length > 0 || issues > 0) && <span className="research-agent-meta">{tools.length} 次查询{issues > 0 && ` · ${issues} 项资料需留意`}</span>}
    </span>
    {hasDetails && <ChevronDown size={16} className={cn('research-agent-chevron', open && 'rotate-180')}/>}
  </>;
    return <section className={cn('research-agent', workspace && 'research-agent-flat', group.status === 'running' && 'is-active', group.status === 'failed' && 'is-failed')} data-testid={`research-agent-${group.id}`}>
    {!hasDetails ? <div className="research-agent-heading">{content}</div>
            : <button type="button" className="research-agent-heading" aria-expanded={open} aria-controls={region} onClick={() => setOpen(v => !v)}>{content}</button>}
    {open && hasDetails && <div id={region} className="research-agent-body">
      {milestones.map((text, i) => <p key={i} className="research-milestone">{text}</p>)}
      {tools.length > 0 && <ol className="research-queries">{tools.map(step => <ToolActivity key={step.id} step={step} stopped={interrupted || group.status !== 'running'} open={openToolIds.has(step.id)} onOpenChange={(open) => onToolOpenChange(step.id, open)}/>)}</ol>}
    </div>}
  </section>;
}
export const ThinkingChain: React.FC<ThinkingChainProps> = ({ steps, isGenerating, displayContent, isSynthesizing, pendingStatusText, variant = 'default', serverTotalMs, startedAt, regionId, layout = 'default', runStatus, gatePending = false, runKey, initiallyExpanded, forcedCollapsed = false, collapseKey, activityTitle, emptyText }) => {
    const interrupted = variant === 'interrupted';
    const live = isGenerating && !interrupted;
    const defaultExpanded = initiallyExpanded ?? (live || layout === 'workspace');
    const [expanded, setExpanded] = useState(defaultExpanded);
    const [openToolIds, setOpenToolIds] = useState<Set<string>>(() => new Set());
    const [now, setNow] = useState(Date.now());
    const runScope = runKey || regionId;
    const previousRunScope = React.useRef(runScope);
    const terminalStatus = Boolean(runStatus && !['running', 'awaiting_input', 'cancel_requested'].includes(runStatus));
    React.useEffect(() => {
        if (previousRunScope.current === runScope)
            return;
        previousRunScope.current = runScope;
        setOpenToolIds(new Set());
        setExpanded(initiallyExpanded ?? (isGenerating && !interrupted));
    }, [initiallyExpanded, interrupted, isGenerating, runScope]);
    React.useEffect(() => {
        if (forcedCollapsed || collapseKey)
            setExpanded(false);
    }, [forcedCollapsed, collapseKey]);
    React.useEffect(() => {
        if (terminalStatus)
            setOpenToolIds(new Set());
    }, [terminalStatus, runScope]);
    const setToolOpen = (id: string, open: boolean) => {
        setOpenToolIds((previous) => {
            const next = new Set(previous);
            if (open)
                next.add(id);
            else
                next.delete(id);
            return next;
        });
    };
    const clearTools = React.useCallback((ids: string[]) => {
        setOpenToolIds((previous) => {
            if (!ids.some(id => previous.has(id)))
                return previous;
            const next = new Set(previous);
            for (const id of ids)
                next.delete(id);
            return next;
        });
    }, []);
    useEffect(() => {
        if (!live)
            return;
        const timer = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, [live]);
    const visibleSteps = React.useMemo(() => steps.filter(isPublicActivityStep), [steps]);
    // 生命周期用未过滤事件计算，展示内容再排除失败/内部行动。先删步骤会让
    // “running → 正常结果 → failed”被误判成仍在进行。
    const groups = React.useMemo(() => researchGroups(steps, live, interrupted)
        .map(group => ({ ...group, steps: group.steps.filter(isPublicActivityStep) }))
        .filter(group => group.steps.length > 0), [steps, live, interrupted]);
    const start = startedAt ? new Date(startedAt).getTime() : visibleSteps[0]?.timestamp.getTime();
    const ms = serverTotalMs ?? (live && start ? now - start : undefined);
    const elapsed = ms != null && Number.isFinite(ms) ? `${Math.max(0, Math.floor(ms / 1000))} 秒` : '';
    const derivedTitle = layout === 'workspace'
        ? deriveActivityTitle({ steps: visibleSteps, isStreaming: live, isSynthesizing, answerStarted: Boolean(displayContent?.trim()), runStatus, gatePending, interrupted })
        : interrupted ? '调研已停止' : isSynthesizing || (live && displayContent?.trim()) ? '正在整理旅行方案' : live ? (visibleSteps.length ? '正在为你调研' : '正在准备规划') : visibleSteps.length ? '调研记录' : '准备旅行查询';
    const title = activityTitle?.trim() || derivedTitle;
    const emptyMessage = emptyText?.trim()
        || (live ? publicProgressText(pendingStatusText) || '正在整理旅行需求，接下来会显示各阶段的查询和资料。' : '本次调研没有留下可查看的过程记录。');
    return <section className={cn('research-panel', layout === 'workspace' && 'research-panel-workspace')} data-testid="thinking-chain">
    <button type="button" className="research-panel-heading" aria-expanded={expanded} aria-controls={regionId} onClick={() => setExpanded(v => !v)}>
      {live ? <AgentOrb state={isSynthesizing ? 'composing' : 'searching'}/> : interrupted ? <Pause size={18}/> : <FileCheck2 size={18}/>}
      <span className="min-w-0 flex-1 text-left"><span className="research-panel-title">{title}</span></span>
      {elapsed && <span className="research-elapsed">{elapsed}</span>}
      <ChevronDown size={16} className={cn('research-agent-chevron', expanded && 'rotate-180')}/>
    </button>
    {expanded && <div id={regionId} className="research-panel-body">
      {groups.length ? <div className="research-agent-list">{groups.map(group => <AgentCard key={`${runScope}-${group.id}`} group={group} interrupted={interrupted} layout={layout} openToolIds={openToolIds} onToolOpenChange={setToolOpen} onClearTools={clearTools} duplicateTitle={layout === 'workspace' && groups.length === 1 && group.title === title} runTerminal={terminalStatus}/>)}</div>
                : <div className="research-empty"><Search size={18}/><p>{emptyMessage}</p></div>}
    </div>}
  </section>;
};
