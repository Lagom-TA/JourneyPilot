import { m } from 'motion/react';
import { ArrowRight, CalendarDays, Check, Loader2, MapPin, PencilLine, Route, Users } from 'lucide-react';
import { useApp } from '../../../../app/state/AppContext';
import { useSendMessage } from '../../../../app/session/useSendMessage';
import { type PlanGateDecisionAction } from '../../types/planner';
import { Button } from '../../../../components/ui/Button';
import { cn } from '../../../../lib/utils';
import { emphasisEnter } from '../../../../lib/motion';
import { RESEARCH_START_TEXT } from '../../../chat/model/conversationFlow';
import { planGateEntries } from '../../model/planGateActions';
import React from 'react';

export const TripBriefPlanGate: React.FC = () => {
  const { state, dispatch } = useApp();
  const { sendMessage } = useSendMessage();
  const gate = state.planApprovalGate;
  const [editing, setEditing] = React.useState(false);
  const [guide, setGuide] = React.useState('');
  const [submitting, setSubmitting] = React.useState<PlanGateDecisionAction | null>(null);
  const revisionKey = gate ? `${gate.runId}#${gate.revision}` : null;

  React.useEffect(() => {
    setGuide('');
    setEditing(false);
  }, [revisionKey]);

  React.useEffect(() => {
    if (gate?.runId) document.getElementById('trip-brief-plan-gate-title')?.focus();
  }, [gate?.runId]);

  if (!gate) return null;
  const entries = planGateEntries(gate);
  const identity = state.controlledTripIdentity;
  const controlsBlocked = state.isStreaming || submitting !== null;
  const requirements = [
    ...gate.recognizedRequirements.hard,
    ...gate.recognizedRequirements.preferences,
    ...gate.recognizedRequirements.attention,
  ];
  const stayRequirements = requirements.filter((item) => /晚|停留/.test(item.summary));
  const budgetRequirements = requirements.filter((item) => /预算|花费|费用/.test(item.summary));
  const generalRequirements = requirements.filter((item) => !stayRequirements.includes(item) && !budgetRequirements.includes(item));
  const canRevise = entries.supplement && !gate.revisionLimitReached;

  const submit = async (action: PlanGateDecisionAction) => {
    const content = guide.trim();
    if (controlsBlocked || (action === 'supplement' && !content)) return;
    setSubmitting(action);
    try {
      const sent = await sendMessage(action === 'approve' ? RESEARCH_START_TEXT : action === 'supplement' ? '按这些修改重新整理旅行' : '取消本次规划', undefined, {
        resumeRunId: gate.runId,
        route: 'trip_refinement',
        gateDecision: { action, content: action === 'approve' || action === 'supplement' ? content : '' },
        assistantPendingLabel: action === 'approve' ? '正在开始调研' : action === 'supplement' ? '正在按你的修改重新整理' : undefined,
      });
      if (sent && action === 'cancel') {
        dispatch({ type: 'CLEAR_CHAT' });
      }
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <m.section data-testid="trip-brief-plan-gate" aria-labelledby="trip-brief-plan-gate-title" className="plan-review-card" variants={emphasisEnter} initial="hidden" animate="visible">
      <div className="plan-review-identity">
        <h2 id="trip-brief-plan-gate-title" tabIndex={-1}>这趟旅行</h2>
        {identity ? (
          <dl>
            <div><dt><Route size={15} />出发</dt><dd>{identity.origin.name}</dd></div>
            <div><dt><MapPin size={15} />目的地</dt><dd>{identity.destinations.map((place) => place.name).join('＋')}</dd></div>
            <div><dt><CalendarDays size={15} />日期</dt><dd>{identity.start_date}<br />{identity.end_date}</dd></div>
            <div><dt><Users size={15} />同行</dt><dd>{identity.party.adults} 位成人{identity.party.children ? `＋${identity.party.children} 位儿童` : ''}</dd></div>
          </dl>
        ) : (
          <p className="plan-review-fallback">请在下方确认本次旅行的需求与安排。</p>
        )}
      </div>

      {identity && (
        <div className="plan-review-style">
          <span>{identity.style.primary}</span>
          {identity.style.secondary_interests.map((item) => <span key={item}>{item}</span>)}
          {identity.party.elderly_companions && <span>老人同行</span>}
        </div>
      )}

      {stayRequirements.length > 0 && (
        <section className="plan-review-stays">
          <h2>每城停留</h2>
          <ul>{stayRequirements.map((item) => <li key={item.requirementId}>{item.summary}</li>)}</ul>
        </section>
      )}

      {budgetRequirements.length > 0 && (
        <section className="plan-review-budget">
          <h2>花费参考</h2>
          <p>{budgetRequirements.map((item) => item.summary).join('；')}</p>
        </section>
      )}

      {generalRequirements.length > 0 && (
        <section className="plan-review-requirements" aria-labelledby="plan-review-requirements-title">
          <h2 id="plan-review-requirements-title">已识别的旅行要求</h2>
          <ul>
            {generalRequirements.map((item) => <li key={item.requirementId} data-requirement={item.requirementId}><Check size={13} aria-hidden />{item.summary}</li>)}
          </ul>
        </section>
      )}

      {canRevise && (
        <div className="plan-review-edit">
          <button type="button" aria-expanded={editing} onClick={() => setEditing((value) => !value)} disabled={controlsBlocked}>
            <PencilLine size={14} />修改旅行信息
          </button>
          <div className={cn('plan-review-edit-panel', editing && 'is-open')}>
            <div>
              <label htmlFor="plan-review-guide">想改哪里？</label>
              <textarea
                id="plan-review-guide"
                value={guide}
                onChange={(event) => setGuide(event.target.value)}
                disabled={controlsBlocked}
                rows={3}
                maxLength={500}
                placeholder="例如：成都多住一晚，首日中午后到达，最后一天傍晚前返程。"
              />
              {editing && <Button variant="secondary" data-testid="plan-gate-supplement" disabled={controlsBlocked || !guide.trim()} onClick={() => void submit('supplement')}>
                {submitting === 'supplement' ? <Loader2 size={15} className="animate-spin" /> : <ArrowRight size={15} />}
                按修改重新整理
              </Button>}
            </div>
          </div>
        </div>
      )}

      <section className="plan-review-next" aria-label="接下来的生成步骤">
        <h2>接下来</h2>
        <div><span>01</span><p>查找交通与住宿</p><span>02</span><p>编排每天路线</p><span>03</span><p>生成完整计划</p></div>
      </section>

      <div className="plan-review-actions">
        {entries.approve && <Button size="lg" disabled={controlsBlocked} onClick={() => void submit('approve')}>
          {submitting === 'approve' ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
          确认并开始生成
        </Button>}
        {entries.cancel && <button type="button" disabled={controlsBlocked} onClick={() => void submit('cancel')}>取消规划</button>}
      </div>
    </m.section>
  );
};
