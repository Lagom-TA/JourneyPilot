import { ArrowUpRight, Check, ChevronDown, Compass, FileCheck2, Map, MapPin, Pause, CircleAlert, Search, TrainFront, BedDouble } from "lucide-react";
import { type ThinkingStep } from "../types/messages";
import { describeToolStep, toolResultText, toolStatusLabel } from "../model/toolDisplay";
import { publicProgressText, researchGroups, type ResearchGroup } from "../model/researchProgress";
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
}
const ICONS = { planning: Compass, destination: MapPin, transport: TrainFront, stay: BedDouble, itinerary: Map, verify: FileCheck2, delivery: FileCheck2 };
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
    const subject = publicProgressText(display.subject || undefined);
    const previews = (step.resultPreview || []).map(row => ({ title: publicProgressText(row.title), detail: publicProgressText(row.detail), url: safeUrl(row.url) })).filter(row => row.title);
    const running = display.status === 'running';
    const headline = result || subject || display.categoryLabel;
    const extraSubject = subject && subject !== headline ? subject : '';
    const extraResults = previews.filter(row => row.title !== headline || row.detail || row.url);
    const hasDetails = Boolean(extraSubject || extraResults.length);
    const summary = <>
    <span className={cn('research-query-dot', running && !stopped && 'is-active', display.status === 'failed' && 'is-warning')}/>
    <span className="min-w-0 flex-1"><span className="research-query-kind">{display.categoryLabel}</span><span className="research-query-title">{headline}</span></span>
    <span className="research-query-status">{running && stopped ? '已停止' : toolStatusLabel(display.status)}</span>
    {hasDetails && <ChevronDown size={14} className="research-disclosure-icon shrink-0"/>}
  </>;
    return <li className="research-query" data-testid="research-query">
    {hasDetails ? <details>
      <summary className="research-query-summary">{summary}</summary>
      <div className="research-query-detail">
        {extraSubject && <p className="research-query-context">查询内容 · {extraSubject}</p>}
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
function AgentCard({ group, interrupted }: {
    group: ResearchGroup;
    interrupted: boolean;
}) {
    const region = useId();
    const [open, setOpen] = useState(false);
    const Icon = ICONS[group.id as keyof typeof ICONS] || Compass;
    const tools = group.steps.filter(s => s.isToolCall);
    const last = group.steps[group.steps.length - 1];
    const runningTool = [...tools].reverse().find(s => s.toolStatus === 'running');
    const latestResult = [...tools].reverse().find(s => toolResultText(s));
    const summary = group.status === 'running'
        ? runningTool ? describeToolStep(runningTool).actionText : '正在整理资料与下一步安排'
        : group.status === 'failed' ? '本轮调研未完成，暂未形成可用结果'
            : group.status === 'stopped' ? '任务已停止，已查资料保留在下方'
                : latestResult ? toolResultText(latestResult) : (group.id === 'planning' ? '需求已梳理，调研任务已分派' : publicProgressText(last.content)) || '本轮处理已结束';
    const milestones = [...new Set(group.steps.filter(s => !s.isToolCall).map(s => publicProgressText(s.content)).filter(Boolean))]
        .filter(text => text !== summary && text !== '正在整理需求并查询相关资料' && text !== '本轮资料整理已结束');
    const published = [...group.steps].reverse().find(s => !s.isToolCall && s.progressStatus);
    const candidates = (published?.resultPreview || []).map(row => ({ title: publicProgressText(row.title), detail: publicProgressText(row.detail) })).filter(row => row.title);
    const hasDetails = tools.length > 0 || milestones.length > 0 || candidates.length > 0;
    const issues = tools.filter(s => s.toolStatus === 'failed' || s.toolStatus === 'capability_declared').length;
    const content = <>
    <span className="research-agent-icon"><Icon size={18} strokeWidth={1.6}/></span>
    <span className="min-w-0 flex-1">
      <span className="research-agent-title">{group.title}<span className={cn('research-agent-state', group.status === 'running' && 'is-active')}>
        {group.status === 'failed' ? <CircleAlert size={11}/> : group.status === 'completed' ? <Check size={11}/> : group.status === 'stopped' ? <Pause size={11}/> : <span className="research-status-dot"/>}
        {group.status === 'failed' ? '未完成' : group.status === 'running' ? '进行中' : group.status === 'stopped' ? '已停止' : '已结束'}
      </span></span>
      <span className="research-agent-description">{group.description}</span>
      <span className="research-agent-update">{publicProgressText(summary || '') || '正在处理调研任务'}</span>
      {(tools.length > 0 || issues > 0) && <span className="research-agent-meta">{tools.length} 次查询{issues > 0 && ` · ${issues} 项资料需留意`}</span>}
    </span>
    {hasDetails && <ChevronDown size={16} className={cn('research-agent-chevron', open && 'rotate-180')}/>}
  </>;
    return <section className={cn('research-agent', group.status === 'running' && 'is-active', group.status === 'failed' && 'is-failed')} data-testid={`research-agent-${group.id}`}>
    {hasDetails ? <button type="button" className="research-agent-heading" aria-expanded={open} aria-controls={region} onClick={() => setOpen(v => !v)}>{content}</button>
            : <div className="research-agent-heading">{content}</div>}
    {open && hasDetails && <div id={region} className="research-agent-body">
      {milestones.map((text, i) => <p key={i} className="research-milestone">{text}</p>)}
      {candidates.length > 0 && <div className="research-candidates">
        <p className="research-query-context">调研候选 · 最终选择以行程为准</p>
        {candidates.map((row, i) => <div key={i} className="research-source"><div className="research-source-title">{row.title}</div>{row.detail && <p>{row.detail}</p>}</div>)}
      </div>}
      {tools.length > 0 && <ol className="research-queries">{tools.map(step => <ToolActivity key={step.id} step={step} stopped={interrupted || group.status !== 'running'}/>)}</ol>}
    </div>}
  </section>;
}
export const ThinkingChain: React.FC<ThinkingChainProps> = ({ steps, isGenerating, displayContent, isSynthesizing, pendingStatusText, variant = 'default', serverTotalMs, startedAt, regionId }) => {
    const interrupted = variant === 'interrupted';
    const live = isGenerating && !interrupted;
    const [expanded, setExpanded] = useState(live);
    const [now, setNow] = useState(Date.now());
    useEffect(() => {
        if (!live)
            return;
        const timer = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, [live]);
    const groups = researchGroups(steps, live, interrupted);
    const active = groups.filter(g => g.status === 'running').length;
    const start = startedAt ? new Date(startedAt).getTime() : steps[0]?.timestamp.getTime();
    const ms = serverTotalMs ?? (live && start ? now - start : undefined);
    const elapsed = ms != null && Number.isFinite(ms) ? `${Math.max(0, Math.floor(ms / 1000))} 秒` : '';
    const title = interrupted ? '调研已停止' : isSynthesizing || (live && displayContent?.trim()) ? '正在整理旅行方案' : live ? '正在为你调研' : '研究记录';
    return <section className="research-panel" data-testid="thinking-chain">
    <button type="button" className="research-panel-heading" aria-expanded={expanded} aria-controls={regionId} onClick={() => setExpanded(v => !v)}>
      {live ? <AgentOrb state={isSynthesizing ? 'composing' : 'searching'}/> : interrupted ? <Pause size={18}/> : <FileCheck2 size={18}/>}
      <span className="min-w-0 flex-1 text-left"><span className="research-panel-title">{title}</span><span className="research-panel-subtitle" role="status">{live ? active > 1 ? `${active} 个任务正在并行推进` : '跟随每个任务，查看查询与资料' : `${groups.length} 个工作环节 · 查询过程可追溯`}</span></span>
      {elapsed && <span className="research-elapsed">{elapsed}</span>}
      <ChevronDown size={16} className={cn('research-agent-chevron', expanded && 'rotate-180')}/>
    </button>
    {expanded && <div id={regionId} className="research-panel-body">
      {groups.length ? <div className="research-agent-list">{groups.map(group => <AgentCard key={group.id} group={group} interrupted={interrupted}/>)}</div>
                : <div className="research-empty"><Search size={18}/><p>{publicProgressText(pendingStatusText) || '正在理解你的旅行需求，准备调研任务'}</p></div>}
      {live && <p className="research-panel-note">资料随查询逐步更新，最终安排将在行程中汇总。</p>}
    </div>}
  </section>;
};
