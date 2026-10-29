import { ArrowUpRight, Check, ChevronDown, Compass, FileCheck2, Map, MapPin, Pause, CircleAlert, Search, TrainFront, BedDouble } from "lucide-react";
import { type ThinkingStep } from "../types/messages";
import { describeToolStep, toolResultText, toolStatusLabel } from "../model/toolDisplay";
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
function ToolActivity({ step, stopped }: {
    step: ThinkingStep;
    stopped: boolean;
}) {
    const display = describeToolStep(step);
    const result = toolResultText(step);
    const subject = publicProgressText(display.fullSubject || display.subject || undefined);
    const previews = (step.resultPreview || []).map(row => ({ title: publicProgressText(row.title), detail: publicProgressText(row.detail), url: safeUrl(row.url) })).filter(row => row.title);
    const running = display.status === 'running';
    const headline = subject || result || display.categoryLabel;
    const extraSubject = result && result !== headline ? result : '';
    const extraResults = previews.filter(row => row.title !== headline || row.detail || row.url);
    const hasDetails = Boolean(extraSubject || extraResults.length);
    const summary = <>
    <span className={cn('research-query-dot', running && !stopped && 'is-active', display.status === 'failed' && 'is-warning')}/>
    <span className="research-query-main min-w-0 flex-1"><span className="research-query-kind">{display.categoryLabel}</span><span className="research-query-title" title={headline}>{headline}</span></span>
    <span className="research-query-status">{running && stopped ? '已停止' : toolStatusLabel(display.status)}</span>
    {hasDetails && <ChevronDown size={14} className="research-disclosure-icon shrink-0"/>}
  </>;
    return <li className="research-query" data-testid="research-query">
    {hasDetails ? <details>
      <summary className="research-query-summary">{summary}</summary>
      <div className="research-query-detail">
        {extraSubject && <p className="research-query-context">返回摘要 · {extraSubject}</p>}
        {extraResults.length > 0 && <p className="research-query-context">结果预览</p>}
        {extraResults.map((row, index) => <div key={index} className="research-source">
          <div className="research-source-title">{row.url ? <a href={row.url} target="_blank" rel="noreferrer">{row.title}<ArrowUpRight size={13}/></a> : row.title}</div>
          {row.detail && <p>{row.detail}</p>}
          {row.url && <span className="research-source-domain">{new URL(row.url).hostname}</span>}
        </div>)}
      </div>
    </details> : <div className="research-query-summary">{summary}</div>}
  </li>;
}
function AgentCard({ group, interrupted, layout }: {
    group: ResearchGroup;
    interrupted: boolean;
    layout: 'default' | 'workspace';
}) {
    const region = useId();
    const [open, setOpen] = useState(group.status === 'running');
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
    const milestones = [...new Set(group.steps
        .filter(s => !s.isToolCall
        && s.progressStatus !== 'running'
        && !(group.status !== 'running' && isTransientStageActivity(s)))
        .map(s => informativeProgressText(s.content))
        .filter(Boolean))]
        .filter(text => text !== summary);
    const hasDetails = tools.length > 0 || milestones.length > 0;
    const issues = tools.filter(s => s.toolStatus === 'failed' || s.toolStatus === 'capability_declared').length;
    const workspace = layout === 'workspace';
    const status = <span className={cn('research-agent-state', group.status === 'running' && 'is-active')}>
      {group.status === 'failed' ? <CircleAlert size={11}/> : group.status === 'completed' ? <Check size={11}/> : group.status === 'stopped' ? <Pause size={11}/> : <span className="research-status-dot"/>}
      {group.status === 'failed' ? '未完成' : group.status === 'running' ? '进行中' : group.status === 'stopped' ? '已停止' : '已结束'}
    </span>;
    const content = workspace ? <>
    <span className="research-agent-icon"><Icon size={18} strokeWidth={1.6}/></span>
    <span className="research-agent-line">
      <span className="research-agent-title">{group.title}{status}</span>
      {(tools.length > 0 || issues > 0) && <span className="research-agent-meta">{tools.length} 次查询{issues > 0 && ` · ${issues} 项资料需留意`}</span>}
      {summary && <span className="research-agent-update" data-testid="research-agent-update" title={summary} aria-label={summary}>{summary}</span>}
    </span>
  </> : <>
    <span className="research-agent-icon"><Icon size={18} strokeWidth={1.6}/></span>
    <span className="min-w-0 flex-1">
      <span className="research-agent-title">{group.title}{status}</span>
      {summary && <span className="research-agent-update" data-testid="research-agent-update">{summary}</span>}
      {(tools.length > 0 || issues > 0) && <span className="research-agent-meta">{tools.length} 次查询{issues > 0 && ` · ${issues} 项资料需留意`}</span>}
    </span>
    {hasDetails && <ChevronDown size={16} className={cn('research-agent-chevron', open && 'rotate-180')}/>}
  </>;
    const showBody = workspace || open;
    return <section className={cn('research-agent', workspace && 'research-agent-flat', group.status === 'running' && 'is-active', group.status === 'failed' && 'is-failed')} data-testid={`research-agent-${group.id}`}>
    {workspace || !hasDetails ? <div className="research-agent-heading">{content}</div>
            : <button type="button" className="research-agent-heading" aria-expanded={open} aria-controls={region} onClick={() => setOpen(v => !v)}>{content}</button>}
    {showBody && hasDetails && <div id={region} className="research-agent-body">
      {milestones.map((text, i) => <p key={i} className="research-milestone">{text}</p>)}
      {tools.length > 0 && <ol className="research-queries">{tools.map(step => <ToolActivity key={step.id} step={step} stopped={interrupted || group.status !== 'running'}/>)}</ol>}
    </div>}
  </section>;
}
export const ThinkingChain: React.FC<ThinkingChainProps> = ({ steps, isGenerating, displayContent, isSynthesizing, pendingStatusText, variant = 'default', serverTotalMs, startedAt, regionId, layout = 'default', runStatus, gatePending = false }) => {
    const interrupted = variant === 'interrupted';
    const live = isGenerating && !interrupted;
    const [expanded, setExpanded] = useState(live || layout === 'workspace');
    const [now, setNow] = useState(Date.now());
    useEffect(() => {
        if (!live)
            return;
        const timer = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, [live]);
    const groups = researchGroups(steps, live, interrupted);
    const start = startedAt ? new Date(startedAt).getTime() : steps[0]?.timestamp.getTime();
    const ms = serverTotalMs ?? (live && start ? now - start : undefined);
    const elapsed = ms != null && Number.isFinite(ms) ? `${Math.max(0, Math.floor(ms / 1000))} 秒` : '';
    const title = layout === 'workspace'
        ? deriveActivityTitle({ steps, isStreaming: live, isSynthesizing, answerStarted: Boolean(displayContent?.trim()), runStatus, gatePending, interrupted })
        : interrupted ? '调研已停止' : isSynthesizing || (live && displayContent?.trim()) ? '正在整理旅行方案' : live ? (steps.length ? '正在为你调研' : '正在准备规划') : steps.length ? '调研记录' : '准备旅行查询';
    return <section className={cn('research-panel', layout === 'workspace' && 'research-panel-workspace')} data-testid="thinking-chain">
    <button type="button" className="research-panel-heading" aria-expanded={expanded} aria-controls={regionId} onClick={() => setExpanded(v => !v)}>
      {live ? <AgentOrb state={isSynthesizing ? 'composing' : 'searching'}/> : interrupted ? <Pause size={18}/> : <FileCheck2 size={18}/>}
      <span className="min-w-0 flex-1 text-left"><span className="research-panel-title">{title}</span></span>
      {elapsed && <span className="research-elapsed">{elapsed}</span>}
      <ChevronDown size={16} className={cn('research-agent-chevron', expanded && 'rotate-180')}/>
    </button>
    {expanded && <div id={regionId} className="research-panel-body">
      {groups.length ? <div className="research-agent-list">{groups.map(group => <AgentCard key={group.id} group={group} interrupted={interrupted} layout={layout}/>)}</div>
                : <div className="research-empty"><Search size={18}/><p>{live ? publicProgressText(pendingStatusText) || '正在整理旅行需求，接下来会显示各阶段的查询和资料。' : '本次调研没有留下可查看的过程记录。'}</p></div>}
    </div>}
  </section>;
};
