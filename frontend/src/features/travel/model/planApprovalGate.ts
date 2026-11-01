import { type PlanApprovalGate, type PlanGateStep } from "../types/planning";
import { type PlanGateDecisionAction } from "../types/planner";
export const PLAN_GATE_ACTIONS: PlanGateDecisionAction[] = ['approve', 'supplement', 'retry', 'cancel'];
export function normalizePlanApprovalGate(event: {
    run_id?: string;
    gate?: string;
    payload?: Record<string, unknown>;
}, status: PlanApprovalGate['status'] = 'pending', source: PlanApprovalGate['source'] = 'live'): PlanApprovalGate | null {
    const payload = event.payload || {};
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
    const planFailed = steps.length === 0
        && !decisionOptions.includes('approve')
        && decisionOptions.includes('retry')
        && Boolean(String(payload.plan_text || '').trim());
    if (decisionOptions.length === 0 || (steps.length === 0 && !planFailed))
        return null;
    return {
        gate: event.gate || String(payload.gate || 'plan'),
        runId: event.run_id,
        status,
        source,
        approvalToken: typeof payload.approval_token === 'string' && payload.approval_token.trim() ? payload.approval_token : undefined,
        revision: Number(payload.revision) || 0,
        steps,
        planText: String(payload.plan_text || ''),
        decisionOptions,
    };
}
