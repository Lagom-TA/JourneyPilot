import { type PlanApprovalGate } from "../types/planning";
import { type PlanGateDecisionAction, type TripSupplementCategory } from "../types/planner";
export const SUPPLEMENT_MAX = 50;
export const SUPPLEMENT_CATEGORIES: Array<{
    value: TripSupplementCategory;
    label: string;
}> = [
    { value: 'food', label: '饮食口味' },
    { value: 'transport', label: '交通与租车' },
    { value: 'accommodation', label: '住宿倾向' },
    { value: 'pace', label: '每日节奏' },
    { value: 'must_do', label: '必去体验' },
    { value: 'other', label: '其他要求' },
];
export function supplementCategoryLabel(value: TripSupplementCategory | ''): string {
    return SUPPLEMENT_CATEGORIES.find((item) => item.value === value)?.label || '其他要求';
}
export interface RequirementRow {
    category: TripSupplementCategory | '';
    content: string;
}
export function requirementRowsOverLimit(rows: RequirementRow[]): boolean {
    return rows.some((row) => row.content.trim().length > SUPPLEMENT_MAX);
}
export function composeRequirementContent(rows: RequirementRow[], guide: string): string {
    const lines = rows
        .filter((row) => row.content.trim())
        .map((row) => `[${supplementCategoryLabel(row.category)}] ${row.content.trim()}`);
    const guideText = guide.trim();
    if (guideText)
        lines.push(`[补充想法] ${guideText}`);
    return lines.join('\n');
}
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
export function planGateRevisionsLeft(gate: Pick<PlanApprovalGate, 'revision' | 'revisionLimit'>): number {
    return Math.max(0, gate.revisionLimit - gate.revision);
}
export function planGateBudgetCopy(gate: Pick<PlanApprovalGate, 'decisionOptions' | 'status' | 'revision' | 'revisionLimit'>): string | null {
    if (gate.status === 'cancelled')
        return null;
    const entries = planGateEntries(gate);
    if (!entries.edit && !entries.supplement)
        return null;
    const left = planGateRevisionsLeft(gate);
    if (left <= 0)
        return null;
    return `你还可以让我按你的要求重新规划 ${left} 次；直接确认则立即开始调研。`;
}
