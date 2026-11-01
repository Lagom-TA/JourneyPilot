import { CalendarDays, Check, Loader2, Play, Sparkles, Square, Users } from 'lucide-react';
import { useReducedMotion } from 'motion/react';
import { useApp } from '../../../../app/state/AppContext';
import { useSendMessage } from '../../../../app/session/useSendMessage';
import { useStopRun } from '../../../../app/session/useStopRun';
import { derivePlanningStageSnapshot } from '../../model/travelProgress';
import { followupComposerState } from '../../model/followupComposer';
import {
  filterStepsForActivityStage,
  getActivityStageIdForAgent,
  latestActivityStageId,
  latestActivityStageWithSteps,
  type ActivityStageId,
} from '../../../chat/model/agentStages';
import { TripBriefPlanGate } from '../planning/TripBriefPlanGate';
import { UnderstandingQuestionsCard } from './UnderstandingQuestionsCard';
import { type PlanApprovalGate } from '../../types/planning';
import { ThinkingChain } from '../../../chat/components/ThinkingChain';
import { InputArea } from '../../../chat/components/InputArea';
import { cn } from '../../../../lib/utils';
import React from 'react';

const RESUME_TEXT = '继续上次被中断的规划';
type StageStatus = 'pending' | 'active' | 'done';
const STAGE_ACTIVITY_TITLES: Record<ActivityStageId, string> = {
  requirements: '整理旅行需求',
  research: '查找旅行资料',
  route: '安排每天路线',
  delivery: '生成完整计划',
};

function tripDays(start: string, end: string): number {
  if (!start || !end) return 0;
  return Math.floor((new Date(`${end}T00:00:00`).getTime() - new Date(`${start}T00:00:00`).getTime()) / 86400000) + 1;
}

export const GenerationJourneyPanel: React.FC = () => {
  const { state, dispatch } = useApp();
  const { sendMessage } = useSendMessage();
  const { stopRun } = useStopRun();
  const [resuming, setResuming] = React.useState(false);
  const [selectedStage, setSelectedStage] = React.useState<ActivityStageId | null>(null);
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
  const hasUnresolved = Boolean(state.deliveryBundle?.report_projection.document?.unresolved.length);
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
  // 阶段选择只属于当前 Run；换 Run 或开启新会话轮次时回到“只跟随最新阶段”。
  React.useEffect(() => {
    setSelectedStage(null);
  }, [runId, state.conversationEpoch]);
  const understandingPending = Boolean(
    state.understandingQuestions && state.understandingQuestions.runId === runId,
  );
  const followup = followupComposerState({
    runStatus,
    isStreaming: state.isStreaming,
    readOnly: state.currentTripRunReadOnly,
    gatePending,
    pendingUnderstanding: understandingPending,
    pendingRouteConfirmation: Boolean(state.pendingRouteConfirmation),
    canResume,
    hasUnresolved,
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
      gatePaneRef.current?.querySelector<HTMLElement>('#trip-brief-plan-gate-title')?.focus();
    }, reducedMotion || state.planApprovalGate?.source === 'restored' ? 0 : 320);
    return () => window.clearTimeout(timer);
  }, [gatePending, gateSnapshot, reducedMotion, state.planApprovalGate?.revision, state.planApprovalGate?.source]);

  if (!runId) return null;

  const planning = snapshot.stages[0];
  const research = snapshot.stages[1];
  const synthesis = snapshot.stages[2];
  const itineraryTouched = state.thinkingSteps.some((step) => getActivityStageIdForAgent(step.agentName) === 'route');
  const completed = runStatus === 'completed';
  const synthesisStarted = synthesis.status === 'active' || completed;
  const routeStatus: StageStatus = completed || (state.isStreaming && synthesisStarted) ? 'done' : itineraryTouched ? research.status : 'pending';
  const researchStatus: StageStatus = completed || (state.isStreaming && (routeStatus !== 'pending' || synthesisStarted)) ? 'done' : research.status;
  const stages: Array<{ id: ActivityStageId; title: string; description: string; status: StageStatus }> = [
    { id: 'requirements', title: STAGE_ACTIVITY_TITLES.requirements, description: '目的地、时间、同行人与旅行偏好', status: gatePending || understandingPending ? 'active' : planning.status },
    { id: 'research', title: STAGE_ACTIVITY_TITLES.research, description: '按目的地、交通、住宿的顺序调研并保留充分备选', status: researchStatus },
    { id: 'route', title: STAGE_ACTIVITY_TITLES.route, description: '让景点、美食与休息节奏顺路衔接', status: routeStatus },
    { id: 'delivery', title: STAGE_ACTIVITY_TITLES.delivery, description: '整理日程、地图、阅读版与费用参考', status: synthesis.status },
  ];
  const days = identity ? tripDays(identity.start_date, identity.end_date) : 0;
  const styleTags = identity
    ? [identity.style.primary, ...identity.style.secondary_interests].filter(Boolean)
    : [];
  const partyText = identity
    ? `${identity.party.adults} 位成人${identity.party.children ? ` · ${identity.party.children} 位儿童` : ''}${identity.party.elderly_companions ? ' · 有长辈同行' : ''}${identity.party.accessibility_required ? ' · 需要无障碍安排' : ''}`
    : '';
  // 身份确认前展示最初的旅行设想；后续回答与补充不顶掉原文。
  const firstUserMessage = state.currentMessages.find((message) => message.role === 'user');
  const ideaText = firstUserMessage?.displayContent || firstUserMessage?.content || '';
  const latestStage = latestActivityStageId({
    steps: state.thinkingSteps,
    isStreaming: state.isStreaming,
    isSynthesizing: state.isSynthesizing,
    answerStarted,
    runStatus,
    gatePending,
  });
  const latestPopulatedStage = latestActivityStageWithSteps(state.thinkingSteps);
  const latestStageHasSteps = latestStage ? filterStepsForActivityStage(state.thinkingSteps, latestStage).length > 0 : false;
  // 完成或开始输出时最新阶段是交付，但历史 Run 可能只有研究记录；此时退到最近一个有内容的阶段。
  const activityStage = selectedStage ?? (latestStage && latestStageHasSteps ? latestStage : latestPopulatedStage);
  const activitySteps = activityStage ? filterStepsForActivityStage(state.thinkingSteps, activityStage) : state.thinkingSteps;
  const activityTitle = understandingPending
    ? '等待你的回答'
    : selectedStage
      ? STAGE_ACTIVITY_TITLES[selectedStage]
      : undefined;
  const emptyActivityText = selectedStage ? `「${STAGE_ACTIVITY_TITLES[selectedStage]}」阶段暂无行动记录。` : undefined;
  const hideEmptyProcess = state.thinkingSteps.length === 0
    && !state.isStreaming
    && (runStatus === 'failed' || runStatus === 'cancelled' || runStatus === 'interrupted');
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
          ? understandingPending
            ? '等待你的回答'
            : '等待确认研究方案'
          : runStatus === 'completed'
            ? hasUnresolved ? '部分行程尚未安排' : '旅行规划已完成'
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
                  {identity ? (
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
                  ) : (
                    <h1 tabIndex={-1} data-workspace-handoff-focus className="generation-trip-title-idea">
                      <span>{ideaText || '正在理解你的旅行想法'}</span>
                    </h1>
                  )}
                </div>
                {state.isStreaming && (
                  <button type="button" data-testid="boarding-pass-stop" className="generation-stop-btn" onClick={() => void stopRun()} aria-label="停止生成">
                    <Square size={12} />停止
                  </button>
                )}
              </div>
              {identity ? (
                <div className="generation-trip-card-meta">
                  <div
                    className="generation-trip-fact"
                    role="group"
                    aria-label={`出发地 ${identity.origin.name}，${identity.start_date} 至 ${identity.end_date}${days > 0 ? `，共 ${days} 天` : ''}`}
                  >
                    <CalendarDays size={14} aria-hidden />
                    <span className="generation-trip-fact-value">
                      <span>{identity.origin.name}出发</span>
                      <span className="generation-trip-card-date">{identity.start_date} — {identity.end_date}</span>
                    </span>
                  </div>
                  <div className="generation-trip-fact" role="group" aria-label={`同行 ${partyText}`}>
                    <Users size={14} aria-hidden />
                    <span className="generation-trip-fact-value">{partyText}</span>
                  </div>
                  {styleTags.length > 0 && (
                    <div className="generation-trip-fact generation-trip-fact-style" role="group" aria-label={`旅行风格 ${styleTags.join('、')}`}>
                      <Sparkles size={14} aria-hidden />
                      <span className="generation-trip-tags">
                        {styleTags.map((item) => <span key={item}>{item}</span>)}
                      </span>
                    </div>
                  )}
                </div>
              ) : (
                <div className="generation-trip-card-meta">
                  <p className="generation-trip-fact-pending" role="status">
                    基础信息正在确认，缺什么模型会直接问你。
                  </p>
                </div>
              )}
            </section>

            <section className="generation-progress" data-active={showActiveSweep ? 'true' : 'false'} aria-label="旅行生成进度">
              <h2>{progressTitle}</h2>
              {statusMessage && <p role="alert" aria-live="polite">{statusMessage}</p>}
              <ol>
                {stages.map((stage, index) => {
                  const selected = selectedStage === stage.id;
                  return (
                    <li key={stage.id} className={cn(`is-${stage.status}`, selected && 'is-selected')}>
                      <h3 className="generation-stage-heading">
                        <button
                          type="button"
                          className="generation-stage-button"
                          aria-pressed={selected}
                          onClick={() => setSelectedStage((current) => current === stage.id ? null : stage.id)}
                        >
                          <span className="generation-stage-mark" aria-hidden>
                            {stage.status === 'done' ? <Check size={14} /> : stage.status === 'active' ? <Loader2 size={14} className="generation-stage-spinner" /> : index + 1}
                          </span>
                          <span className="generation-stage-copy">
                            <span className="generation-stage-title">{stage.title}</span>
                            <span className="generation-stage-description">{stage.description}</span>
                            {index > 0 && stage.status === 'active' && state.tripSummaryCard?.currentFocus && <span className="generation-stage-focus">{state.tripSummaryCard.currentFocus}</span>}
                          </span>
                        </button>
                      </h3>
                    </li>
                  );
                })}
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
                    {!hideEmptyProcess && (
                      <ThinkingChain
                        steps={activitySteps}
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
                        activityTitle={activityTitle}
                        emptyText={emptyActivityText}
                        initiallyExpanded={hadGateOnMount.current ? false : undefined}
                        forcedCollapsed={forceCompactProcess}
                        collapseKey={gatePending ? `${state.planApprovalGate?.runId}:${state.planApprovalGate?.revision}` : undefined}
                      />
                    )}
                    {understandingPending && state.understandingQuestions && (
                      <UnderstandingQuestionsCard
                        runId={state.understandingQuestions.runId}
                        revision={state.understandingQuestions.revision}
                        approvalToken={state.understandingQuestions.approvalToken}
                        questions={state.understandingQuestions.questions}
                      />
                    )}
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
