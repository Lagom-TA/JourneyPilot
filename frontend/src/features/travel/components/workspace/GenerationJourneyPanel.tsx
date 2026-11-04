import { CalendarDays, Check, CircleAlert, Loader2, Pause, Play, Sparkles, Square, Users } from 'lucide-react';
import { useReducedMotion } from 'motion/react';
import { useApp } from '../../../../app/state/AppContext';
import { useSendMessage } from '../../../../app/session/useSendMessage';
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
import { ThinkingChain } from '../../../chat/components/ThinkingChain';
import { InputArea } from '../../../chat/components/InputArea';
import { cn } from '../../../../lib/utils';
import React from 'react';

const RESUME_TEXT = '继续上次被中断的规划';
const STAGE_ACTIVITY_TITLES: Record<ActivityStageId, string> = {
  requirements: '整理旅行需求',
  research: '查找旅行资料',
  route: '安排每天路线',
  delivery: '生成完整计划',
};
const STAGE_DESCRIPTIONS: Record<ActivityStageId, string> = {
  requirements: '目的地、时间、同行人与旅行偏好',
  research: '先研究目的地，再并行查询交通与住宿，保留充分备选',
  route: '让景点、美食与休息节奏顺路衔接',
  delivery: '整理日程、地图、阅读版与费用参考',
};

function tripDays(start: string | null, end: string | null): number {
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
  // 恢复或查看历史 Run 时，正文和错误提示只能取当前 Run 的助手消息。
  // 实时助手消息在 chat_start 时写入 runId，因此这里不需要再混入无归属消息。
  const runMessages = state.currentMessages.filter((message) => message.runId === runId);
  const lastAssistant = [...runMessages].reverse().find((message) => message.role === 'assistant');
  const answerStarted = lastAssistant?.type !== 'error' && Boolean(lastAssistant?.content?.trim());
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
  // 阶段选择只属于当前 Run；换 Run 或开启新会话轮次时回到“只跟随最新阶段”。
  React.useEffect(() => {
    setSelectedStage(null);
  }, [runId, state.conversationEpoch]);
  const understandingPending = Boolean(
    state.understandingQuestions && state.understandingQuestions.runId === runId,
  );
  // 左侧阶段列表与右侧过程区共用这一份投影；右侧不再根据过滤后的事件和
  // 整个 Run 的 isStreaming 二次推断阶段状态。
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
    if (processPaneRef.current)
      (processPaneRef.current as HTMLElement & { inert: boolean }).inert = gatePending;
    if (gatePaneRef.current)
      (gatePaneRef.current as HTMLElement & { inert: boolean }).inert = !gatePending;
    if (!gatePending) return;
    const timer = window.setTimeout(() => {
      gatePaneRef.current?.querySelector<HTMLElement>('#trip-brief-plan-gate-title')?.focus();
    }, reducedMotion || state.planApprovalGate?.source === 'restored' ? 0 : 320);
    return () => window.clearTimeout(timer);
  }, [gatePending, gateSnapshot, reducedMotion, state.planApprovalGate?.revision, state.planApprovalGate?.source]);

  if (!runId) return null;

  const stages: Array<{ id: ActivityStageId; title: string; description: string; status: ActivityStageStatus }> = stageProjection.stages.map((stage) => ({
    ...stage,
    description: STAGE_DESCRIPTIONS[stage.id],
  }));
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
  // 右侧过程区始终显示所属阶段的标题；默认跟随当前阶段时也要显式传入，
  // 否则 ThinkingChain 会按整次 Run 的门/终态重新推导，把标题换成
  // “等待确认研究方案”或“旅行规划未完成”。
  const activityTitle = understandingPending
    ? state.understandingQuestions?.retryResearch ? '等待重试研究' : state.understandingQuestions?.retryLocation ? '等待核实目的地' : '等待你的回答'
    : activityStage
      ? STAGE_ACTIVITY_TITLES[activityStage]
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
            ? state.understandingQuestions?.retryResearch ? '等待重试研究' : state.understandingQuestions?.retryLocation ? '等待核实目的地' : '等待你的回答'
            : '等待确认研究方案'
          : runStatus === 'completed'
            ? '旅行规划已生成'
            : '正在规划你的旅行';

  const canStartOver = (runStatus === 'failed' || runStatus === 'cancelled' || (runStatus === 'interrupted' && !canResume));
  // cancel_requested 只是“正在停止”，仍按运行中展示；真正取消/失败/中断才切到终态。
  const runStopped = runStatus === 'failed' || runStatus === 'cancelled' || runStatus === 'interrupted';
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
      await sendMessage(RESUME_TEXT, {
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
                  {identity?.destinations.length ? (
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
                      <span>目的地待确认</span>
                    </h1>
                  )}
                </div>
                {state.isStreaming && (
                  <button type="button" data-testid="boarding-pass-stop" className="generation-stop-btn" onClick={() => void stopRun()} aria-label="停止生成">
                    <Square size={12} />停止
                  </button>
                )}
              </div>
              <div className="generation-trip-card-meta">
                <div className="generation-trip-fact" role="group" aria-label={`${departureText}，${dateText}`}>
                  <CalendarDays size={14} aria-hidden />
                  <span className="generation-trip-fact-value">
                    <span>{departureText}</span>
                    <span className="generation-trip-card-date">{dateText}</span>
                  </span>
                </div>
                <div className="generation-trip-fact" role="group" aria-label={`同行 ${partyText || '待确认'}`}>
                  <Users size={14} aria-hidden />
                  <span className="generation-trip-fact-value">{partyText || '同行人数待确认'}</span>
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
            </section>

            <section className="generation-progress" data-active={showActiveSweep ? 'true' : 'false'} aria-label="旅行生成进度">
              <h2>{progressTitle}</h2>
              {statusMessage && <p role="alert" aria-live="polite">{statusMessage}</p>}
              <ol>
                {stages.map((stage, index) => {
                  const selected = selectedStage === stage.id;
                  return (
                    <li key={stage.id} className={cn(`is-${stage.status}`, selected && 'is-selected')} data-stage-status={stage.status}>
                      <h3 className="generation-stage-heading">
                        <button
                          type="button"
                          className="generation-stage-button"
                          aria-pressed={selected}
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
                        activityTitle={activityTitle}
                        emptyText={emptyActivityText}
                        activityStage={activityStage ?? undefined}
                        stageStatus={activityStageView?.status}
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
                        retryLocation={state.understandingQuestions.retryLocation}
                        retryResearch={state.understandingQuestions.retryResearch}
                        message={state.understandingQuestions.message}
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
                  <InputArea minimal showCompaction={false} autoFocus={false} placeholder={followup.placeholder} />
                </div>
              </div>
            )}
          </main>
        </div>
    </div>
  );
};
