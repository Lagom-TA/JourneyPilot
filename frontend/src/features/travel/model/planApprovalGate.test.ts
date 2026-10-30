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
                approval_token: 'plan_gate.approval.v1:abc',
                decision_options: ['approve', 'cancel'],
                recognized_requirements: {
                    hard: [{ requirement_id: 'intent_no_museum', summary: '不安排博物馆' }],
                    preferences: [{ requirement_id: 'intent_architecture', summary: '偏好当代建筑' }],
                    attention: [{ requirement_id: 'conflict_1', summary: '两项要求相互冲突' }],
                },
            },
        });
        expect(gate?.planText).toBe('Research Tokyo');
        expect(gate?.approvalToken).toBe('plan_gate.approval.v1:abc');
        expect(gate?.recognizedRequirements).toEqual({
            hard: [{ requirementId: 'intent_no_museum', summary: '不安排博物馆' }],
            preferences: [{ requirementId: 'intent_architecture', summary: '偏好当代建筑' }],
        });
    });

    it('restores legacy semantic payloads as a plain question and fails closed on hidden fields', () => {
        const assertion = {
            assertion_id: 'a1', source_kind: 'current_request', context: '不喝咖啡', quote: '咖啡',
            object_label: '咖啡', domain_label: '餐饮', allowed_decisions: ['avoid', 'unknown'],
            execution: {
                requirement_id: 'constraint_coffee', requirement_type: 'constraint', kind: 'dietary_restriction',
                target: 'dietary_restriction', polarity: 'exclude', strength: 'hard',
                value: { value: '不喝咖啡', params: {} }, applies_to: ['全体同行：2 位成人、0 位儿童'],
                scope: 'dietary_restriction', public_summary: '不喝咖啡',
            },
        };
        const payload = { phase: 'semantics', challenge_id: 'challenge', revision: 1, approval_token: 'token', assertions: [assertion] };
        const gate = normalizePlanApprovalGate({ run_id: 'run', gate: 'plan', payload }, 'pending', 'restored');
        expect(gate?.semanticChallenge).toBeUndefined();
        expect(gate?.planText).toContain('请补充或更正');
        expect(gate?.decisionOptions).toEqual(['supplement', 'cancel']);
        const bad = normalizePlanApprovalGate({ run_id: 'run', payload: { ...payload, assertions: [{ ...assertion, hidden_query: '牛肉' }] } });
        expect(bad?.semanticError).toBeTruthy();
        expect(bad?.planText).toBe('');
        expect(bad?.decisionOptions).toEqual(['cancel']);
    });

    it('restores unanswered questions without inventing a plan or an approval', () => {
        const gate = normalizePlanApprovalGate({
            run_id: 'run_needs_clarification',
            payload: {
                plan: { steps: [] },
                plan_text: '**需要先补充的信息**：长辈的行动限制是什么？',
                approval_token: 'versioned-questions',
                decision_options: ['supplement', 'cancel'],
            },
        }, 'pending', 'restored');
        expect(gate?.steps).toEqual([]);
        expect(gate?.decisionOptions).toEqual(['supplement', 'cancel']);
        expect(gate?.planText).toContain('长辈的行动限制');
        expect(gate?.approvalToken).toBe('versioned-questions');
        expect(normalizePlanApprovalGate({
            run_id: 'empty_plan', payload: { plan: { steps: [] }, decision_options: ['approve', 'cancel'] },
        })).toBeNull();
    });

    it('keeps the server-approved retry action and never fabricates a legacy token', () => {
        const gate = normalizePlanApprovalGate({
            run_id: 'run_legacy',
            payload: {
                revision: 1,
                revision_limit: 1,
                revision_limit_reached: true,
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
