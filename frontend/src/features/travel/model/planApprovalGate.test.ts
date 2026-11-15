import { describe, expect, it } from "vitest";
import { normalizePlanApprovalGate, planGateFromRunEvents } from "./planApprovalGate";
describe('normalizePlanApprovalGate', () => {
    it('restores the approval token without clarification controls', () => {
        const gate = normalizePlanApprovalGate({
            run_id: 'run_test',
            gate: 'plan',
            payload: {
                plan: {
                    steps: [{ step: 1, agents: ['destination_researcher'], tasks: {} }],
                },
                approval_token: 'plan_gate.approval:abc',
                decision_options: ['approve', 'cancel'],
            },
        });
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
                plan_text: '可以重试、补充要求或取消。',
                approval_token: 'failed-plan-token',
                decision_options: ['retry', 'supplement', 'cancel'],
            },
        }, 'pending', 'restored');
        expect(gate?.steps).toEqual([]);
        expect(gate?.decisionOptions).toEqual(['retry', 'supplement', 'cancel']);
        expect(gate?.approvalToken).toBe('failed-plan-token');
    });

    it('restores the latest plan gate from the run event window', () => {
        const gate = planGateFromRunEvents([
            {
                event_id: 1, run_id: 'run-events', sequence: 1, event_type: 'run.started',
                payload: {}, created_at: '2026-11-10T09:00:00Z',
            },
            {
                event_id: 2, run_id: 'run-events', sequence: 2, event_type: 'run.gate_raised',
                payload: {
                    status: 'awaiting_input',
                    gate: 'plan',
                    payload: {
                        revision: 1,
                        plan_text: '先比较交通和住宿，再安排每天的路线。',
                        plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: {} }] },
                        decision_options: ['approve', 'supplement', 'cancel'],
                    },
                },
                created_at: '2026-11-10T09:00:01Z',
            },
        ], 'run-events');
        expect(gate?.planText).toBe('先比较交通和住宿，再安排每天的路线。');
        expect(gate?.source).toBe('restored');
    });

    it('ignores planless event payloads', () => {
        expect(planGateFromRunEvents([{
            event_id: 1, run_id: 'run-events', sequence: 1, event_type: 'run.gate_raised',
            payload: { status: 'awaiting_input', gate: 'understanding', payload: { questions: [] } },
            created_at: '2026-11-10T09:00:00Z',
        }], 'run-events')).toBeNull();
    });

    it('restores a plan without fabricating a missing approval token', () => {
        const gate = normalizePlanApprovalGate({
            run_id: 'run-A',
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
