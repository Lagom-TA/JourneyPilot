import { m } from 'motion/react';
import { ArrowRight, Check, Loader2, PencilLine, Users } from 'lucide-react';
import { useApp } from '../../../../app/state/AppContext';
import { useSendMessage } from '../../../../app/session/useSendMessage';
import { type PlanGateDecisionAction } from '../../types/planner';
import { type PlanApprovalGate } from '../../types/planning';
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
    if (!workspace && gate?.runId) document.querySelector<HTMLElement>('#trip-brief-plan-gate-title, [data-testid="semantic-requirement-gate"] h2')?.focus();
  }, [workspace, gate?.runId, gate?.revision, gate?.approvalToken]);

  React.useEffect(() => {
    if (error && !state.isStreaming && !submitting && !refreshing) errorRef.current?.focus();
  }, [error, state.isStreaming, submitting, refreshing]);

  if (!gate) return null;
  const entries = planGateEntries(gate);
  const identity = state.controlledTripIdentity;
  const controlsBlocked = state.isStreaming || submitting !== null || refreshing;
  const decisionBlocked = controlsBlocked || stalePlan;
  const { hard, preferences } = gate.recognizedRequirements;
  const canRevise = entries.supplement;
  const planText = gate.planText.trim();
  const planSteps = gate.steps.filter((step) => step.agents.length > 0);
  const clarifying = !entries.approve && entries.supplement && gate.steps.length === 0;
  const showEditor = clarifying || editing;
  const requirements = [...hard, ...preferences].filter((item, index, items) => item.summary && items.findIndex((other) => other.summary === item.summary) === index);
  const partySummary = identity
    ? [
      `${identity.party.adults} 位成人`,
      identity.party.children ? `${identity.party.children} 位儿童` : '',
      identity.party.elderly_companions ? '有长辈同行' : '',
      identity.party.accessibility_required ? '需要无障碍安排' : '',
    ].filter(Boolean).join(' · ')
    : '';
  const styleTags = identity ? [identity.style.primary, ...identity.style.secondary_interests].filter(Boolean) : [];

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
      setError(gate.semanticChallenge || gate.semanticError ? '需求核对已刷新，请重新检查后再提交。' : '计划已刷新，请重新核对后再确认。');
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
          ? (clarifying ? '补充旅行信息' : '按这些修改重新整理旅行')
          : action === 'retry' ? '重试生成研究计划' : '取消本次规划';
      const sent = await sendMessage(actionText, undefined, {
        resumeRunId: gate.runId,
        route: 'trip_refinement',
        gateDecision: {
          action,
          content: action === 'approve' || action === 'supplement' ? content : '',
          ...(action !== 'cancel' && gate.approvalToken ? { approval_token: gate.approvalToken } : {}),
        },
        onRequestError: (requestError) => { stale = requestError.message.includes('plan_gate_version_stale'); },
        assistantPendingLabel: action === 'approve'
          ? '正在开始调研'
          : action === 'supplement'
            ? (clarifying ? '正在重新分析补充的信息' : '正在按你的修改重新整理')
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

  if (gate.semanticError) {
    return <section className="plan-gate-card" data-testid="trip-brief-plan-gate" role="alert">
      <h2 id="trip-brief-plan-gate-title" tabIndex={-1}>需求核对暂不可用</h2>
      <p>{gate.semanticError}</p>
      <Button variant="secondary" type="button" disabled={controlsBlocked} onClick={() => void refreshPlan()}>刷新需求核对</Button>
      <button type="button" disabled={controlsBlocked} onClick={() => void submit('cancel')}>取消规划</button>
    </section>;
  }

  return (
    <m.section data-testid="trip-brief-plan-gate" aria-labelledby="trip-brief-plan-gate-title" className={cn('plan-gate-card', workspace && 'is-workspace')} variants={emphasisEnter} initial={workspace ? false : 'hidden'} animate="visible">
      <header className="plan-gate-header">
        {!workspace && <p>开始规划前</p>}
        <h2 id="trip-brief-plan-gate-title" tabIndex={-1}>{clarifying ? '补充必要信息' : '确认旅行需求'}</h2>
        {!workspace && <span>{clarifying ? '回答后会重新分析，再为你整理研究计划。' : identity ? '已整理这趟旅行的信息。确认下面的要求后开始，或补充调整。' : '请确认本次旅行的需求与安排。'}</span>}
      </header>

      {identity && !workspace && (
        <div className="plan-gate-context" aria-label="旅行摘要">
          <p><Users size={14} aria-hidden /><span>{partySummary}</span></p>
          {styleTags.length > 0 && <div className="plan-gate-context-tags" aria-label="旅行风格">{styleTags.map((item) => <span key={item}>{item}</span>)}</div>}
        </div>
      )}

      {(planText || planSteps.length > 0) && (
        <section className="plan-gate-plan" aria-labelledby="plan-gate-plan-title">
          <h3 id="plan-gate-plan-title">{clarifying ? '请先回答' : '本次会这样研究'}</h3>
          {planText ? (
            <Markdown content={planText} className="plan-gate-plan-text" />
          ) : (
            <ol className="plan-gate-plan-steps">
              {planSteps.map((step) => (
                <li key={step.step}>
                  <strong>步骤 {step.step}</strong>
                  <span>{Object.values(step.tasks || {}).filter(Boolean).join('；') || step.agents.join('、')}</span>
                </li>
              ))}
            </ol>
          )}
          {!workspace && <p className="plan-gate-plan-note">确认后，下面的调研会按这份计划执行；有修改会在重新整理后更新。</p>}
        </section>
      )}

      {requirements.length > 0 ? (
        <section className="plan-gate-requirements" aria-labelledby="plan-gate-requirements-title">
          <h3 id="plan-gate-requirements-title">已识别的旅行要求</h3>
          <ul>
            {requirements.map((item) => <li key={item.requirementId} data-requirement={item.requirementId}><Check size={14} aria-hidden />{item.summary}</li>)}
          </ul>
        </section>
      ) : planText || planSteps.length > 0 ? null : (
        <p className="plan-gate-note">还没有识别到额外要求，可以直接开始规划。</p>
      )}

      {canRevise && (
        <div className="plan-gate-edit">
          {!clarifying && <button type="button" aria-expanded={editing} onClick={() => setEditing((value) => !value)} disabled={decisionBlocked}>
            <PencilLine size={15} />补充或调整旅行要求
          </button>}
          <div className={cn('plan-gate-edit-panel', showEditor && 'is-open')}>
            <div>
              <label htmlFor="plan-gate-guide">{clarifying ? '你的回答' : '想改哪里？'}</label>
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
                placeholder={clarifying ? '请说明你的具体要求。' : '例如：每天少安排一个景点，住宿选在地铁附近，首日中午后开始活动。'}
              />
              {guide.trim() && draftStorageUnavailable && <p role="status">回答尚未保存，刷新页面会清空，请先提交。</p>}
              {showEditor && <Button variant="secondary" data-testid="plan-gate-supplement" disabled={decisionBlocked || !guide.trim()} onClick={() => void submit('supplement')}>
                {submitting === 'supplement' ? <Loader2 size={15} className="animate-spin" /> : <ArrowRight size={15} />}
                {clarifying ? '提交回答并继续整理' : '按修改重新整理'}
              </Button>}
            </div>
          </div>
        </div>
      )}

      {error && <p ref={errorRef} role="alert" tabIndex={-1} className="plan-gate-error">{error}</p>}
      {stalePlan && <Button variant="secondary" type="button" disabled={controlsBlocked} onClick={() => void refreshPlan()}>{refreshing ? '正在刷新计划…' : '刷新当前计划'}</Button>}

      <div className="plan-gate-actions">
        {!workspace && <p>{clarifying ? '研究计划将在信息明确后展示，尚未开始查询。' : gate.revision > 0 ? '修改后会按这一版要求重新整理。' : '确认后开始查询资料，再安排每天路线。'}</p>}
        <div>
          {entries.cancel && <button type="button" disabled={controlsBlocked} onClick={() => void submit('cancel')}>取消规划</button>}
          {entries.retry && <Button variant="secondary" disabled={decisionBlocked} onClick={() => void submit('retry')}>
            {submitting === 'retry' ? <Loader2 size={16} className="animate-spin" /> : <ArrowRight size={16} />}
            重试生成研究计划
          </Button>}
          {entries.approve && <Button size="lg" disabled={decisionBlocked} onClick={() => void submit('approve')}>
            {submitting === 'approve' ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
            确认并开始生成
          </Button>}
        </div>
      </div>
    </m.section>
  );
};
