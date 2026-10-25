import { m } from "motion/react";
import { Check, ChevronDown, ListPlus, Loader2, PencilLine, Plus, RefreshCw, Square, X } from "lucide-react";
import { useApp } from "../../../../app/state/AppContext";
import { useSendMessage } from "../../../../app/session/useSendMessage";
import { type PlanGateDecisionAction, type TripSupplementCategory } from "../../types/planner";
import { Button } from "../../../../components/ui/Button";
import { ConfirmAction } from "../../../../components/ui/ConfirmAction";
import { Modal } from "../../../../components/ui/Modal";
import { cn, generateId } from "../../../../lib/utils";
import { emphasisEnter } from "../../../../lib/motion";
import { RESEARCH_START_TEXT } from "../../../chat/model/conversationFlow";
import { SUPPLEMENT_CATEGORIES, SUPPLEMENT_MAX, composeRequirementContent, planGateBudgetCopy, planGateEntries, requirementRowsOverLimit } from "../../model/planGateActions";
import React from 'react';
const AGENT_LABELS: Record<string, string> = {
    destination_researcher: '目的地与体验',
    transport_researcher: '交通可行性',
    accommodation_researcher: '住宿选择',
    itinerary_planner: '每日路线编排',
};
interface SupplementRow {
    id: string;
    category: TripSupplementCategory | '';
    content: string;
}
export const TripBriefPlanGate: React.FC = () => {
    const { state, dispatch } = useApp();
    const { sendMessage } = useSendMessage();
    const gate = state.planApprovalGate;
    const [openSupplement, setOpenSupplement] = React.useState(false);
    const [rows, setRows] = React.useState<SupplementRow[]>([]);
    const [guide, setGuide] = React.useState('');
    const [editing, setEditing] = React.useState(false);
    const [planDraft, setPlanDraft] = React.useState('');
    const [submitting, setSubmitting] = React.useState<PlanGateDecisionAction | null>(null);
    const guideRef = React.useRef<HTMLTextAreaElement>(null);
    React.useEffect(() => {
        const el = guideRef.current;
        if (!el)
            return;
        el.style.height = 'auto';
        el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }, [guide]);
    const revisionKey = gate ? `${gate.runId}#${gate.revision}` : null;
    const seenRevisionRef = React.useRef<string | null>(revisionKey);
    React.useEffect(() => {
        if (revisionKey === null || seenRevisionRef.current === revisionKey)
            return;
        seenRevisionRef.current = revisionKey;
        setRows([]);
        setGuide('');
        setOpenSupplement(false);
        setEditing(false);
        setPlanDraft('');
    }, [revisionKey]);
    if (!gate)
        return null;
    const cancelled = gate.status === 'cancelled';
    const runId = state.currentTripRunId;
    const entries = planGateEntries(gate);
    const budgetCopy = planGateBudgetCopy(gate);
    const showRefine = entries.approve || entries.supplement;
    const overLimit = requirementRowsOverLimit(rows);
    const requirementContent = composeRequirementContent(rows, guide);
    const controlsBlocked = state.isStreaming || submitting !== null || !runId;
    const addRow = () => setRows((prev) => [...prev, { id: generateId(), category: '', content: '' }]);
    const updateRow = (id: string, patch: Partial<SupplementRow>) => setRows((prev) => prev.map((row) => (row.id === id ? { ...row, ...patch } : row)));
    const removeRow = (id: string) => setRows((prev) => prev.filter((row) => row.id !== id));
    const toggleSupplement = () => setOpenSupplement((open) => {
        const next = !open;
        if (next && rows.length === 0)
            addRow();
        return next;
    });
    const openEditor = () => {
        setPlanDraft(gate.planText);
        setEditing(true);
    };
    const submit = async (action: PlanGateDecisionAction, content = '') => {
        if (!runId || submitting || state.isStreaming)
            return;
        if ((action === 'edit' || action === 'supplement') && !content.trim())
            return;
        if (action === 'approve' && overLimit)
            return;
        setSubmitting(action);
        const messageText = {
            approve: RESEARCH_START_TEXT,
            supplement: '按这些要求重新规划',
            edit: '按我改写的计划重新规划',
            cancel: '取消本次规划',
        }[action];
        const pendingLabel = {
            approve: '正在开始并行调研',
            supplement: '正在按你的要求重新规划',
            edit: '正在按你改写的计划重新规划',
            cancel: undefined,
        }[action];
        try {
            const sent = await sendMessage(messageText, undefined, {
                resumeRunId: runId,
                route: 'trip_refinement',
                gateDecision: { action, content },
                assistantPendingLabel: pendingLabel,
            });
            if (sent && action === 'approve' && content)
                dispatch({ type: 'FLASH_BOARDING_PASS' });
            if (sent && action === 'edit')
                setEditing(false);
        }
        finally {
            setSubmitting(null);
        }
    };
    const requirementGroups = [
        { key: 'hard', label: '硬要求', items: gate.recognizedRequirements.hard },
        { key: 'preferences', label: '偏好与侧重', items: gate.recognizedRequirements.preferences },
        { key: 'attention', label: '需要注意', items: gate.recognizedRequirements.attention },
    ].filter((group) => group.items.length > 0);
    return (<m.section data-testid="trip-brief-plan-gate" aria-labelledby="trip-brief-plan-gate-title" className="rounded-card border border-stroke bg-panel p-4 shadow-sm sm:p-5" variants={emphasisEnter} initial="hidden" animate="visible">
      <h2 id="trip-brief-plan-gate-title" className="text-xl font-semibold text-ink">{cancelled ? '已取消时的调研计划' : '调研计划已准备好'}</h2>


      <div className="mt-4 divide-y divide-stroke/60 overflow-hidden rounded-card border border-stroke bg-surface/30">
        {gate.steps.map((step) => {
            const tasked = step.agents.filter((agent) => step.tasks?.[agent]?.trim());
            const named = tasked.length > 0 ? tasked : step.agents;
            return (<div key={step.step} data-plan-step={step.step} className="px-3 py-2.5">
              <span className="block font-mono text-[11px] uppercase tracking-wide text-ink-muted">任务 {step.step}</span>
              <ul className="mt-1.5 space-y-2">
                {named.map((agent) => (<li key={agent} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[13px] leading-relaxed text-ink-secondary">
                    <span data-plan-agent={agent} className="shrink-0 rounded-label bg-accent-soft px-2 py-0.5 text-xs text-accent">
                      {AGENT_LABELS[agent] || '旅行调研'}
                    </span>
                    {step.tasks?.[agent]?.trim() && (<span className="min-w-0 flex-1 basis-full break-words sm:basis-auto">{step.tasks[agent].trim()}</span>)}
                  </li>))}
              </ul>
            </div>);
        })}
      </div>

      {requirementGroups.length > 0 && (<section className="mt-4 rounded-card border border-stroke bg-surface/30 px-3 py-2.5">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">系统识别到的要求</h3>
          <div className="mt-2 space-y-3">
            {requirementGroups.map((group) => (<div key={group.key} data-requirement-group={group.key}>
                <p className="text-xs font-medium text-ink">{group.label}</p>
                <ul className="mt-1 space-y-1.5">
                  {group.items.map((item) => (<li key={item.requirementId} data-requirement={item.requirementId} className="flex items-baseline gap-2 text-[13px] leading-relaxed text-ink-secondary">
                      <span aria-hidden className="mt-[0.35em] h-1 w-1 shrink-0 rounded-full bg-accent"/>
                      <span className="min-w-0 flex-1 break-words">{item.summary}</span>
                    </li>))}
                </ul>
              </div>))}
          </div>
        </section>)}

      {showRefine && (<div className="mt-4 space-y-3">

          <div className="rounded-card border border-stroke bg-panel px-3 py-2 focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/15">
            <textarea ref={guideRef} value={guide} onChange={(event) => setGuide(event.target.value)} disabled={controlsBlocked} rows={1} placeholder="补充你的想法：侧重点、临时约束或任何希望调研时考虑的事…" aria-label="补充想法" className="block max-h-40 min-h-[24px] w-full resize-none bg-transparent text-sm leading-relaxed text-ink placeholder:text-ink-secondary disabled:opacity-50"/>
          </div>


          <div>
            <button type="button" aria-expanded={openSupplement} disabled={controlsBlocked} onClick={toggleSupplement} className={cn('inline-flex h-9 items-center gap-1.5 rounded-card border px-3 text-sm font-medium transition-colors disabled:opacity-50', openSupplement ? 'border-accent/40 bg-accent-soft text-accent' : 'border-stroke text-ink-secondary hover:border-accent/40 hover:text-ink')}>
              <ListPlus size={14}/>
              追加信息
              {rows.some((row) => row.content.trim()) && (<span className="rounded-label bg-accent/15 px-1.5 text-[11px] tabular-nums text-accent">
                  {rows.filter((row) => row.content.trim()).length}
                </span>)}
              <ChevronDown size={13} className={cn('transition-transform', openSupplement && 'rotate-180')}/>
            </button>

            <div className={cn('grid transition-[grid-template-rows,opacity] duration-slow ease-standard', openSupplement ? 'mt-2 grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0')}>
              <div className="overflow-hidden">
                <div className="space-y-2">
                  {rows.map((row) => {
                const over = row.content.trim().length > SUPPLEMENT_MAX;
                return (<div key={row.id}>
                        <div className="flex items-center gap-2">
                          <select aria-label="追加信息分类" value={row.category} onChange={(event) => updateRow(row.id, { category: event.target.value as TripSupplementCategory | '' })} disabled={controlsBlocked} className="h-9 shrink-0 rounded-card border border-stroke bg-panel px-2 text-sm text-ink disabled:opacity-50">
                            <option value="">分类</option>
                            {SUPPLEMENT_CATEGORIES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                          </select>
                          <input aria-label="追加信息内容" value={row.content} onChange={(event) => updateRow(row.id, { content: event.target.value })} disabled={controlsBlocked} placeholder="写下本次规划需要考虑的一条要求" className={cn('h-9 min-w-0 flex-1 rounded-card border bg-panel px-3 text-sm text-ink disabled:opacity-50', over ? 'border-warning/60 focus:border-warning' : 'border-stroke')}/>
                          <button type="button" aria-label="删除这条" disabled={controlsBlocked} onClick={() => removeRow(row.id)} className="grid h-9 w-9 shrink-0 place-items-center rounded-card text-ink-muted transition-colors hover:bg-surface hover:text-danger disabled:opacity-40">
                            <X size={15}/>
                          </button>
                        </div>

                        {over && (<p role="alert" data-testid="supplement-over-limit" className="mt-1.5 flex items-center gap-1 rounded-card border border-error/25 bg-panel px-2 py-1 text-xs font-medium leading-5 text-error">
                            <span className="tabular-nums">{row.content.trim().length}/{SUPPLEMENT_MAX}</span>
                            字 · 超出后无法提交，请删减这一条
                          </p>)}
                      </div>);
            })}
                  <button type="button" disabled={controlsBlocked} onClick={addRow} className="inline-flex h-9 items-center gap-1.5 rounded-card px-2 text-xs font-semibold text-ink-muted transition-colors hover:bg-surface hover:text-ink disabled:opacity-40">
                    <Plus size={14}/> 再加一条
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>)}


      {budgetCopy && (<p data-testid="plan-gate-revision-budget" className="mt-4 text-[13px] leading-relaxed text-ink-muted">
          {budgetCopy}
        </p>)}


      {(entries.approve || entries.edit || entries.supplement || entries.cancel) && (<div className="mt-5 flex flex-wrap items-center gap-3">
          {entries.approve && (<Button type="button" size="lg" className="flex-1 basis-full sm:basis-auto" disabled={Boolean(submitting) || state.isStreaming || overLimit} onClick={() => void submit('approve', requirementContent)}>
              {submitting === 'approve' ? <Loader2 size={16} className="animate-spin"/> : <Check size={16}/>}
              确认调研计划并继续
            </Button>)}
          {entries.supplement && (<Button type="button" variant="secondary" data-testid="plan-gate-supplement" disabled={Boolean(submitting) || state.isStreaming || overLimit || !requirementContent.trim()} onClick={() => void submit('supplement', requirementContent)}>
              {submitting === 'supplement' ? <Loader2 size={15} className="animate-spin"/> : <RefreshCw size={15}/>}
              按这些要求重新规划
            </Button>)}
          {entries.edit && (<Button type="button" variant="secondary" data-testid="plan-gate-edit" disabled={Boolean(submitting) || state.isStreaming} onClick={openEditor}>
              <PencilLine size={15}/>
              改写计划全文
            </Button>)}
          {entries.cancel && (<ConfirmAction tone="error" confirmLabel="取消运行" confirmPending={submitting === 'cancel'} disabled={Boolean(submitting) || state.isStreaming} onConfirm={() => void submit('cancel')}>
              <Square size={13}/>取消规划
            </ConfirmAction>)}
        </div>)}


      {entries.supplement && !requirementContent.trim() && !overLimit && (<p role="alert" data-testid="plan-gate-supplement-empty" className="mt-2 text-xs leading-5 text-ink-muted">
          想让我重新规划，先在上面写下至少一条要求或一句补充想法。
        </p>)}


      <Modal open={editing} onClose={() => setEditing(false)} title="改写这份调研计划" maxWidth="max-w-2xl">
        <p className="text-[13px] leading-relaxed text-ink-secondary">
          你写下的这段文本会成为本轮的最终计划 —— 系统不再按原计划替你补任务。改完提交，我按它重新分配调研。
        </p>

        <textarea aria-label="调研计划全文" data-testid="plan-gate-plan-text" value={planDraft} onChange={(event) => setPlanDraft(event.target.value)} disabled={controlsBlocked} className="mt-3 block h-72 w-full resize-none rounded-card border border-stroke bg-surface/30 px-3 py-2 font-mono text-[13px] leading-relaxed text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:opacity-50"/>
        {!planDraft.trim() && (<p role="alert" data-testid="plan-gate-editor-empty" className="mt-2 rounded-card border border-error/25 bg-panel px-2 py-1 text-xs font-medium leading-5 text-error">
            计划全文不能为空 —— 空白的计划提交不了，请写下你要的调研安排。
          </p>)}
        <div className="mt-4 flex items-center gap-2">
          <Button type="button" data-testid="plan-gate-edit-submit" disabled={controlsBlocked || !planDraft.trim()} onClick={() => void submit('edit', planDraft)}>
            {submitting === 'edit' ? <Loader2 size={16} className="animate-spin"/> : <RefreshCw size={15}/>}
            按此计划重新规划
          </Button>
          <Button type="button" variant="ghost" disabled={Boolean(submitting)} onClick={() => setEditing(false)}>
            返回
          </Button>
        </div>
      </Modal>
    </m.section>);
};
