import { AnimatePresence, m } from "motion/react";
import { CircleAlert, CheckCircle2, ChevronDown, Loader2, Play, Route, Square } from "lucide-react";
import { useApp } from "../../../../app/state/AppContext";
import { useSendMessage } from "../../../../app/session/useSendMessage";
import { useStopRun } from "../../../../app/session/useStopRun";
import { BrandMark } from "../../../../app/components/BrandMark";
import { AgentOrb } from "../../../chat/components/AgentOrb";
import { TRANSPORT_MODE_ICONS } from "../../model/transportPresentation";
import { selectPrimaryLongDistanceMode } from "../../model/itineraryPresentation";
import { derivePlanningStageSnapshot } from "../../model/travelProgress";
import { deriveOrbState } from "../../../chat/model/orbState";
import { cn } from "../../../../lib/utils";
import { READOUT_LABEL } from "../../../../lib/typography";
import { duration, easing } from "../../../../lib/motion";
import { isTripRunActive, isTripRunAwaitingInput } from "../../types/runs";
import React from 'react';
const RESUME_TEXT = '继续上次被中断的规划';
function days(start: string, end: string): number {
    if (!start || !end)
        return 0;
    return Math.floor((new Date(`${end}T00:00:00`).getTime() - new Date(`${start}T00:00:00`).getTime()) / 86400000) + 1;
}
export const ResearchBoardingPass: React.FC = () => {
    const { state } = useApp();
    const { stopRun } = useStopRun();
    const { sendMessage } = useSendMessage();
    const [expanded, setExpanded] = React.useState(true);
    const [flashing, setFlashing] = React.useState(false);
    const [resuming, setResuming] = React.useState(false);
    const identity = state.controlledTripIdentity;
    const card = state.tripSummaryCard;
    const runId = state.currentTripRunId;
    const gateActive = Boolean(state.planApprovalGate);
    React.useEffect(() => setExpanded(true), [runId]);
    const prevGateRef = React.useRef(gateActive);
    React.useEffect(() => {
        if (gateActive && !prevGateRef.current)
            setExpanded(false);
        else if (!gateActive && prevGateRef.current)
            setExpanded(true);
        prevGateRef.current = gateActive;
    }, [gateActive]);
    React.useEffect(() => {
        if (state.boardingPassFlash === 0)
            return;
        setExpanded(true);
        setFlashing(true);
        const timer = window.setTimeout(() => setFlashing(false), 1400);
        return () => window.clearTimeout(timer);
    }, [state.boardingPassFlash]);
    const lastAssistant = [...state.currentMessages].reverse().find((message) => message.role === 'assistant');
    const answerStarted = Boolean(lastAssistant?.content?.trim());
    const snapshot = derivePlanningStageSnapshot({ steps: state.thinkingSteps, isStreaming: state.isStreaming, isSynthesizing: state.isSynthesizing, answerStarted });
    const runStatus = state.currentTripRunStatus;
    const recovery = state.currentTripRunRecovery;
    const interruptedByShutdown = runStatus === 'interrupted' && recovery !== null;
    const canResume = runStatus === 'interrupted' && recovery?.resumable === true;
    const bundle = state.deliveryBundle?.manifest.run_id === runId ? state.deliveryBundle : null;
    const completed = runStatus === 'completed' && bundle !== null;
    const active = isTripRunActive(runStatus);
    const awaiting = isTripRunAwaitingInput(runStatus);
    const orbState = deriveOrbState(state.thinkingSteps, {
        isStreaming: state.isStreaming,
        isSynthesizing: state.isSynthesizing,
        answerStarted,
        awaitingInput: awaiting,
    });
    const statusMessage = state.isStreaming
        ? null
        : completed
            ? '旅行方案已生成'
            : runStatus === 'completed'
                ? '方案已生成，结果暂时无法加载'
                : runStatus === 'failed'
                    ? '本次规划未完成'
                    : runStatus === 'cancelled'
                        ? '本次规划已取消'
                        : runStatus === 'interrupted'
                            ? (canResume
                                ? '上次运行被程序关闭中断，可继续'
                                : interruptedByShutdown
                                    ? '上次运行被中断，无法继续'
                                    : '运行已中断，可恢复')
                            : runStatus === 'cancel_requested'
                                ? '正在停止'
                                : null;
    const stages = snapshot.stages;
    const activeIndex = completed && !state.isStreaming
        ? stages.length
        : Math.min(stages.length - 1, stages.filter((stage) => stage.status === 'done').length);
    const resume = async () => {
        if (!runId || resuming || state.isStreaming)
            return;
        setResuming(true);
        try {
            await sendMessage(RESUME_TEXT, undefined, {
                resumeRunId: runId,
                route: 'trip_refinement',
                assistantPendingLabel: '正在从最近检查点继续',
            });
        }
        finally {
            setResuming(false);
        }
    };
    if (!runId || !identity)
        return null;
    const arrival = identity.destinations.map((item) => item.name).join(' → ');
    const durationDays = days(identity.start_date, identity.end_date);
    const party = `${identity.party.adults} 成人${identity.party.children ? ` · ${identity.party.children} 儿童` : ''}`;
    const style = identity.style.primary;
    const primaryMode = bundle ? selectPrimaryLongDistanceMode(bundle.workspace.itinerary) : null;
    const RouteGlyph = primaryMode ? TRANSPORT_MODE_ICONS[primaryMode] : Route;
    const stageShort = statusMessage || (awaiting ? '等待确认' : `${stages[Math.min(activeIndex, stages.length - 1)].label}中`);
    const stageLabel = statusMessage || (awaiting
        ? (state.planApprovalGate ? '等待确认调研计划' : '等待补充信息')
        : (card?.currentFocus?.trim() || stageShort));
    const statusTone = completed
        ? 'text-success'
        : runStatus === 'failed'
            ? 'text-error'
            : 'text-ink-secondary';
    return (<m.div className="mx-auto w-full max-w-5xl" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: duration.base, ease: easing.decelerate }}>
      <div className="rounded-card shadow-sm">
        <section aria-label="旅行简报" data-flashing={flashing ? 'true' : undefined} className={cn('research-ticket w-full overflow-hidden rounded-card border bg-panel text-ink transition-[border-color] duration-base ease-standard', flashing ? 'border-accent' : 'border-stroke')}>

          <header className="flex items-center gap-3 px-4 py-3 sm:px-5">
            <BrandMark size={20} className="shrink-0"/>
            <div className="min-w-0 flex-1">
              <p className={cn(READOUT_LABEL, 'text-ink-muted')}>行程登机牌</p>
              <h2 className="mt-0.5 truncate text-sm font-semibold text-ink">
                <span className="text-chart">{identity.origin.name}</span> → {arrival}
                <span className="ml-2 font-normal text-ink-secondary">{durationDays} 天 {durationDays - 1} 晚</span>
              </h2>
            </div>
            {!expanded && (<span className="hidden shrink-0 items-center gap-1.5 rounded-label bg-surface px-2.5 py-1 font-mono text-[11px] text-ink-secondary sm:inline-flex">
                {state.isStreaming || active || runStatus === 'cancel_requested' || awaiting ? (<AgentOrb state={orbState} size={20}/>) : completed ? (<CheckCircle2 size={12} className="text-success"/>) : runStatus === 'failed' ? (<CircleAlert size={12} className="text-error"/>) : (<Square size={12} className="text-ink-muted"/>)}
                {stageShort}
              </span>)}



            {canResume && !state.isStreaming && (<button type="button" data-testid="boarding-pass-resume" onClick={() => void resume()} disabled={resuming} aria-label="从最近检查点继续这次规划" className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-card border border-accent/40 bg-accent/10 px-3 text-xs font-semibold text-accent transition-colors hover:border-accent/60 hover:bg-accent/[0.16] disabled:opacity-60">
                {resuming ? <Loader2 size={12} className="animate-spin"/> : <Play size={12}/>}
                继续
              </button>)}
            {state.isStreaming && (<button type="button" data-testid="boarding-pass-stop" onClick={() => void stopRun()} aria-label="停止本次规划" className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-card border border-error/35 bg-error/10 px-3 text-xs font-semibold text-error transition-colors hover:border-error/55 hover:bg-error/[0.16]">
                <Square size={12}/>
                停止
              </button>)}
            <button type="button" aria-expanded={expanded} aria-label={expanded ? '收起旅行简报' : '展开旅行简报'} onClick={() => setExpanded((value) => !value)} className="inline-flex min-h-10 shrink-0 items-center gap-1 rounded-card border border-stroke px-2.5 text-xs text-ink-secondary hover:border-accent/40 hover:text-ink">
              {expanded ? '收起' : '展开'}
              <ChevronDown size={14} className={cn('transition-transform', expanded && 'rotate-180')}/>
            </button>
          </header>

          <AnimatePresence initial={false}>
            {expanded && (<m.div initial={{ height: 0, opacity: 0 }} animate={{
                height: 'auto',
                opacity: 1,
                transition: { duration: duration.slow, ease: easing.decelerate },
            }} exit={{
                height: 0,
                opacity: 0,
                transition: { duration: duration.base, ease: easing.accelerate },
            }} className="overflow-hidden border-t border-stroke/60">

                <div className="px-4 pb-5 pt-4 sm:px-6">
                  <div className="flex items-center gap-3 sm:gap-6">
                    <div className="min-w-0 flex-1">
                      <p className={cn(READOUT_LABEL, 'text-ink-muted')}>出发 · FROM</p>

                      <p className="mt-1 break-words text-xl font-semibold text-ink">{identity.origin.name}</p>
                    </div>
                    <div className="flex shrink-0 flex-col items-center text-chart" aria-hidden>
                      <RouteGlyph size={18}/>
                      <span className="mt-1.5 block h-px w-12 border-t border-dashed border-stroke sm:w-20"/>
                    </div>
                    <div className="min-w-0 flex-1 text-right">
                      <p className={cn(READOUT_LABEL, 'text-ink-muted')}>抵达 · TO</p>
                      <p className="mt-1 break-words text-xl font-semibold text-ink">{arrival}</p>
                    </div>
                  </div>

                  <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4">
                    <TicketField className="col-span-2" label="日期 · DATE" value={`${identity.start_date} → ${identity.end_date}`}/>
                    <TicketField label="同行 · PARTY" value={party}/>
                    <TicketField label="风格 · STYLE" value={style}/>
                  </dl>

                  {(identity.party.elderly_companions || identity.party.accessibility_required || identity.style.secondary_interests.length > 0 || (card?.priorities?.length ?? 0) > 0) && (<div className="mt-4 flex flex-wrap gap-1.5">
                      {identity.style.secondary_interests.map((item) => <Tag key={item}>{item}</Tag>)}
                      {card?.priorities?.map((item) => <Tag key={item}>{item}</Tag>)}
                      {identity.party.elderly_companions && <Tag>老人同行</Tag>}
                      {identity.party.accessibility_required && <Tag>需要无障碍</Tag>}
                    </div>)}
                </div>


                <div className="ticket-perf mx-4 sm:mx-6"/>


                <div className="flex flex-wrap items-center gap-x-3 gap-y-2 bg-surface/40 px-4 py-3 sm:px-6">
                  <span className={cn(READOUT_LABEL, 'shrink-0 text-ink-muted')}>当前进度</span>
                  {statusMessage ? (<p className={cn('inline-flex items-center gap-1.5 text-sm font-medium', statusTone)}>
                      {completed ? <CheckCircle2 size={14}/> : runStatus === 'failed' ? <CircleAlert size={14}/> : <Square size={12}/>}
                      {statusMessage}
                    </p>) : (<>

                      <AgentOrb state={orbState} size={20} paused={!active && !awaiting && !state.isStreaming}/>
                      <span className="text-sm font-medium text-ink">{stageLabel}</span>
                      <span className="ml-auto flex items-center gap-1" aria-label={`阶段 ${Math.min(activeIndex + 1, stages.length)} / ${stages.length}`}>
                        {stages.map((stage, index) => {
                    const status = index < activeIndex ? 'done' : index === activeIndex && active ? 'active' : 'pending';
                    return (<span key={stage.id} className="flex h-1.5 w-6 items-center justify-start">
                              <span className={cn('h-1.5 w-6 origin-left rounded-full', 'transition-[transform,background-color] duration-base ease-standard', status === 'active' ? 'scale-x-100 bg-accent' : 'scale-x-50', status === 'done' && 'bg-success', status === 'pending' && 'bg-stroke')}/>
                            </span>);
                })}
                      </span>
                    </>)}
                </div>

              </m.div>)}
          </AnimatePresence>
        </section>
      </div>
    </m.div>);
};
const TicketField: React.FC<{
    label: string;
    value: string;
    className?: string;
}> = ({ label, value, className }) => (<div className={cn('min-w-0', className)}>
    <dt className={cn(READOUT_LABEL, 'text-ink-muted')}>{label}</dt>
    <dd className="mt-0.5 break-words font-mono text-sm font-medium tabular-nums text-ink">{value}</dd>
  </div>);
const Tag: React.FC<React.PropsWithChildren> = ({ children }) => (<span className="rounded-label bg-surface px-2.5 py-1 text-xs text-ink-secondary">{children}</span>);
