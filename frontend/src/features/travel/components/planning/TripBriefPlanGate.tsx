import { m } from 'motion/react';
import { ArrowRight, Check, Loader2, PencilLine, Users } from 'lucide-react';
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
  const { state } = useApp();
  const { sendMessage } = useSendMessage();
  const gate = state.planApprovalGate;
  const [editing, setEditing] = React.useState(false);
  const [guide, setGuide] = React.useState('');
  const [submitting, setSubmitting] = React.useState<PlanGateDecisionAction | null>(null);
  const [error, setError] = React.useState('');
  const revisionKey = gate ? `${gate.runId}#${gate.revision}` : null;

  React.useEffect(() => {
    setGuide('');
    setEditing(false);
    setError('');
  }, [revisionKey]);

  React.useEffect(() => {
    if (gate?.runId) document.getElementById('trip-brief-plan-gate-title')?.focus();
  }, [gate?.runId]);

  if (!gate) return null;
  const entries = planGateEntries(gate);
  const identity = state.controlledTripIdentity;
  const controlsBlocked = state.isStreaming || submitting !== null;
  const { hard, preferences } = gate.recognizedRequirements;
  const canRevise = entries.supplement;
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

  const submit = async (action: PlanGateDecisionAction) => {
    const content = guide.trim();
    if (controlsBlocked || (action === 'supplement' && !content)) return;
    setSubmitting(action);
    setError('');
    try {
      const sent = await sendMessage(action === 'approve' ? RESEARCH_START_TEXT : action === 'supplement' ? '按这些修改重新整理旅行' : '取消本次规划', undefined, {
        resumeRunId: gate.runId,
        route: 'trip_refinement',
        gateDecision: { action, content: action === 'approve' || action === 'supplement' ? content : '' },
        assistantPendingLabel: action === 'approve' ? '正在开始调研' : action === 'supplement' ? '正在按你的修改重新整理' : undefined,
      });
      if (!sent) {
        setError('这次操作未完成，旅行信息和修改已保留，请重试。');
      }
    } catch {
      setError('暂时无法提交，旅行信息和修改已保留，请重试。');
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <m.section data-testid="trip-brief-plan-gate" aria-labelledby="trip-brief-plan-gate-title" className="plan-gate-card" variants={emphasisEnter} initial="hidden" animate="visible">
      <header className="plan-gate-header">
        <p>开始规划前</p>
        <h2 id="trip-brief-plan-gate-title" tabIndex={-1}>确认旅行需求</h2>
        <span>{identity ? '已整理这趟旅行的信息。确认下面的要求后开始，或补充调整。' : '请确认本次旅行的需求与安排。'}</span>
      </header>

      {identity && (
        <div className="plan-gate-context" aria-label="旅行摘要">
          <p><Users size={14} aria-hidden /><span>{partySummary}</span></p>
          {styleTags.length > 0 && <div className="plan-gate-context-tags" aria-label="旅行风格">{styleTags.map((item) => <span key={item}>{item}</span>)}</div>}
        </div>
      )}

      {requirements.length > 0 ? (
        <section className="plan-gate-requirements" aria-labelledby="plan-gate-requirements-title">
          <h3 id="plan-gate-requirements-title">已识别的旅行要求</h3>
          <ul>
            {requirements.map((item) => <li key={item.requirementId} data-requirement={item.requirementId}><Check size={14} aria-hidden />{item.summary}</li>)}
          </ul>
        </section>
      ) : (
        <p className="plan-gate-note">还没有识别到额外要求，可以直接开始规划。</p>
      )}

      {canRevise && (
        <div className="plan-gate-edit">
          <button type="button" aria-expanded={editing} onClick={() => setEditing((value) => !value)} disabled={controlsBlocked}>
            <PencilLine size={15} />补充或调整旅行要求
          </button>
          <div className={cn('plan-gate-edit-panel', editing && 'is-open')}>
            <div>
              <label htmlFor="plan-gate-guide">想改哪里？</label>
              <textarea
                id="plan-gate-guide"
                value={guide}
                onChange={(event) => setGuide(event.target.value)}
                disabled={controlsBlocked}
                rows={3}
                maxLength={500}
                placeholder="例如：每天少安排一个景点，住宿选在地铁附近，首日中午后开始活动。"
              />
              {editing && <Button variant="secondary" data-testid="plan-gate-supplement" disabled={controlsBlocked || !guide.trim()} onClick={() => void submit('supplement')}>
                {submitting === 'supplement' ? <Loader2 size={15} className="animate-spin" /> : <ArrowRight size={15} />}
                按修改重新整理
              </Button>}
            </div>
          </div>
        </div>
      )}

      {error && <p role="alert" className="plan-gate-error">{error}</p>}

      <div className="plan-gate-actions">
        <p>{gate.revision > 0 ? '修改后会按这一版要求重新整理。' : '确认后开始查询资料，再安排每天路线。'}</p>
        <div>
          {entries.cancel && <button type="button" disabled={controlsBlocked} onClick={() => void submit('cancel')}>取消规划</button>}
          {entries.approve && <Button size="lg" disabled={controlsBlocked} onClick={() => void submit('approve')}>
            {submitting === 'approve' ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
            确认并开始生成
          </Button>}
        </div>
      </div>
    </m.section>
  );
};
