import { type PlanApprovalGate, type PlanGateRecognizedRequirements, type PlanGateRequirement, type PlanGateStep } from "../types/planning";
import { type PlanGateDecisionAction } from "../types/planner";
import { normalizeSemanticChallenge } from "./semanticChallenge";
export const PLAN_GATE_ACTIONS: PlanGateDecisionAction[] = ['approve', 'edit', 'supplement', 'retry', 'cancel'];
function normalizeRequirements(raw: unknown): PlanGateRequirement[] {
    if (!Array.isArray(raw))
        return [];
    const rows: PlanGateRequirement[] = [];
    for (const entry of raw) {
        if (!entry || typeof entry !== 'object')
            continue;
        const row = entry as Record<string, unknown>;
        const requirementId = String(row.requirement_id || '').trim();
        const summary = String(row.summary || '').trim();
        if (!requirementId || !summary)
            continue;
        rows.push({ requirementId, summary });
    }
    return rows;
}
function normalizeRecognizedRequirements(raw: unknown): PlanGateRecognizedRequirements {
    const source = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
    return {
        hard: normalizeRequirements(source.hard),
        preferences: normalizeRequirements(source.preferences),
    };
}
export function normalizePlanApprovalGate(event: {
    run_id?: string;
    gate?: string;
    payload?: Record<string, unknown>;
}, status: PlanApprovalGate['status'] = 'pending', source: PlanApprovalGate['source'] = 'live'): PlanApprovalGate | null {
    const payload = event.payload || {};
    if (payload.phase === 'semantics') {
        if (!event.run_id) return null;
        const parsed = normalizeSemanticChallenge(payload);
        const fallbackRevision = typeof payload.revision === 'number' && Number.isSafeInteger(payload.revision) && payload.revision >= 0 ? payload.revision : 0;
        return {
            gate: event.gate || 'plan', runId: event.run_id, status, source,
            approvalToken: parsed.ok ? parsed.challenge.approvalToken : undefined,
            semanticError: parsed.ok ? undefined : '无法加载完整的需求核对内容，请刷新或取消规划。',
            revision: parsed.ok ? parsed.challenge.revision : fallbackRevision,
            revisionLimit: 0, revisionLimitReached: false, steps: [],
            planText: parsed.ok ? '请补充或更正这项旅行要求，回答后会重新分析。' : '',
            decisionOptions: parsed.ok ? ['supplement', 'cancel'] : ['cancel'],
            recognizedRequirements: { hard: [], preferences: [] },
        };
    }
    const plan = payload.plan && typeof payload.plan === 'object' ? payload.plan as Record<string, unknown> : {};
    const rawSteps = Array.isArray(plan.steps) ? plan.steps : [];
    const steps: PlanGateStep[] = [];
    for (const item of rawSteps) {
        if (!item || typeof item !== 'object')
            continue;
        const row = item as Record<string, unknown>;
        const agents = Array.isArray(row.agents) ? row.agents.map(String) : [];
        const tasks = row.tasks && typeof row.tasks === 'object'
            ? Object.fromEntries(Object.entries(row.tasks as Record<string, unknown>).map(([key, value]) => [key, String(value || '')]))
            : {};
        steps.push({ step: Number(row.step) || 0, agents, tasks });
    }
    if (!event.run_id)
        return null;
    const rawOptions = Array.isArray(payload.decision_options) ? payload.decision_options.map(String) : [];
    const decisionOptions = rawOptions.filter((option): option is PlanGateDecisionAction => (PLAN_GATE_ACTIONS as string[]).includes(option));
    const clarification = steps.length === 0
        && !decisionOptions.includes('approve')
        && decisionOptions.includes('supplement')
        && Boolean(String(payload.plan_text || '').trim());
    if (decisionOptions.length === 0 || (steps.length === 0 && !clarification))
        return null;
    const revisionLimitReached = Boolean(payload.revision_limit_reached);
    return {
        gate: event.gate || String(payload.gate || 'plan'),
        runId: event.run_id,
        status,
        source,
        approvalToken: typeof payload.approval_token === 'string' && payload.approval_token.trim() ? payload.approval_token : undefined,
        revision: Number(payload.revision) || 0,
        revisionLimit: Number(payload.revision_limit) || 1,
        revisionLimitReached,
        steps,
        planText: String(payload.plan_text || ''),
        decisionOptions,
        recognizedRequirements: normalizeRecognizedRequirements(payload.recognized_requirements),
    };
}
