import { m } from 'motion/react';
import { ArrowRight, Check, Loader2, PencilLine, Users } from 'lucide-react';
import { useApp } from '../../../../app/state/AppContext';
import { useSendMessage } from '../../../../app/session/useSendMessage';
import { type PlanGateDecisionAction } from '../../types/planner';
import { type PlanApprovalGate, type PlanGateStep } from '../../types/planning';
import { Button } from '../../../../components/ui/Button';
import { cn } from '../../../../lib/utils';
import { emphasisEnter } from '../../../../lib/motion';
import { RESEARCH_START_TEXT } from '../../../chat/model/conversationFlow';
import { Markdown } from '../../../chat/components/Markdown';
import { planGateEntries } from '../../model/planGateActions';
import { normalizePlanApprovalGate } from '../../model/planApprovalGate';
import { planGateDraftKey, readPlanGateDraft, writePlanGateDraft } from '../../model/planGateDraftStorage';
import { getTripRunDetail } from '../../api/runs';
import { isTripRunStatus } from '../../types/runs';
import React from 'react';

const RESEARCH_STEP_LABELS: Record<string, string> = {
  destination_researcher: '目的地调研',
  transport_researcher: '交通查询',
  accommodation_researcher: '住宿查询',
  itinerary_planner: '行程规划',
};

function researchStepText(step: PlanGateStep): string {
  const labels = step.agents.map(agent => RESEARCH_STEP_LABELS[agent] || agent);
  return labels.join('、');
}

export const TripBriefPlanGate: React.FC<{
  variant?: 'default' | 'workspace';
  /** 工作区交接期间保留已清除门的最后一帧，供尺寸收起过渡使用。 */
  gateOverride?: PlanApprovalGate | null;
}> = ({ variant = 'default', gateOverride }) => {
  const { state, dispatch, currentStateRef } = useApp();
  const { sendMessage } = useSendMessage();
  const workspace = variant === 'workspace';
  const gate = gateOverride !== undefined ? gateOverride : state.planApprovalGate;
  const [editing, setEditing] = React.useState(false);
  const [guide, setGuide] = React.useState('');
  const [draftStorageUnavailable, setDraftStorageUnavailable] = React.useState(false);
  const [submitting, setSubmitting] = React.useState<PlanGateDecisionAction | null>(null);
  const [error, setError] = React.useState('');
  const [stalePlan, setStalePlan] = React.useState(false);
  const [refreshing, setRefreshing] = React.useState(false);
  const errorRef = React.useRef<HTMLParagraphElement>(null);
  const revisionKey = gate ? `${gate.runId}#${gate.revision}#${gate.approvalToken ?? ''}` : null;
  const draftKey = gate ? planGateDraftKey(state.currentSessionId, gate.runId, gate.approvalToken) : null;

  React.useEffect(() => {
    const saved = readPlanGateDraft(draftKey);
    setGuide(saved.value);
    setDraftStorageUnavailable(!saved.available);
    setEditing(false);
    setError('');
    setStalePlan(false);
  }, [revisionKey, draftKey]);

  React.useEffect(() => {
    if (!workspace && gate?.runId) document.querySelector<HTMLElement>('#trip-brief-plan-gate-title')?.focus();
  }, [workspace, gate?.runId, gate?.revision, gate?.approvalToken]);

  React.useEffect(() => {
    if (error && !state.isStreaming && !submitting && !refreshing) errorRef.current?.focus();
  }, [error, state.isStreaming, submitting, refreshing]);

  if (!gate) return null;
  const entries = planGateEntries(gate);
  const identity = state.controlledTripIdentity;
  const controlsBlocked = state.isStreaming || submitting !== null || refreshing;
  const decisionBlocked = controlsBlocked || stalePlan;
  const canRevise = entries.supplement;
  const planText = gate.planText.trim() || [...new Set(gate.steps.flatMap(step => Object.values(step.tasks || {})).map(task => task.trim()).filter(Boolean))].join('\n\n');
  const generationFailed = Boolean(entries.retry) && !entries.approve;
  const showEditor = editing;
  const partySummary = identity?.party
    ? [
      identity.party.adults == null && identity.party.total != null ? `${identity.party.total} 人同行` : '',
      identity.party.adults != null ? `${identity.party.adults} 位成人` : '',
      identity.party.children ? `${identity.party.children} 位儿童` : '',
      identity.party.elderly_companions ? '有长辈同行' : '',
      identity.party.accessibility_required ? '需要无障碍安排' : '',
    ].filter(Boolean).join(' · ')
    : '';
  const styleTags = identity?.style ? [identity.style.primary, ...identity.style.secondary_interests].filter(Boolean) : [];

  const refreshPlan = async () => {
    if (refreshing) return;
    const sessionId = state.currentSessionId;
    const epoch = state.conversationEpoch;
    setRefreshing(true);
    try {
      const detail = await getTripRunDetail(gate.runId, { sessionId });
      const current = currentStateRef.current;
      if (current.currentTripRunId !== gate.runId || current.currentSessionId !== sessionId || current.conversationEpoch !== epoch
        || current.planApprovalGate?.runId !== gate.runId || current.planApprovalGate.revision !== gate.revision
        || current.planApprovalGate.approvalToken !== gate.approvalToken || current.planApprovalGate.status !== 'pending') return;
      const choice = detail.state.pending_user_choice;
      if (detail.run.status !== 'awaiting_input') {
        if (isTripRunStatus(detail.run.status)) dispatch({ type: 'SET_TRIP_RUN_STATUS', payload: detail.run.status });
        dispatch({ type: 'SET_PLAN_APPROVAL_GATE', payload: null });
        dispatch({ type: 'RESOLVE_WAITING_MESSAGES' });
        return;
      }
      if (choice?.read_only || choice?.terminal_status) {
        setError('这份计划已不可修改，请返回行程查看当前状态。');
        return;
      }
      const payload = choice?.payload;
      const latest = choice?.gate === 'plan' && payload && typeof payload === 'object' && !Array.isArray(payload)
        ? normalizePlanApprovalGate({ run_id: gate.runId, gate: 'plan', payload: payload as Record<string, unknown> }, 'pending', 'restored')
        : null;
      if (!latest || !latest.approvalToken) {
        setError('暂时无法加载可确认的最新计划；请稍后重试或取消规划。');
        return;
      }
      dispatch({ type: 'SET_PLAN_APPROVAL_GATE', payload: latest });
      setStalePlan(false);
      setError('计划已刷新，请重新核对后再确认。');
    } catch {
      setError('暂时无法刷新计划，请重试或取消规划。');
    } finally {
      setRefreshing(false);
    }
  };

  const submit = async (action: PlanGateDecisionAction) => {
    const content = guide.trim();
    if (controlsBlocked || (stalePlan && action !== 'cancel') || (action === 'supplement' && !content)) return;
    setSubmitting(action);
    setError('');
    let stale = false;
    try {
      const actionText = action === 'approve'
        ? RESEARCH_START_TEXT
        : action === 'supplement'
          ? '按这些修改重新整理旅行'
          : action === 'retry' ? '重试生成研究计划' : '取消本次规划';
      const sent = await sendMessage(actionText, {
        resumeRunId: gate.runId,
        route: 'trip_refinement',
        gateDecision: {
          action,
          content: action === 'supplement' ? content : '',
          ...(action !== 'cancel' && gate.approvalToken ? { approval_token: gate.approvalToken } : {}),
        },
        onRequestError: (requestError) => { stale = requestError.message.includes('plan_gate_version_stale'); },
        assistantPendingLabel: action === 'approve'
          ? '正在开始调研'
          : action === 'supplement'
            ? '正在按你的修改重新整理'
            : action === 'retry' ? '正在重新生成研究计划' : undefined,
      });
      if (sent && (action === 'supplement' || action === 'cancel')) writePlanGateDraft(draftKey, '');
      if (!sent) {
        if (stale) setStalePlan(true);
        setError(stale || stalePlan ? '计划版本已变化，请刷新并重新核对后再确认。' : '这次操作未完成，旅行信息和修改已保留，请重试。');
      }
    } catch {
      setError('暂时无法提交，旅行信息和修改已保留，请重试。');
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <m.section data-testid="trip-brief-plan-gate" aria-labelledby="trip-brief-plan-gate-title" className={cn('plan-gate-card', workspace && 'is-workspace')} variants={emphasisEnter} initial={workspace ? false : 'hidden'} animate="visible">
      <header className="plan-gate-header">
        <h2 id="trip-brief-plan-gate-title" tabIndex={-1}>{generationFailed ? '研究方案暂未生成' : '研究方案'}</h2>
        {!workspace && <span>{identity ? generationFailed ? '可以重试生成方案，也可以补充要求后再试。' : '这是本次准备怎样研究和安排的设想，确认后开始调研，或补充调整。' : '请确认本次旅行的需求与安排。'}</span>}
      </header>
      <div className="plan-gate-content">
        {identity && !workspace && (
          <div className="plan-gate-context" aria-label="旅行摘要">
            <p><Users size={14} aria-hidden /><span>{partySummary || '同行人数待确认'}</span></p>
            {styleTags.length > 0 && <div className="plan-gate-context-tags" aria-label="旅行风格">{styleTags.map((item) => <span key={item}>{item}</span>)}</div>}
          </div>
        )}

        {planText && (
          <section className="plan-gate-plan" aria-labelledby="plan-gate-plan-title">
            <h3 id="plan-gate-plan-title" className={workspace ? 'sr-only' : undefined}>{generationFailed ? '方案生成情况' : '研究与安排设想'}</h3>
            <Markdown content={planText} className="plan-gate-plan-text" />
            {!workspace && !generationFailed && gate.steps.length > 0 && <p className="plan-gate-plan-note">
              研究安排：{gate.steps.map(researchStepText).join(' → ')}
            </p>}
            {!workspace && !generationFailed && <p className="plan-gate-plan-note">确认后开始研究；有修改会重新整理方案。</p>}
          </section>
        )}

        {!planText && <p className="plan-gate-note">暂时没有可展示的研究设想。</p>}

        {canRevise && (
          <div className="plan-gate-edit">
            <button type="button" aria-expanded={editing} onClick={() => setEditing((value) => !value)} disabled={decisionBlocked}>
              <PencilLine size={15} />补充或调整旅行要求
            </button>
            <div className={cn('plan-gate-edit-panel', showEditor && 'is-open')}>
              <div>
                <label htmlFor="plan-gate-guide">想改哪里？</label>
                <textarea
                  id="plan-gate-guide"
                  value={guide}
                  onChange={(event) => {
                    const value = event.target.value;
                    setGuide(value);
                    setDraftStorageUnavailable(!writePlanGateDraft(draftKey, value));
                  }}
                  disabled={controlsBlocked}
                  rows={3}
                  maxLength={500}
                  placeholder="例如：每天少安排一个景点，住宿选在地铁附近，首日中午后开始活动。"
                />
                {guide.trim() && <p role="status">请先提交修改，或清空内容后确认当前方案。</p>}
                {guide.trim() && draftStorageUnavailable && <p role="status">修改内容尚未保存，刷新页面会清空，请先提交。</p>}
                {showEditor && <Button variant="secondary" data-testid="plan-gate-supplement" disabled={decisionBlocked || !guide.trim()} onClick={() => void submit('supplement')}>
                  {submitting === 'supplement' ? <Loader2 size={15} className="animate-spin" /> : <ArrowRight size={15} />}
                  按修改重新整理
                </Button>}
              </div>
            </div>
          </div>
        )}

        {error && <p ref={errorRef} role="alert" tabIndex={-1} className="plan-gate-error">{error}</p>}
        {stalePlan && <Button variant="secondary" type="button" disabled={controlsBlocked} onClick={() => void refreshPlan()}>{refreshing ? '正在刷新计划…' : '刷新当前计划'}</Button>}

        <div className="plan-gate-actions">
          {!workspace && <p>{gate.revision > 0 ? '修改后会按这一版要求重新整理。' : '确认后开始查询资料，再安排每天路线。'}</p>}
          <div>
            {entries.cancel && <button type="button" disabled={controlsBlocked} onClick={() => void submit('cancel')}>取消规划</button>}
            {entries.retry && <Button variant="secondary" disabled={decisionBlocked} onClick={() => void submit('retry')}>
              {submitting === 'retry' ? <Loader2 size={16} className="animate-spin" /> : <ArrowRight size={16} />}
              重试生成研究计划
            </Button>}
            {entries.approve && <Button size="lg" disabled={decisionBlocked || !planText || Boolean(guide.trim())} onClick={() => void submit('approve')}>
              {submitting === 'approve' ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
              确认并开始生成
            </Button>}
          </div>
        </div>
      </div>
    </m.section>
  );
};
