import { Check, CircleAlert, Loader2, Pause, Play, Square } from 'lucide-react';
import { useReducedMotion } from 'motion/react';
import { duration, milliseconds } from '../../../../lib/motion';
import { useApp } from '../../../../app/state/AppContext';
import { useResumeRun } from '../../../../app/session/useResumeRun';
import { useStopRun } from '../../../../app/session/useStopRun';
import { followupComposerState } from '../../model/followupComposer';
import {
  deriveActivityStages,
  getActivityStageIdForAgent,
  type ActivityStageId,
  type ActivityStageStatus,
} from '../../../chat/model/agentStages';
import { TripBriefPlanGate } from '../planning/TripBriefPlanGate';
import { UnderstandingQuestionsCard } from './UnderstandingQuestionsCard';
import { type PlanApprovalGate } from '../../types/planning';
import { planGateFromRunEvents } from '../../model/planApprovalGate';
import { getTripRunEventWindow } from '../../api/runs';
import { isTripRunResumeAvailable } from '../../types/runs';
import { ThinkingChain } from '../../../chat/components/ThinkingChain';
import { InputArea } from '../../../chat/components/InputArea';
import { getChatErrorGuidance } from '../../../chat/model/chatErrorGuidance';
import { cn } from '../../../../lib/utils';
import React from 'react';
import '../../../../styles/generation.css';

function generationErrorText(raw: string): string {
  const trimmed = raw.trim();
  if (/^请求失败\s*[：:]|^SSE\s|^\d{3}\b|delivery_integrity_projection_failure|identity_locked|failed to fetch|networkerror/i.test(trimmed)) {
    return getChatErrorGuidance(trimmed, 'fault').description;
  }
  return trimmed;
}

const STAGE_ACTIVITY_TITLES: Record<ActivityStageId, string> = {
  requirements: '整理旅行需求',
  research: '查找旅行资料',
  route: '安排每天路线',
  delivery: '生成完整计划',
};
const STAGE_LABELS: Record<ActivityStageId, string> = { requirements: '需求', research: '研究', route: '路线', delivery: '成稿' };

function tripDays(start: string | null, end: string | null): number {
  if (!start || !end) return 0;
  return Math.floor((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000) + 1;
}

export const GenerationJourneyPanel: React.FC = () => {
  const { state, dispatch } = useApp();
  const { stopRun } = useStopRun();
  const [selectedStage, setSelectedStage] = React.useState<ActivityStageId | null>(null);
  const reducedMotion = Boolean(useReducedMotion());
  const identity = state.controlledTripIdentity;
  const runId = state.currentTripRunId;
  const { resume, resuming } = useResumeRun(runId);
  // 恢复或查看历史 Run 时，正文和错误提示只能取当前 Run 的助手消息。
  // 等待首页请求的首个事件时，临时助手消息尚未归属 Run。
  const runMessages = runId
    ? state.currentMessages.filter((message) => message.runId === runId)
    : state.homeSubmissionPending ? state.currentMessages : [];
  const lastAssistant = [...runMessages].reverse().find((message) => message.role === 'assistant');
  const pendingUserMessage = state.homeSubmissionPending
    ? [...state.currentMessages].reverse().find((message) => message.role === 'user')
    : null;
  const answerStarted = lastAssistant?.type !== 'error' && Boolean(lastAssistant?.content?.trim());
  const runStatus = state.currentTripRunStatus;
  const recovery = state.currentTripRunRecovery;
  const canResume = isTripRunResumeAvailable({
    status: runStatus,
    recovery,
    readOnly: state.currentTripRunReadOnly,
    isStreaming: state.isStreaming || resuming,
  });
  const gatePending = Boolean(state.planApprovalGate && state.planApprovalGate.status !== 'cancelled');
  const hadGateOnMount = React.useRef(gatePending);
  const [seenRun, setSeenRun] = React.useState<string | null>(gatePending ? runId : null);
  const [gateSnapshot, setGateSnapshot] = React.useState<PlanApprovalGate | null>(gatePending ? state.planApprovalGate : null);
  // 方案门关闭后仍保留最后一版，供用户点回“需求”阶段查看确认过的研究方案。
  const [stagePlan, setStagePlan] = React.useState<PlanApprovalGate | null>(null);
  const stagePlanLoadKey = React.useRef<string | null>(null);
  const previousGate = React.useRef({ pending: gatePending, runId, epoch: state.conversationEpoch });
  const handoffRef = React.useRef<HTMLDivElement>(null);
  const processPaneRef = React.useRef<HTMLDivElement>(null);
  const gatePaneRef = React.useRef<HTMLDivElement>(null);
  // 阶段选择只属于当前 Run；换 Run 或开启新会话轮次时回到“只跟随最新阶段”。
  React.useEffect(() => {
    setSelectedStage(null);
    setStagePlan(null);
    stagePlanLoadKey.current = null;
  }, [runId, state.conversationEpoch]);
  const understandingPending = Boolean(
    runStatus === 'awaiting_input' && state.understandingQuestions && state.understandingQuestions.runId === runId,
  );
  // 阶段导航与任务区共用状态投影，过滤后的事件只用于展示当前阶段内容。
  const stageProjection = deriveActivityStages(state.thinkingSteps, {
    isStreaming: state.isStreaming,
    isSynthesizing: state.isSynthesizing,
    answerStarted,
    runStatus,
    gatePending,
    understandingPending,
  });
  const followup = followupComposerState({
    runStatus,
    isStreaming: state.isStreaming,
    hasDelivery: state.deliveryBundle !== null,
    readOnly: state.currentTripRunReadOnly,
    gatePending,
    pendingUnderstanding: understandingPending,
    pendingRouteConfirmation: Boolean(state.pendingRouteConfirmation),
    canResume,
  });

  React.useEffect(() => {
    if (gatePending && state.planApprovalGate) {
      setSeenRun(runId);
      setGateSnapshot(state.planApprovalGate);
      setStagePlan(state.planApprovalGate);
      return;
    }
    const timer = window.setTimeout(
      () => setGateSnapshot(null),
      reducedMotion ? 0 : milliseconds(duration.slow),
    );
    return () => window.clearTimeout(timer);
  }, [gatePending, reducedMotion, runId, state.planApprovalGate]);

  // 刷新或打开历史 Run 后没有实时方案快照，点时从持久事件中取回最近一次计划门。
  React.useEffect(() => {
    if (selectedStage !== 'requirements' || stagePlan?.runId === runId || gatePending || understandingPending || !runId)
      return;
    const loadKey = `${state.conversationEpoch}:${runId}`;
    if (stagePlanLoadKey.current === loadKey)
      return;
    stagePlanLoadKey.current = loadKey;
    let cancelled = false;
    getTripRunEventWindow(runId, {
      sessionId: state.currentSessionId,
      afterSequence: 0,
      limit: 200,
    })
      .then((window) => {
        if (cancelled)
          return;
        const plan = planGateFromRunEvents(window.events, runId);
        if (plan)
          setStagePlan(plan);
      })
      .catch(() => {
        // 事件缺失时保留阶段行动记录，不阻断工作台。
      });
    return () => {
      cancelled = true;
    };
  }, [selectedStage, stagePlan, gatePending, understandingPending, runId, state.conversationEpoch, state.currentSessionId]);

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
    const timer = window.setTimeout(focusCompact, reducedMotion ? 0 : milliseconds(duration.slow));
    return () => window.clearTimeout(timer);
  }, [gatePending, reducedMotion, runId, state.conversationEpoch]);

  React.useLayoutEffect(() => {
    // 先解除 inert，再交接焦点；延迟回调在门或 Run 更换时取消。
    if (processPaneRef.current)
      (processPaneRef.current as HTMLElement & { inert: boolean }).inert = gatePending;
    if (gatePaneRef.current)
      (gatePaneRef.current as HTMLElement & { inert: boolean }).inert = !gatePending;
    if (!gatePending) return;
    const timer = window.setTimeout(() => {
      const active = document.activeElement;
      if (active && active !== document.body && gatePaneRef.current?.contains(active)) return;
      gatePaneRef.current?.querySelector<HTMLElement>('#trip-brief-plan-gate-title')?.focus();
    }, reducedMotion || state.planApprovalGate?.source === 'restored' ? 0 : milliseconds(duration.slow));
    return () => window.clearTimeout(timer);
  }, [gatePending, gateSnapshot, reducedMotion, state.planApprovalGate?.revision, state.planApprovalGate?.source]);

  if (!runId && !state.homeSubmissionPending) return null;

  const stages: Array<{ id: ActivityStageId; title: string; status: ActivityStageStatus }> = stageProjection.stages;
  const days = identity ? tripDays(identity.start_date, identity.end_date) : 0;
  const styleTags = identity?.style
    ? [identity.style.primary, ...identity.style.secondary_interests].filter(Boolean)
    : [];
  const party = identity?.party;
  const partyText = party
    ? [
      party.adults == null && party.total != null ? `${party.total} 人同行` : '',
      party.adults != null ? `${party.adults} 位成人` : '',
      party.children ? `${party.children} 位儿童` : '',
      party.elderly_companions ? '有长辈同行' : '',
      party.accessibility_required ? '需要无障碍安排' : '',
    ].filter(Boolean).join(' · ')
    : '';
  const departureText = identity?.origin ? `${identity.origin.name}出发` : '出发地待确认';
  const dateText = identity?.start_date && identity.end_date
    ? `${identity.start_date} — ${identity.end_date}${identity.dates_assumed ? '（暂定）' : ''}`
    : identity?.start_date || identity?.end_date || '日期待确认';
  // 默认跟随当前阶段；用户点选后固定查看该阶段，直到换 Run 或会话轮次。
  const activityStage = selectedStage ?? stageProjection.currentStage;
  const activityStageView = activityStage ? stages.find((stage) => stage.id === activityStage) : undefined;
  // 固定查看时使用所选阶段标题，跟随当前进展时由运行状态补充终态标题。
  const activityTitle = understandingPending
    ? state.understandingQuestions?.retryResearch ? '等待重试研究' : state.understandingQuestions?.retryLocation ? '等待核实目的地' : '等待你的回答'
    : activityStage
      ? STAGE_ACTIVITY_TITLES[activityStage]
      : undefined;
  const emptyActivityText = selectedStage ? `「${STAGE_ACTIVITY_TITLES[selectedStage]}」阶段暂无行动记录。` : undefined;
  const hideEmptyProcess = state.thinkingSteps.length === 0
    && !state.isStreaming
    && (runStatus === 'failed' || runStatus === 'cancelled' || runStatus === 'interrupted');
  // 需求阶段回看确认过的方案；门仍在等待或正在追问时由各自卡片占位。
  const stagePlanView = selectedStage === 'requirements' && !gatePending && !understandingPending && stagePlan?.runId === runId
    ? stagePlan
    : null;
  const statusMessage = canResume
    ? runStatus === 'failed' ? '可以从最近的检查点重试。' : '可以从最近的位置继续。'
    : null;
  const progressTitle = state.homeSubmissionPending && !runId
    ? lastAssistant?.pendingStatusText || '正在理解你的旅行想法'
    : runStatus === 'failed'
      ? '旅行规划未完成'
      : runStatus === 'cancelled'
        ? '旅行规划已取消'
        : runStatus === 'interrupted'
          ? '旅行规划已中断'
          : runStatus === 'cancel_requested'
            ? '正在停止规划'
            : runStatus === 'awaiting_input'
              ? understandingPending
                ? state.understandingQuestions?.retryResearch ? '等待重试研究' : state.understandingQuestions?.retryLocation ? '等待核实目的地' : '等待你的回答'
                : '等待确认研究方案'
              : runStatus === 'completed'
                ? '旅行规划已生成'
                : '正在规划你的旅行';

  const canStartOver = !state.currentTripRunReadOnly && (runStatus === 'failed' || runStatus === 'cancelled' || (runStatus === 'interrupted' && !canResume));
  // cancel_requested 只是“正在停止”，仍按运行中展示；真正取消/失败/中断才切到终态。
  const runStopped = runStatus === 'failed' || runStatus === 'cancelled' || runStatus === 'interrupted';
  const showActiveSweep = Boolean(runId) && state.isStreaming && !gatePending && (runStatus === null || runStatus === 'running');
  const hasResearchActivity = state.thinkingSteps.some((step) => {
    const stage = getActivityStageIdForAgent(step.agentName);
    return stage === 'research' || stage === 'route' || stage === 'delivery';
  });
  const forceCompactProcess = seenRun !== runId && !hasResearchActivity && (state.isStreaming || gatePending);
  const effectiveGate = gatePending ? state.planApprovalGate : gateSnapshot?.runId === runId ? gateSnapshot : null;

  const startOver = () => {
    dispatch({ type: 'CLEAR_CHAT' });
    const url = new URL(window.location.href);
    url.searchParams.delete('session_id');
    url.searchParams.delete('run_id');
    url.searchParams.set('view', 'chat');
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  };

  return (
    <div className={cn('generation-journey-panel', understandingPending && 'generation-has-questions', state.homeSubmissionPending && !runId && 'is-awaiting-route')} data-testid="generation-journey-panel">
        <div className="generation-planning-layout">
          <header className="generation-planning-sidebar">
            <section className="generation-trip-card" aria-label="旅行信息">
              <div className="generation-trip-card-header">
                <div>
                  {identity?.destinations.length ? (
                    <h1 tabIndex={-1} data-workspace-handoff-focus>
                      <span className="generation-trip-title-destinations" aria-label={`目的地顺序：${identity.destinations.map((place) => place.name).join('、')}`}>
                        {identity.destinations.map((place, index) => (
                          <span key={place.place_id} className={cn('generation-trip-title-segment', index === 0 && 'is-first')}>
                            {index > 0 && <span className="generation-trip-title-divider" aria-hidden>·</span>}
                            <span className="generation-trip-title-place">{place.name}</span>
                          </span>
                        ))}
                      </span>
                    </h1>
                  ) : (
                    <h1 tabIndex={-1} data-workspace-handoff-focus className="generation-trip-title-idea">
                      <span>{state.homeSubmissionPending && !runId ? '你的旅行想法' : '目的地待确认'}</span>
                    </h1>
                  )}
                </div>
              </div>
              {pendingUserMessage && <p className="generation-submitted-request">{pendingUserMessage.displayContent || pendingUserMessage.content}</p>}
              {(!state.homeSubmissionPending || identity) && <div className="generation-trip-card-meta">
                <div className="generation-trip-fact" role="group" aria-label={`${departureText}，${dateText}`}>
                  <span className="generation-trip-fact-value">
                    <span>{departureText}</span>
                    <span className="generation-trip-card-date">{dateText}</span>
                    {days > 0 && <span>{days} 日</span>}
                  </span>
                </div>
                <div className="generation-trip-fact" role="group" aria-label={`同行 ${partyText || '待确认'}`}>
                  <span className="generation-trip-fact-value">{partyText || '同行人数待确认'}</span>
                </div>
                {styleTags.length > 0 && (
                  <div className="generation-trip-fact generation-trip-fact-style" role="group" aria-label={`旅行风格 ${styleTags.join('、')}`}>
                    <span className="generation-trip-tags">
                      {styleTags.map((item) => <span key={item}>{item}</span>)}
                    </span>
                  </div>
                )}
              </div>}
            </section>

            <section className="generation-progress" data-active={showActiveSweep ? 'true' : 'false'} data-run-status={runStatus || (state.homeSubmissionPending ? 'pending' : 'idle')} aria-label="旅行生成进度">
              <h2 className="sr-only">{progressTitle}</h2>
              {state.homeSubmissionPending && !runId ? (
                <p className="generation-route-status" role="status">正在确认处理方式</p>
              ) : <ol>
                {stages.map((stage, index) => {
                  const selected = selectedStage === stage.id;
                  return (
                    <li key={stage.id} className={cn(`is-${stage.status}`, selected && 'is-selected')} data-stage-status={stage.status}>
                      <h3 className="generation-stage-heading">
                        <button
                          type="button"
                          className="generation-stage-button"
                          aria-pressed={selected}
                          aria-label={stage.title}
                          onClick={() => setSelectedStage((current) => current === stage.id ? null : stage.id)}
                        >
                          <span className="generation-stage-mark" aria-hidden>
                            {stage.status === 'done'
                              ? <Check size={14} />
                              : stage.status === 'failed'
                                ? <CircleAlert size={14} />
                                : stage.status === 'stopped'
                                  ? <Pause size={14} />
                                  : stage.status === 'active'
                                    ? <Loader2 size={14} className="generation-stage-spinner" />
                                    : index + 1}
                          </span>
                          <span className="generation-stage-title">{STAGE_LABELS[stage.id]}</span>
                        </button>
                      </h3>
                    </li>
                  );
                })}
              </ol>}
              {(state.isStreaming || runStatus === 'cancel_requested') && !state.currentTripRunReadOnly && !gatePending && !understandingPending && (
                <button type="button" data-testid="boarding-pass-stop" className="generation-stop-btn" onClick={() => void stopRun()} disabled={runStatus === 'cancel_requested'} aria-label={runStatus === 'cancel_requested' ? '正在停止' : '停止生成'} title={runStatus === 'cancel_requested' ? '正在停止' : '停止生成'}>
                  {runStatus === 'cancel_requested' ? <Loader2 size={13} className="generation-stage-spinner" /> : <Square size={12} />}
                  <span className="generation-stop-label">{runStatus === 'cancel_requested' ? '正在停止' : '停止生成'}</span>
                </button>
              )}
            </section>

            {state.currentTripRunReadOnly && (
              <p className="generation-readonly-note" role="status">历史生成记录 · 只读</p>
            )}
          </header>

          <main className={cn('generation-activity', gatePending && 'is-confirming')} data-live={showActiveSweep ? 'true' : 'false'} aria-label="规划与调研动态">
            <div className="generation-activity-body">
              {(statusMessage || canResume || canStartOver) && (
                <div className="generation-status-actions">
                  {statusMessage && <p role="status">{statusMessage}</p>}
                  <div className="generation-run-actions">
                    {canResume && <button type="button" data-testid="boarding-pass-resume" onClick={() => void resume()} disabled={resuming}><Play size={14} />{resuming ? '正在重试' : runStatus === 'failed' ? '从上次位置重试' : '继续生成'}</button>}
                    {canResume && runStatus === 'failed' && <span className="text-xs text-ink-muted">重试会再次调用模型，可能产生费用；动态资料可能已过期，请重新核实。</span>}
                    {canStartOver && <button type="button" onClick={startOver}>返回新旅行</button>}
                  </div>
                </div>
              )}
              {lastAssistant?.type === 'error' && (
                <p role="alert" className="generation-activity-error">{generationErrorText(lastAssistant.displayContent || lastAssistant.content)}</p>
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
                    {hideEmptyProcess && !stagePlanView && <h2 className="generation-terminal-title" tabIndex={-1}>{progressTitle}</h2>}
                    {understandingPending && state.understandingQuestions && (
                      <UnderstandingQuestionsCard
                        key={`${state.understandingQuestions.runId}:${state.understandingQuestions.revision}`}
                        runId={state.understandingQuestions.runId}
                        revision={state.understandingQuestions.revision}
                        approvalToken={state.understandingQuestions.approvalToken}
                        questions={state.understandingQuestions.questions}
                        retryLocation={state.understandingQuestions.retryLocation}
                        retryResearch={state.understandingQuestions.retryResearch}
                        message={state.understandingQuestions.message}
                      />
                    )}
                    {stagePlanView ? (
                      <TripBriefPlanGate
                        variant="workspace"
                        gateOverride={stagePlanView}
                        readOnly
                        headingId="trip-brief-stage-plan-title"
                      />
                    ) : !hideEmptyProcess && (
                      <ThinkingChain
                        steps={state.thinkingSteps}
                        isGenerating={state.isStreaming}
                        displayContent={lastAssistant?.displayContent}
                        isSynthesizing={state.isSynthesizing}
                        pendingStatusText={lastAssistant?.pendingStatusText}
                        variant={runStopped ? 'interrupted' : 'default'}
                        startedAt={lastAssistant?.timestamp}
                        regionId={`generation-thinking-${runId ?? 'pending'}`}
                        layout="workspace"
                        runStatus={runStatus}
                        gatePending={gatePending}
                        runKey={runId ?? undefined}
                        activityTitle={state.homeSubmissionPending && !runId ? progressTitle : resuming ? '正在继续生成' : !selectedStage && (runStopped || runStatus === 'cancel_requested' || runStatus === 'completed') ? progressTitle : activityTitle}
                        emptyText={emptyActivityText}
                        activityStage={activityStage ?? undefined}
                        activityFocus={!selectedStage || selectedStage === stageProjection.currentStage ? state.tripSummaryCard?.currentFocus : undefined}
                        stageStatus={activityStageView?.status}
                        initiallyExpanded={hadGateOnMount.current ? false : undefined}
                        forcedCollapsed={forceCompactProcess}
                        collapseKey={gatePending ? `${state.planApprovalGate?.runId}:${state.planApprovalGate?.revision}` : undefined}
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
                  {followup.hint && <p className="generation-followup-hint">{followup.hint}</p>}
                  <InputArea minimal autoFocus={false} placeholder={followup.placeholder} />
                </div>
              </div>
            )}
          </main>
        </div>
    </div>
  );
};
