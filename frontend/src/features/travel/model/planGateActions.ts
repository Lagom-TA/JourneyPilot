import { type PlanApprovalGate } from "../types/planning";
import { type PlanGateDecisionAction } from "../types/planner";

export type PlanGateEntries = Record<PlanGateDecisionAction, boolean>;
export function planGateEntries(gate: Pick<PlanApprovalGate, 'decisionOptions' | 'status'>): PlanGateEntries {
    const live = gate.status !== 'cancelled';
    const has = (action: PlanGateDecisionAction) => live && gate.decisionOptions.includes(action);
    return {
        approve: has('approve'),
        edit: has('edit'),
        supplement: has('supplement'),
        cancel: has('cancel'),
    };
}