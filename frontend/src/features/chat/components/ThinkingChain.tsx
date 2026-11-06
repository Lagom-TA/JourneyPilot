import { ArrowUpRight, Check, ChevronDown, Compass, FileCheck2, Map, MapPin, Pause, CircleAlert, Search, TrainFront, BedDouble } from "lucide-react";
import { type ThinkingStep } from "../types/messages";
import { dedupeToolSteps, describeToolStep, isNoResultSummary, isPublicActivityStep, toolResultText, toolStatusLabel } from "../model/toolDisplay";
import { isWorkExplanationStep, publicProgressText, researchGroups, workExplanationText, type ResearchGroup } from "../model/researchProgress";
import { deriveActivityTitle, getActivityStageIdForAgent, parseAgentRound, type ActivityStageId, type ActivityStageStatus } from "../model/agentStages";
import { AgentOrb } from "./AgentOrb";
import { cn } from "../../../lib/utils";
import React, { useEffect, useId, useState } from 'react';
import '../../../styles/generation.css';
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
    /** 工作台当前展示的四阶段；传入后组状态以阶段状态为准，不再按整 Run 推断。 */
    activityStage?: ActivityStageId;
    stageStatus?: ActivityStageStatus;
    activityFocus?: string;
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
function ToolActivity({ step, stopped, open, onOpenChange, visibleSummary }: {
    step: ThinkingStep;
    stopped: boolean;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    visibleSummary?: string;
}) {
    const display = describeToolStep(step);
    const result = toolResultText(step);
    const previews = (step.resultPreview || []).map(row => ({ title: publicProgressText(row.title), detail: publicProgressText(row.detail), url: safeUrl(row.url) })).filter(row => row.title);
    const running = display.status === 'running';
    const noResult = display.status === 'completed' && isNoResultSummary(result);
    // 折叠行只保留一次结论：进行中显示工具类别，结束后显示后端摘要。
    // 查询主题放在展开后的输入里，不在标题和详情重复。
    const headline = running || result === visibleSummary ? display.categoryLabel : result || display.actionText;
    const statusText = running && stopped ? '已停止' : noResult ? '无结果' : toolStatusLabel(display.status);
    const resultLine = running
        ? ''
        : result || (display.status === 'failed' ? '本次查询未完成，暂无可用结果。' : '无结果');
    // 折叠行已经显示结果时，展开详情不再重复同一句；只有“没有结果”这类
    // 限制说明才需要单独一行。
    const showResultLine = Boolean(resultLine && resultLine !== headline && resultLine !== visibleSummary);
    const hasDetails = display.inputs.length > 0 || previews.length > 0;
    const summary = <>
    <span className={cn('research-query-dot', running && !stopped && 'is-active', display.status === 'failed' && 'is-warning')}/>
    <span className="research-query-main min-w-0 flex-1"><span className="research-query-kind">{display.categoryLabel}</span>{headline !== display.categoryLabel && <span className="research-query-title" title={headline}>{headline}</span>}</span>
    <span className="research-query-status">{statusText}</span>
    {hasDetails && <ChevronDown size={14} className="research-disclosure-icon shrink-0"/>}
  </>;
    const detail = <div className="research-query-detail">
    <div className="research-tool-detail">
      {display.inputs.length > 0 && <div className="research-tool-field" data-detail-section="input">
        <dl className="research-tool-inputs">{display.inputs.map(field => <div key={`${field.label}-${field.value}`} className="research-tool-input-row">
            <dt className="research-tool-input-label">{field.label}</dt>
            <dd className="research-tool-input-value">{field.value}</dd>
          </div>)}</dl>
      </div>}
      <div className="research-tool-field" data-detail-section="result">
        {running
        ? <p className="research-tool-empty">正在处理，结果返回后会显示在这里。</p>
        : <>
          {showResultLine && <p className="research-tool-result-line">{resultLine}</p>}
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
  </div>;
    return <li className="research-query" data-testid="research-query" data-tool-id={step.toolCallId || step.id}>
    {hasDetails
        ? <details open={open} onToggle={(event) => {
                const next = event.currentTarget.open;
                if (next !== open)
                    onOpenChange(next);
            }}>
        <summary className="research-query-summary">{summary}</summary>
        {detail}
      </details>
        : <div className="research-query-summary">{summary}</div>}
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
    const [open, setOpen] = useState(layout !== 'workspace' && group.status === 'running');
    const previousStatus = React.useRef(group.status);
    const previousRunTerminal = React.useRef(runTerminal);
    React.useEffect(() => {
        const previous = previousStatus.current;
        previousStatus.current = group.status;
        if (layout === 'workspace') return;
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
    }, [group.status, group.steps, onClearTools, layout]);
    React.useEffect(() => {
        if (layout !== 'workspace' && runTerminal && !previousRunTerminal.current) {
            setOpen(false);
            onClearTools(group.steps.map(step => step.id));
        }
        previousRunTerminal.current = runTerminal;
    }, [group.steps, onClearTools, runTerminal, layout]);
    const Icon = ICONS[group.id as keyof typeof ICONS] || Compass;
    const activitySteps = dedupeToolSteps(group.steps);
    const tools = activitySteps.filter(s => s.isToolCall);
    const progressSteps = activitySteps.filter(s => !s.isToolCall && s.progressStatus);
    const runningTool = [...tools].reverse().find(s => s.toolStatus === 'running');
    const latestRunningProgress = [...progressSteps].reverse().find(s => s.progressStatus === 'running' && informativeProgressText(s.content));
    const latestCompletedProgress = [...progressSteps].reverse().find(s => s.progressStatus === 'completed' && informativeProgressText(s.content));
    const latestResult = [...tools].reverse().map(toolResultText).find(Boolean) || '';
    const latestWorkNote = [...group.steps].reverse().find(isWorkExplanationStep);
    const latestActivity = [...activitySteps].reverse().map(step => step.isToolCall
        ? step.toolStatus === 'running' ? describeToolStep(step).actionText : toolResultText(step)
        : isWorkExplanationStep(step) ? workExplanationText(step.content) : informativeProgressText(step.content)).find(Boolean);
    const summary = group.status === 'running'
        ? latestActivity || (runningTool ? describeToolStep(runningTool).actionText
            : informativeProgressText(latestRunningProgress?.content) || informativeProgressText(latestCompletedProgress?.content) || workExplanationText(latestWorkNote?.content) || latestResult
        )
        : informativeProgressText(latestCompletedProgress?.content) || latestResult;
    const workspace = layout === 'workspace';
    const summaryIsWorkNote = summary && summary === workExplanationText(latestWorkNote?.content);
    // 工具、公开说明与阶段里程碑按到达顺序渲染；同一工具调用只保留一条折叠行。
    const activityItems: Array<{
        key: string;
        kind: 'tool' | 'note' | 'milestone';
        step?: ThinkingStep;
        text?: string;
    }> = [];
    const seenToolIds = new Set<string>();
    const seenMilestones = new Set<string>();
    for (const step of activitySteps) {
        if (step.isToolCall) {
            const key = step.toolCallId || step.id;
            if (seenToolIds.has(key))
                continue;
            seenToolIds.add(key);
            activityItems.push({ key: `tool-${key}`, kind: 'tool', step });
            continue;
        }
        if (isWorkExplanationStep(step)) {
            const text = workExplanationText(step.content);
            if (text && (!workspace || text !== summary))
                activityItems.push({ key: `note-${step.id}`, kind: 'note', text });
            continue;
        }
        if (step.progressStatus === 'running')
            continue;
        if (group.status !== 'running' && isTransientStageActivity(step))
            continue;
        const text = informativeProgressText(step.content);
        if (!text || text === summary || seenMilestones.has(text))
            continue;
        seenMilestones.add(text);
        activityItems.push({ key: `milestone-${step.id}`, kind: 'milestone', text });
    }
    const hasDetails = activityItems.length > 0;
    if (workspace && duplicateTitle && !summary && !hasDetails && group.status !== 'failed') return null;
    const issues = tools.filter(s => s.toolStatus === 'failed' || s.toolStatus === 'capability_declared').length;
    const status = <span className={cn('research-agent-state', group.status === 'running' && 'is-active')}>
      {group.status === 'failed' ? <CircleAlert size={11}/> : group.status === 'completed' ? <Check size={11}/> : group.status === 'stopped' ? <Pause size={11}/> : <span className="research-status-dot"/>}
      {group.status === 'failed' ? '未完成' : group.status === 'running' ? '进行中' : group.status === 'stopped' ? '已停止' : '已结束'}
    </span>;
    const content = workspace ? <>
    <span className="research-agent-summary">
      <span className="research-agent-line">
        {!duplicateTitle && <span className="research-agent-title">{group.title}</span>}
        {status}
        {hasDetails && <ChevronDown size={15} className={cn('research-agent-chevron', open && 'rotate-180')} aria-hidden/>}
      </span>
      {summary && <span className="research-agent-update" data-testid="research-agent-update" title={summaryIsWorkNote ? '规划过程中的工作说明，不是已核实的旅行事实' : undefined}>{summary}</span>}
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
    return <section className={cn('research-agent', workspace && 'research-agent-flat', duplicateTitle && 'is-stage-group', group.status === 'running' && 'is-active', group.status === 'failed' && 'is-failed')} data-testid={`research-agent-${group.id}`} data-status={group.status}>
    {!hasDetails ? <div className="research-agent-heading">{content}</div>
            : <button type="button" className="research-agent-heading" aria-expanded={open} aria-controls={region} onClick={() => setOpen(v => !v)}>{content}</button>}
    {open && hasDetails && <div id={region} className="research-agent-body">
      <ol className="research-queries">
        {activityItems.map(item => item.kind === 'tool' && item.step
            ? <ToolActivity key={item.key} step={item.step} stopped={interrupted || group.status !== 'running'} open={openToolIds.has(item.step.id)} onOpenChange={(open) => onToolOpenChange(item.step!.id, open)} visibleSummary={workspace ? summary : undefined}/>
            : item.kind === 'note'
                ? <li key={item.key} className="research-work-note" data-testid="research-work-note">
                    <span className="research-work-note-label" title="规划过程中的工作说明，不是已核实的旅行事实">工作说明</span>
                    <span className="research-work-note-text">{item.text}</span>
                  </li>
                : <li key={item.key} className="research-milestone-row"><p className="research-milestone">{item.text}</p></li>)}
      </ol>
    </div>}
  </section>;
}
export const ThinkingChain: React.FC<ThinkingChainProps> = ({ steps, isGenerating, displayContent, isSynthesizing, pendingStatusText, variant = 'default', serverTotalMs, startedAt, regionId, layout = 'default', runStatus, gatePending = false, runKey, initiallyExpanded, forcedCollapsed = false, collapseKey, activityTitle, emptyText, activityStage, stageStatus, activityFocus }) => {
    const interrupted = variant === 'interrupted';
    // 工作台传入阶段状态后，“是否还在运行”只由该阶段决定；普通聊天不传，
    // 继续沿用整 Run 的旧口径。
    const stageActive = stageStatus === undefined || stageStatus === 'active';
    const live = isGenerating && !interrupted && stageActive;
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
        if (terminalStatus && layout !== 'workspace')
            setOpenToolIds(new Set());
    }, [terminalStatus, runScope, layout]);
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
    const scopedVisibleSteps = React.useMemo(() => steps.filter(step => (!activityStage || getActivityStageIdForAgent(step.agentName) === activityStage)
        && isPublicActivityStep(step)), [steps, activityStage]);
    // 生命周期用未过滤事件计算，展示内容再排除失败/内部行动。先删步骤会让
    // “running → 正常结果 → failed”被误判成仍在进行。工作台再按阶段过滤组，
    // 阶段状态是组状态的唯一收口。
    const groups = React.useMemo(() => researchGroups(steps, live, interrupted, stageStatus)
        .filter(group => !activityStage || group.stage === activityStage)
        .map(group => ({ ...group, steps: group.steps.filter(isPublicActivityStep) }))
        .filter(group => group.steps.length > 0 || group.status === 'failed')
        .sort((a, b) => {
            if (layout !== 'workspace') return 0;
            const rank = { failed: 0, running: 1, stopped: 2, completed: 3 };
            return rank[a.status] - rank[b.status];
        }), [steps, live, interrupted, activityStage, stageStatus, layout]);
    const focus = publicProgressText(activityFocus);
    const showFocus = focus && !scopedVisibleSteps.some(step => publicProgressText(step.content) === focus || toolResultText(step) === focus);
    const start = startedAt ? new Date(startedAt).getTime() : scopedVisibleSteps[0]?.timestamp.getTime();
    const ms = serverTotalMs ?? (live && start ? now - start : undefined);
    const elapsed = ms != null && Number.isFinite(ms) ? `${Math.max(0, Math.floor(ms / 1000))} 秒` : '';
    const derivedTitle = layout === 'workspace'
        ? deriveActivityTitle({ steps: scopedVisibleSteps, isStreaming: live, isSynthesizing, answerStarted: Boolean(displayContent?.trim()), runStatus, gatePending, interrupted })
        : interrupted ? '调研已停止' : isSynthesizing || (live && displayContent?.trim()) ? '正在整理旅行方案' : live ? (scopedVisibleSteps.length ? '正在为你调研' : '正在准备规划') : scopedVisibleSteps.length ? '调研记录' : '准备旅行查询';
    const title = activityTitle?.trim() || derivedTitle;
    const emptyMessage = emptyText?.trim()
        || (live ? publicProgressText(pendingStatusText) || '等待新的调研进展。'
            : stageStatus === 'done' ? '这个阶段没有留下可查看的行动记录。'
                : stageStatus === 'failed' ? '这个阶段没有完成。'
                    : stageStatus === 'stopped' ? '这个阶段已停止。'
                        : '本次调研没有留下可查看的过程记录。');
    const headingIcon = stageStatus === 'failed'
        ? <CircleAlert size={18}/>
        : stageStatus === 'stopped'
            ? <Pause size={18}/>
            : stageStatus === 'done'
                ? <FileCheck2 size={18}/>
                : live
                    ? <AgentOrb state={isSynthesizing ? 'composing' : 'searching'}/>
                    : stageStatus === 'active'
                        ? <Compass size={18}/>
                        : interrupted ? <Pause size={18}/> : <FileCheck2 size={18}/>;
    return <section className={cn('research-panel', layout === 'workspace' && 'research-panel-workspace')} data-testid="thinking-chain" data-run={runScope}>
    {layout === 'workspace' ? <div className="research-panel-heading" tabIndex={-1}>
      <h2 className="research-panel-title">{title}</h2>
      {elapsed && <span className="research-elapsed">{elapsed}</span>}
    </div> : <button type="button" className="research-panel-heading" aria-expanded={expanded} aria-controls={regionId} onClick={() => setExpanded(v => !v)}>
      {headingIcon}
      <span className="min-w-0 flex-1 text-left"><span className="research-panel-title">{title}</span></span>
      {elapsed && <span className="research-elapsed">{elapsed}</span>}
      <ChevronDown size={16} className={cn('research-agent-chevron', expanded && 'rotate-180')}/>
    </button>}
    {(layout === 'workspace' ? !forcedCollapsed : expanded) && <div id={regionId} className="research-panel-body">
      {showFocus && <p className="research-current-focus">{focus}</p>}
      {groups.length ? <div className="research-agent-list">{groups.map(group => <AgentCard key={`${runScope}-${group.id}`} group={group} interrupted={interrupted} layout={layout} openToolIds={openToolIds} onToolOpenChange={setToolOpen} onClearTools={clearTools} duplicateTitle={layout === 'workspace' && group.title === title} runTerminal={terminalStatus}/>)}</div>
                : <div className="research-empty"><Search size={18}/><p>{emptyMessage}</p></div>}
    </div>}
  </section>;
};
