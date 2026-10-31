import { Check, Loader2, Play, Square, Users } from 'lucide-react';
import { useReducedMotion } from 'motion/react';
import { useApp } from '../../../../app/state/AppContext';
import { useSendMessage } from '../../../../app/session/useSendMessage';
import { useStopRun } from '../../../../app/session/useStopRun';
import { derivePlanningStageSnapshot } from '../../model/travelProgress';
import { followupComposerState } from '../../model/followupComposer';
import { getActivityStageIdForAgent } from '../../../chat/model/agentStages';
import { TripBriefPlanGate } from '../planning/TripBriefPlanGate';
import { type PlanApprovalGate } from '../../types/planning';
import { ThinkingChain } from '../../../chat/components/ThinkingChain';
import { InputArea } from '../../../chat/components/InputArea';
import { cn } from '../../../../lib/utils';
import React from 'react';

const RESUME_TEXT = '继续上次被中断的规划';
type StageStatus = 'pending' | 'active' | 'done';

function tripDays(start: string, end: string): number {
  if (!start || !end) return 0;
  return Math.floor((new Date(`${end}T00:00:00`).getTime() - new Date(`${start}T00:00:00`).getTime()) / 86400000) + 1;
}

export const GenerationJourneyPanel: React.FC = () => {
  const { state, dispatch } = useApp();
  const { sendMessage } = useSendMessage();
  const { stopRun } = useStopRun();
  const [resuming, setResuming] = React.useState(false);
  const reducedMotion = Boolean(useReducedMotion());
  const identity = state.controlledTripIdentity;
  const runId = state.currentTripRunId;
  const lastAssistant = [...state.currentMessages].reverse().find((message) => message.role === 'assistant');
  const answerStarted = lastAssistant?.type !== 'error' && Boolean(lastAssistant?.content?.trim());
  const snapshot = derivePlanningStageSnapshot({
    steps: state.thinkingSteps,
    isStreaming: state.isStreaming,
    isSynthesizing: state.isSynthesizing,
    answerStarted,
    completed: state.currentTripRunStatus === 'completed',
  });
  const runStatus = state.currentTripRunStatus;
  const recovery = state.currentTripRunRecovery;
  const canResume = runStatus === 'interrupted' && recovery?.resumable === true;
  const gatePending = Boolean(state.planApprovalGate && state.planApprovalGate.status !== 'cancelled');
  const hadGateOnMount = React.useRef(gatePending);
  const [seenRun, setSeenRun] = React.useState<string | null>(gatePending ? runId : null);
  const [gateSnapshot, setGateSnapshot] = React.useState<PlanApprovalGate | null>(gatePending ? state.planApprovalGate : null);
  const previousGate = React.useRef({ pending: gatePending, runId, epoch: state.conversationEpoch });
  const handoffRef = React.useRef<HTMLDivElement>(null);
  const processPaneRef = React.useRef<HTMLDivElement>(null);
  const gatePaneRef = React.useRef<HTMLDivElement>(null);
  const followup = followupComposerState({
    runStatus,
    isStreaming: state.isStreaming,
    readOnly: state.currentTripRunReadOnly,
    gatePending,
    pendingIntake: Boolean(state.pendingGuidedIntake),
    pendingRouteConfirmation: Boolean(state.pendingRouteConfirmation),
    canResume,
  });

  React.useEffect(() => {
    if (gatePending && state.planApprovalGate) {
      setSeenRun(runId);
      setGateSnapshot(state.planApprovalGate);
      return;
    }
    const timer = window.setTimeout(
      () => setGateSnapshot(null),
      reducedMotion ? 0 : 320,
    );
    return () => window.clearTimeout(timer);
  }, [gatePending, reducedMotion, runId, state.planApprovalGate]);

  React.useEffect(() => {
    const previous = previousGate.current;
    previousGate.current = { pending: gatePending, runId, epoch: state.conversationEpoch };
    if (!previous.pending || gatePending || previous.runId !== runId || previous.epoch !== state.conversationEpoch)
      return;
    const focusCompact = () => {
      if (processPaneRef.current)
        (processPaneRef.current as HTMLElement & { inert: boolean }).inert = false;
      const active = document.activeElement;
      if (active && active !== document.body && !gatePaneRef.current?.contains(active)) return;
      handoffRef.current
        ?.querySelector<HTMLElement>('[data-testid="thinking-chain"] .research-panel-heading')
        ?.focus();
    };
    const timer = window.setTimeout(focusCompact, reducedMotion ? 100 : 340);
    return () => window.clearTimeout(timer);
  }, [gatePending, reducedMotion, runId, state.conversationEpoch]);

  React.useLayoutEffect(() => {
    // 先解除 inert，再交接焦点；延迟回调在门或 Run 更换时取消。
    processPaneRef.current && ((processPaneRef.current as HTMLElement & { inert: boolean }).inert = gatePending);
    gatePaneRef.current && ((gatePaneRef.current as HTMLElement & { inert: boolean }).inert = !gatePending);
    if (!gatePending) return;
    const timer = window.setTimeout(() => {
      gatePaneRef.current?.querySelector<HTMLElement>('#trip-brief-plan-gate-title, [data-testid="semantic-requirement-gate"] h2')?.focus();
    }, reducedMotion || state.planApprovalGate?.source === 'restored' ? 0 : 320);
    return () => window.clearTimeout(timer);
  }, [gatePending, gateSnapshot, reducedMotion, state.planApprovalGate?.revision, state.planApprovalGate?.source]);

  if (!identity || !runId) return null;

  const planning = snapshot.stages[0];
  const research = snapshot.stages[1];
  const synthesis = snapshot.stages[2];
  const itineraryTouched = state.thinkingSteps.some((step) => getActivityStageIdForAgent(step.agentName) === 'route');
  const completed = runStatus === 'completed';
  const synthesisStarted = synthesis.status === 'active' || completed;
  const routeStatus: StageStatus = completed || (state.isStreaming && synthesisStarted) ? 'done' : itineraryTouched ? research.status : 'pending';
  const researchStatus: StageStatus = completed || (state.isStreaming && (routeStatus !== 'pending' || synthesisStarted)) ? 'done' : research.status;
  const stages: Array<{ title: string; description: string; status: StageStatus }> = [
    { title: '整理旅行需求', description: '目的地、时间、同行人与旅行偏好', status: gatePending ? 'active' : planning.status },
    { title: '查找交通与住宿', description: '把城际衔接、市内交通和住宿放在一起考虑', status: researchStatus },
    { title: '安排每天路线', description: '让景点、美食与休息节奏顺路衔接', status: routeStatus },
    { title: '生成完整计划', description: '整理日程、地图、阅读版与费用参考', status: synthesis.status },
  ];
  const days = tripDays(identity.start_date, identity.end_date);
  const statusMessage = runStatus === 'failed'
    ? '这次规划没有完成，你可以回到新旅行重新尝试。'
    : runStatus === 'cancelled'
      ? '这次规划已取消。'
      : runStatus === 'interrupted'
        ? canResume ? '规划已中断，可以从最近的位置继续。' : '这次规划已中断。'
        : runStatus === 'cancel_requested'
          ? '正在停止这次规划。'
          : null;
  const progressTitle = runStatus === 'failed'
    ? '旅行规划未完成'
    : runStatus === 'cancelled'
      ? '旅行规划已取消'
      : runStatus === 'interrupted'
        ? '旅行规划已中断'
        : runStatus === 'cancel_requested'
          ? '正在停止规划'
          : runStatus === 'awaiting_input'
          ? '等待确认旅行需求'
          : runStatus === 'completed'
            ? '旅行规划已完成'
            : '正在规划你的旅行';

  const canStartOver = (runStatus === 'failed' || runStatus === 'cancelled' || (runStatus === 'interrupted' && !canResume));
  const runStopped = runStatus === 'failed' || runStatus === 'cancelled' || runStatus === 'interrupted' || runStatus === 'cancel_requested';
  const showActiveSweep = state.isStreaming && !gatePending && (runStatus === null || runStatus === 'running');
  const hasResearchActivity = state.thinkingSteps.some((step) => {
    const stage = getActivityStageIdForAgent(step.agentName);
    return stage === 'research' || stage === 'route' || stage === 'delivery';
  });
  const forceCompactProcess = seenRun !== runId && !hasResearchActivity && (state.isStreaming || gatePending);
  const effectiveGate = gatePending ? state.planApprovalGate : gateSnapshot?.runId === runId ? gateSnapshot : null;

  const resume = async () => {
    if (resuming || state.isStreaming) return;
    setResuming(true);
    try {
      await sendMessage(RESUME_TEXT, undefined, {
        resumeRunId: runId,
        route: 'trip_refinement',
        assistantPendingLabel: '正在从最近的位置继续',
      });
    } finally {
      setResuming(false);
    }
  };

  const startOver = () => {
    dispatch({ type: 'CLEAR_CHAT' });
    const url = new URL(window.location.href);
    url.searchParams.delete('session_id');
    url.searchParams.delete('run_id');
    url.searchParams.set('view', 'chat');
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  };

  return (
    <div className="generation-journey-panel" data-testid="generation-journey-panel">
        <div className="generation-planning-layout">
          <aside className="generation-planning-sidebar">
            <section className="generation-trip-card" aria-label="旅行信息">
              <div className="generation-trip-card-header">
                <div>
                  <p className="generation-trip-eyebrow">你的旅行</p>
                  <h1 tabIndex={-1} data-workspace-handoff-focus>
                    <span className="generation-trip-title-destinations" aria-label={`目的地顺序：${identity.destinations.map((place) => place.name).join('、')}`}>
                      {identity.destinations.map((place, index) => (
                        <span key={place.place_id} className={cn('generation-trip-title-segment', index === 0 && 'is-first')}>
                          <span className="generation-trip-title-index" aria-hidden>{index + 1}</span>
                          <span className="generation-trip-title-place">{place.name}</span>
                        </span>
                      ))}
                    </span>
                    {days > 0 && <span className="generation-trip-title-duration">{days} 日</span>}
                  </h1>
                </div>
                {state.isStreaming && (
                  <button type="button" data-testid="boarding-pass-stop" className="generation-stop-btn" onClick={() => void stopRun()} aria-label="停止生成">
                    <Square size={12} />停止
                  </button>
                )}
              </div>
              <dl className="generation-trip-card-meta">
                <div className="generation-trip-card-route">
                  <dt>行程</dt>
                  <dd><span>{identity.origin.name}出发</span><span className="generation-trip-card-date">{identity.start_date} — {identity.end_date}</span></dd>
                </div>
                <div className="generation-trip-card-party">
                  <dt><Users size={14} aria-hidden />同行</dt>
                  <dd>{identity.party.adults} 位成人{identity.party.children ? ` · ${identity.party.children} 位儿童` : ''}{identity.party.elderly_companions ? ' · 有长辈同行' : ''}{identity.party.accessibility_required ? ' · 需要无障碍安排' : ''}</dd>
                </div>
                <div className="generation-trip-card-style">
                  <dt>风格</dt>
                  <dd className="generation-trip-tags">
                    {[identity.style.primary, ...identity.style.secondary_interests].map((item) => <span key={item}>{item}</span>)}
                  </dd>
                </div>
              </dl>
            </section>

            <section className="generation-progress" data-active={showActiveSweep ? 'true' : 'false'} aria-label="旅行生成进度">
              <h2>{progressTitle}</h2>
              {statusMessage && <p role="alert" aria-live="polite">{statusMessage}</p>}
              <ol>
                {stages.map((stage, index) => (
                  <li key={stage.title} className={cn(`is-${stage.status}`)}>
                    <span className="generation-stage-mark" aria-hidden>
                      {stage.status === 'done' ? <Check size={14} /> : stage.status === 'active' ? <Loader2 size={14} className="generation-stage-spinner" /> : index + 1}
                    </span>
                    <div>
                      <h3>{stage.title}</h3>
                      <p>{stage.description}</p>
                      {index > 0 && stage.status === 'active' && state.tripSummaryCard?.currentFocus && <span>{state.tripSummaryCard.currentFocus}</span>}
                    </div>
                  </li>
                ))}
              </ol>
            </section>

            {(canResume || canStartOver) && !state.isStreaming && (
              <div className="generation-run-actions">
                {canStartOver && <button type="button" onClick={startOver}>返回新旅行</button>}
                {canResume && <button type="button" data-testid="boarding-pass-resume" onClick={() => void resume()} disabled={resuming}><Play size={14} />{resuming ? '正在继续' : '继续生成'}</button>}
              </div>
            )}
            {state.currentTripRunReadOnly && (
              <p className="generation-readonly-note" role="status">历史生成记录 · 只读</p>
            )}
          </aside>

          <main className={cn('generation-activity', gatePending && 'is-confirming')} aria-label="规划与调研动态">
            <div className="generation-activity-body">
              {lastAssistant?.type === 'error' && (
                <p role="alert" className="generation-activity-error">{lastAssistant.displayContent || lastAssistant.content}</p>
              )}
              <div
                ref={handoffRef}
                className={cn('generation-handoff', gatePending && 'is-gate', (reducedMotion || (gatePending && state.planApprovalGate?.source === 'restored')) && 'is-instant')}
                data-testid="generation-handoff"
                data-phase={gatePending ? 'gate' : 'process'}
              >
                <div
                  ref={processPaneRef}
                  className="generation-handoff-pane generation-handoff-process"
                  aria-hidden={gatePending}
                >
                  <div className="generation-handoff-pane-inner">
                    <ThinkingChain
                      steps={state.thinkingSteps}
                      isGenerating={state.isStreaming}
                      displayContent={lastAssistant?.displayContent}
                      isSynthesizing={state.isSynthesizing}
                      pendingStatusText={lastAssistant?.pendingStatusText}
                      variant={runStopped ? 'interrupted' : 'default'}
                      startedAt={lastAssistant?.timestamp}
                      regionId={`generation-thinking-${runId}`}
                      layout="workspace"
                      runStatus={runStatus}
                      gatePending={gatePending}
                      runKey={runId}
                      initiallyExpanded={hadGateOnMount.current ? false : undefined}
                      forcedCollapsed={forceCompactProcess}
                      collapseKey={gatePending ? `${state.planApprovalGate?.runId}:${state.planApprovalGate?.revision}` : undefined}
                    />
                  </div>
                </div>
                <div
                  ref={gatePaneRef}
                  className="generation-handoff-pane generation-handoff-gate"
                  aria-hidden={!gatePending}
                >
                  <div className="generation-handoff-pane-inner">
                    {effectiveGate && (
                      <TripBriefPlanGate
                        key={`${effectiveGate.runId}:${effectiveGate.revision}`}
                        variant="workspace"
                        gateOverride={effectiveGate}
                      />
                    )}
                  </div>
                </div>
              </div>
            </div>
            {followup.visible && (
              <div className="generation-followup" data-testid="generation-followup-composer">
                <div className="generation-followup-inner">
                  <p className="generation-followup-hint">{followup.hint}</p>
                  {/* 沿用交付后调整的输入与发送链：不另带 run_id 或 route，交给现有会话分流。 */}
                  <InputArea minimal showCompaction={false} autoFocus={false} placeholder={followup.placeholder} />
                </div>
              </div>
            )}
          </main>
        </div>
    </div>
  );
};
