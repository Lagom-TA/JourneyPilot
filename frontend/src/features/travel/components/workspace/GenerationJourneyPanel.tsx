import { Check, Loader2, MapPin, Play, Route, Square, Users } from 'lucide-react';
import { useApp } from '../../../../app/state/AppContext';
import { useSendMessage } from '../../../../app/session/useSendMessage';
import { useStopRun } from '../../../../app/session/useStopRun';
import { derivePlanningStageSnapshot } from '../../model/travelProgress';
import { TripBriefPlanGate } from '../planning/TripBriefPlanGate';
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
  const identity = state.controlledTripIdentity;
  const runId = state.currentTripRunId;
  const lastAssistant = [...state.currentMessages].reverse().find((message) => message.role === 'assistant');
  const answerStarted = Boolean(lastAssistant?.content?.trim());
  const snapshot = derivePlanningStageSnapshot({
    steps: state.thinkingSteps,
    isStreaming: state.isStreaming,
    isSynthesizing: state.isSynthesizing,
    answerStarted,
  });
  const runStatus = state.currentTripRunStatus;
  const recovery = state.currentTripRunRecovery;
  const canResume = runStatus === 'interrupted' && recovery?.resumable === true;
  const gatePending = Boolean(state.planApprovalGate && state.planApprovalGate.status !== 'cancelled');

  if (!identity || !runId) return null;

  const planning = snapshot.stages[0];
  const research = snapshot.stages[1];
  const synthesis = snapshot.stages[2];
  const itineraryTouched = state.thinkingSteps.some((step) => step.agentName.replace(/_r\d+$/, '') === 'itinerary_planner');
  const synthesisStarted = synthesis.status !== 'pending';
  const routeStatus: StageStatus = synthesisStarted ? 'done' : itineraryTouched ? research.status : 'pending';
  const researchStatus: StageStatus = routeStatus !== 'pending' || synthesisStarted ? 'done' : research.status;
  const stages: Array<{ title: string; description: string; status: StageStatus }> = [
    { title: '整理旅行需求', description: '目的地、时间、同行人与旅行偏好', status: gatePending ? 'active' : planning.status },
    { title: '查找交通与住宿', description: '把城际衔接、市内交通和住宿放在一起考虑', status: researchStatus },
    { title: '安排每天路线', description: '让景点、美食与休息节奏顺路衔接', status: routeStatus },
    { title: '生成完整计划', description: '整理日程、地图、阅读版与费用参考', status: synthesis.status },
  ];
  const activeStage = stages.find((stage) => stage.status === 'active');
  const days = tripDays(identity.start_date, identity.end_date);
  const title = `${identity.destinations.map((place) => place.name).join('＋')} ${days || ''} 日`;
  const statusMessage = runStatus === 'failed'
    ? '这次规划没有完成，你可以回到新旅行重新尝试。'
    : runStatus === 'cancelled'
      ? '这次规划已取消。'
      : runStatus === 'interrupted'
        ? canResume ? '规划已中断，可以从最近的位置继续。' : '这次规划已中断。'
        : null;

  const canStartOver = (runStatus === 'failed' || runStatus === 'cancelled' || (runStatus === 'interrupted' && !canResume));

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
      <header className="generation-journey-heading">
        <p>{gatePending ? '生成前的最后复核' : '你的旅行正在成形'}</p>
        <h1>{gatePending ? '确认这趟旅行' : title}</h1>
        {!gatePending && <span>{identity.origin.name}出发 · {identity.start_date} — {identity.end_date}</span>}
      </header>

      {state.planApprovalGate ? (
        <TripBriefPlanGate />
      ) : (
        <>
          <section className="generation-progress" aria-label="旅行生成进度">
            <h2>正在规划你的旅行</h2>
            <p role={statusMessage ? 'alert' : 'status'} aria-live="polite">{statusMessage ?? activeStage?.description ?? state.tripSummaryCard?.currentFocus ?? '正在整理这趟旅行的基本信息。'}</p>
            <ol>
              {stages.map((stage, index) => (
                <li key={stage.title} className={cn(`is-${stage.status}`)}>
                  <span className="generation-stage-mark" aria-hidden>
                    {stage.status === 'done' ? <Check size={14} /> : stage.status === 'active' ? <Loader2 size={14} className="generation-stage-spinner" /> : index + 1}
                  </span>
                  <div>
                    <h3>{stage.title}</h3>
                    <p>{stage.description}</p>
                    {stage.status === 'active' && state.tripSummaryCard?.currentFocus && <span>{state.tripSummaryCard.currentFocus}</span>}
                  </div>
                </li>
              ))}
            </ol>
          </section>

          {(canResume || state.isStreaming || canStartOver) && (
            <div className="generation-run-actions">
              {canStartOver && <button type="button" onClick={startOver}>返回新旅行</button>}
              {canResume && !state.isStreaming && <button type="button" data-testid="boarding-pass-resume" onClick={() => void resume()} disabled={resuming}><Play size={14} />{resuming ? '正在继续' : '继续生成'}</button>}
              {state.isStreaming && <button type="button" data-testid="boarding-pass-stop" className="is-stop" onClick={() => void stopRun()}><Square size={13} />停止</button>}
            </div>
          )}

          <section className="generation-trip-facts" aria-label="旅行信息">
            <h2>旅行信息</h2>
            <dl>
              <div><dt><MapPin size={14} />目的地</dt><dd>{identity.destinations.map((place) => place.name).join('、')}</dd></div>
              <div><dt><Route size={14} />行程</dt><dd>{days} 天 · {identity.origin.name}出发</dd></div>
              <div><dt><Users size={14} />同行</dt><dd>{identity.party.adults} 位成人{identity.party.children ? ` · ${identity.party.children} 位儿童` : ''}</dd></div>
            </dl>
            <div className="generation-trip-tags">
              {[identity.style.primary, ...identity.style.secondary_interests].map((item) => <span key={item}>{item}</span>)}
            </div>
          </section>
        </>
      )}
    </div>
  );
};
