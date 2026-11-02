import { describe, expect, it } from "vitest";
import { normalizePlanApprovalGate } from "./planApprovalGate";
describe('normalizePlanApprovalGate', () => {
    it('restores the requirement summary without clarification controls', () => {
        const gate = normalizePlanApprovalGate({
            run_id: 'run_test',
            gate: 'plan',
            payload: {
                plan: {
                    steps: [{ step: 1, agents: ['destination_researcher'], tasks: {} }],
                },
                plan_text: 'Research Tokyo',
                approval_token: 'plan_gate.approval:abc',
                decision_options: ['approve', 'cancel'],
            },
        });
        expect(gate?.planText).toBe('Research Tokyo');
        expect(gate?.approvalToken).toBe('plan_gate.approval:abc');
    });

    it('does not offer approval when no research plan exists', () => {
        expect(normalizePlanApprovalGate({
            run_id: 'empty_plan', payload: { plan: { steps: [] }, decision_options: ['approve', 'cancel'] },
        })).toBeNull();
        expect(normalizePlanApprovalGate({
            run_id: 'missing_plan', payload: { plan: { steps: [] }, plan_text: '需要先补充信息', decision_options: ['supplement', 'cancel'] },
        })).toBeNull();
    });

    it('keeps retry and supplement available when a research plan could not be generated', () => {
        const gate = normalizePlanApprovalGate({
            run_id: 'run_plan_failed',
            payload: {
                plan: { steps: [] },
                plan_text: '**研究方案暂未生成**\n可以重试、补充要求或取消。',
                approval_token: 'failed-plan-token',
                decision_options: ['retry', 'supplement', 'cancel'],
            },
        }, 'pending', 'restored');
        expect(gate?.steps).toEqual([]);
        expect(gate?.decisionOptions).toEqual(['retry', 'supplement', 'cancel']);
        expect(gate?.planText).toContain('研究方案暂未生成');
        expect(gate?.approvalToken).toBe('failed-plan-token');
    });

    it('restores a plan without fabricating a missing approval token', () => {
        const gate = normalizePlanApprovalGate({
            run_id: 'run_legacy',
            payload: {
                revision: 1,
                approval_token: null,
                decision_options: ['supplement', 'cancel'],
                plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: {} }] },
            },
        }, 'pending', 'restored');
        expect(gate?.source).toBe('restored');
        expect(gate?.approvalToken).toBeUndefined();
        expect(gate?.decisionOptions).toEqual(['supplement', 'cancel']);
    });
});
