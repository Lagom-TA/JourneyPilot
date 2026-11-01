import { type PlanApprovalGate } from "../types/planning";
import { type PlanGateDecisionAction } from "../types/planner";

export type PlanGateEntries = Record<PlanGateDecisionAction, boolean>;
export function planGateEntries(gate: Pick<PlanApprovalGate, 'decisionOptions' | 'status'>): PlanGateEntries {
    const live = gate.status !== 'cancelled';
    const has = (action: PlanGateDecisionAction) => live && gate.decisionOptions.includes(action);
    return {
        approve: has('approve'),
        supplement: has('supplement'),
        retry: has('retry'),
        cancel: has('cancel'),
        // answer 只属于理解问题卡；计划门永远不会提供它。
        answer: false,
    };
}