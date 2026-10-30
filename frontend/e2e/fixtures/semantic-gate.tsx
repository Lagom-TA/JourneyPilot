import React from 'react';
import { createRoot } from 'react-dom/client';
import { SemanticRequirementGate } from '../../src/features/travel/components/planning/SemanticRequirementGate';
import { normalizeSemanticChallenge, type SemanticConfirmation, type SemanticSupplement } from '../../src/features/travel/model/semanticChallenge';
import '../../src/index.css';

const execution = {
  requirement_id: 'constraint_coffee', requirement_type: 'constraint', kind: 'dietary_restriction',
  target: 'dietary_restriction', polarity: 'exclude', strength: 'hard',
  value: { value: '不喝咖啡', params: { amount: 1200, currency: 'CNY', per: 'total' } },
  applies_to: ['全体同行：2 位成人、0 位儿童'], scope: 'dietary_restriction', public_summary: '不喝咖啡',
};
const payload = {
  phase: 'semantics', challenge_id: 'offline-challenge', revision: 1, approval_token: 'offline-token',
  assertions: [
    { assertion_id: 'coffee', source_kind: 'current_request', context: '这次去杭州，不喝咖啡。', quote: '咖啡', object_label: '咖啡', domain_label: '餐饮', allowed_decisions: ['include', 'avoid', 'historical', 'unknown'], execution },
    { assertion_id: 'tokyo', source_kind: 'current_request', context: '去年去过东京，这次去杭州。', quote: '东京', object_label: '东京', domain_label: '地点', allowed_decisions: ['historical', 'unknown'], execution: { ...execution, requirement_id: 'intent_tokyo', requirement_type: 'intent', kind: 'theme', target: 'visit', polarity: 'include', strength: 'soft', value: { value_type: 'category', categories: ['东京'] }, scope: 'visit', public_summary: '去年去过东京' } },
  ],
};
const parsed = normalizeSemanticChallenge(payload);
if (!parsed.ok) throw new Error(parsed.error);
const probe = { accept: false, confirmations: [] as SemanticConfirmation[], supplements: [] as SemanticSupplement[] };
(window as unknown as { __semanticProbe: typeof probe }).__semanticProbe = probe;

createRoot(document.getElementById('root')!).render(
  <main style={{ maxWidth: 960, margin: '24px auto', padding: '0 16px' }}>
    <SemanticRequirementGate
      challenge={parsed.challenge} sessionId="offline-session" runId="offline-run"
      onConfirm={async (value) => { probe.confirmations.push(value); return probe.accept; }}
      onSupplement={async (value) => { probe.supplements.push(value); return probe.accept; }}
    />
  </main>,
);
