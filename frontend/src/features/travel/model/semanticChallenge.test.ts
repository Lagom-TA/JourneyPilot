import { describe, expect, it } from 'vitest';
import {
  SEMANTIC_DECISION_LABELS,
  SEMANTIC_LIMITS,
  SEMANTIC_STORAGE_BLOCKED_WARNING,
  SEMANTIC_STORAGE_KEY_WARNING,
  SEMANTIC_STORAGE_READ_WARNING,
  buildSemanticConfirmation,
  buildSemanticSupplement,
  clearSemanticDraft,
  clearSemanticDraftIfAccepted,
  isSemanticCallbackAccepted,
  isSemanticDecisionComplete,
  loadSemanticDraft,
  normalizeSemanticChallenge,
  saveSemanticDraft,
  semanticDecidedCount,
  semanticDraftStorageKey,
  type SemanticChallenge,
  type SemanticStorage,
} from './semanticChallenge';

function validExecution(): Record<string, unknown> {
  return {
    requirement_id: 'intent_test', requirement_type: 'intent', kind: 'must_exclude',
    target: 'visit', polarity: 'exclude', strength: 'hard',
    value: { value_type: 'category', categories: ['博物馆'] },
    applies_to: ['全体同行：2 位成人、0 位儿童'], scope: 'visit', public_summary: '不要去博物馆',
  };
}

function validPayload(): Record<string, unknown> {
  return {
    phase: 'semantics',
    challenge_id: 'challenge_opaque_1',
    revision: 2,
    approval_token: 'token_opaque_1',
    assertions: [
      {
        assertion_id: 'assertion_1',
        source_kind: 'current_request',
        context: '这次去杭州，想看当代建筑，但不要去博物馆。',
        quote: '不要去博物馆',
        object_label: '博物馆',
        domain_label: '景点与体验',
        allowed_decisions: ['avoid', 'historical', 'unknown'],
        execution: validExecution(),
      },
      {
        assertion_id: 'assertion_2',
        source_kind: 'current_request',
        context: '本次早餐喜欢本地小店，不喝连锁咖啡。',
        quote: '早餐喜欢本地小店',
        object_label: '本地小店',
        domain_label: '餐饮',
        allowed_decisions: ['include', 'unknown'],
        execution: { ...validExecution(), requirement_id: 'intent_breakfast', kind: 'must_include', target: 'dining', polarity: 'include', strength: 'soft', value: { value_type: 'category', categories: ['本地小店'] }, public_summary: '早餐喜欢本地小店' },
      },
    ],
  };
}

function challengeFrom(payload: unknown = validPayload()): SemanticChallenge {
  const result = normalizeSemanticChallenge(payload);
  if (!result.ok) throw new Error(`fixture should be valid: ${result.error}`);
  return result.challenge;
}

function withFirstAssertion(mutate: (row: Record<string, unknown>) => void, payload = validPayload()): Record<string, unknown> {
  const assertions = payload.assertions as Array<Record<string, unknown>>;
  mutate(assertions[0]);
  return payload;
}

function storageKeyFor(
  challenge: SemanticChallenge,
  scope: { sessionId: string; runId: string },
): string {
  const result = semanticDraftStorageKey(challenge, scope);
  if (!result.ok) throw new Error(`fixture should have a storage key: ${result.warning}`);
  return result.key;
}

function lengthBoundaryPayload(): Record<string, unknown> {
  const payload = validPayload();
  const row = (payload.assertions as Array<Record<string, unknown>>)[0];
  const quote = `${'引'.repeat(497)}博物馆`;
  row.context = `${'前'.repeat(SEMANTIC_LIMITS.context - quote.length)}${quote}`;
  row.quote = quote;
  row.object_label = '博物馆';
  row.question_context = '问'.repeat(SEMANTIC_LIMITS.questionContext);
  payload.approval_token = 't'.repeat(SEMANTIC_LIMITS.approvalToken);
  return payload;
}

class MemoryStorage implements SemanticStorage {
  readonly values = new Map<string, string>();
  failReads = false;
  failWrites = false;

  getItem(key: string): string | null {
    if (this.failReads) throw new Error('blocked');
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    if (this.failWrites) throw new Error('blocked');
    this.values.set(key, value);
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }
}

describe('normalizeSemanticChallenge', () => {
  it('normalizes a valid server payload without changing server text', () => {
    const result = normalizeSemanticChallenge(validPayload());

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.challenge).toMatchObject({
      phase: 'semantics',
      challengeId: 'challenge_opaque_1',
      revision: 2,
      approvalToken: 'token_opaque_1',
    });
    expect(result.challenge.assertions[0]).toEqual({
      assertionId: 'assertion_1',
      sourceKind: 'current_request',
      context: '这次去杭州，想看当代建筑，但不要去博物馆。',
      questionContext: null,
      quote: '不要去博物馆',
      objectLabel: '博物馆',
      domainLabel: '景点与体验',
      allowedDecisions: ['avoid', 'historical', 'unknown'],
      execution: {
        requirementId: 'intent_test', requirementType: 'intent', kind: 'must_exclude',
        target: 'visit', polarity: 'exclude', strength: 'hard',
        value: { value_type: 'category', categories: ['博物馆'] },
        appliesTo: ['全体同行：2 位成人、0 位儿童'], scope: 'visit', publicSummary: '不要去博物馆',
      },
    });
  });

  it('rejects positive decisions offered for unconfirmed historical sources', () => {
    for (const sourceKind of ['saved_preference', 'trip_context']) {
      for (const decision of ['include', 'avoid']) {
        const payload = withFirstAssertion((row) => {
          row.source_kind = sourceKind;
          row.allowed_decisions = [decision, 'unknown'];
        });
        expect(normalizeSemanticChallenge(payload).ok).toBe(false);
      }
      const safe = withFirstAssertion((row) => {
        row.source_kind = sourceKind;
        row.allowed_decisions = ['historical', 'unknown'];
      });
      expect(normalizeSemanticChallenge(safe).ok).toBe(true);
    }
  });

  it('accepts explicit_selection and keeps question_context display-only', () => {
    const payload = withFirstAssertion((row) => {
      row.source_kind = 'explicit_selection';
      row.context = '用户选中标签：亲子友好';
      row.question_context = '模型问题：这次旅行主要和谁一起？';
      row.quote = '亲子友好';
      row.object_label = '亲子友好';
    });
    const result = normalizeSemanticChallenge(payload);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.challenge.assertions[0]).toMatchObject({
      sourceKind: 'explicit_selection',
      context: '用户选中标签：亲子友好',
      questionContext: '模型问题：这次旅行主要和谁一起？',
      quote: '亲子友好',
      objectLabel: '亲子友好',
    });
  });

  it('never binds quote or object against question_context', () => {
    const quoteOutsideSource = normalizeSemanticChallenge(withFirstAssertion((row) => {
      row.context = '用户选中标签：亲子友好';
      row.question_context = '模型问题：不要去博物馆吗？';
      row.quote = '不要去博物馆';
      row.object_label = '博物馆';
    }));
    expect(quoteOutsideSource.ok).toBe(false);

    const objectOutsideQuote = normalizeSemanticChallenge(withFirstAssertion((row) => {
      row.context = '用户选中标签：亲子友好';
      row.question_context = '模型问题：想去博物馆还是美术馆？';
      row.quote = '亲子友好';
      row.object_label = '博物馆';
    }));
    expect(objectOutsideQuote.ok).toBe(false);
  });

  it('accepts exactly the backend maximum lengths and assertion count', () => {
    const boundary = normalizeSemanticChallenge(lengthBoundaryPayload());
    expect(boundary.ok).toBe(true);

    const base = (validPayload().assertions as Array<Record<string, unknown>>)[0];
    const atLimit = normalizeSemanticChallenge({
      ...validPayload(),
      assertions: Array.from({ length: SEMANTIC_LIMITS.assertions }, (_, index) => ({
        ...base,
        assertion_id: `assertion_${index}`,
      })),
    });
    expect(atLimit.ok).toBe(true);
  });

  it('rejects overflowed backend fields without truncating them', () => {
    const contextOverflow = lengthBoundaryPayload();
    const contextRow = (contextOverflow.assertions as Array<Record<string, unknown>>)[0];
    contextRow.context = `${contextRow.context}x`;
    expect(normalizeSemanticChallenge(contextOverflow).ok).toBe(false);

    const questionOverflow = lengthBoundaryPayload();
    const questionRow = (questionOverflow.assertions as Array<Record<string, unknown>>)[0];
    questionRow.question_context = `${questionRow.question_context}x`;
    expect(normalizeSemanticChallenge(questionOverflow).ok).toBe(false);

    const quoteOverflow = lengthBoundaryPayload();
    const quoteRow = (quoteOverflow.assertions as Array<Record<string, unknown>>)[0];
    const longQuote = `${'引'.repeat(498)}博物馆`;
    quoteRow.quote = longQuote;
    quoteRow.context = `${'前'.repeat(SEMANTIC_LIMITS.context - longQuote.length)}${longQuote}`;
    expect(normalizeSemanticChallenge(quoteOverflow).ok).toBe(false);

    expect(normalizeSemanticChallenge({
      ...lengthBoundaryPayload(),
      approval_token: 't'.repeat(SEMANTIC_LIMITS.approvalToken + 1),
    }).ok).toBe(false);
  });

  it.each([
    ['non-object payload', null],
    ['array payload', []],
    ['wrong phase', { ...validPayload(), phase: 'plan' }],
    ['missing challenge id', { ...validPayload(), challenge_id: '   ' }],
    ['overlong challenge id', { ...validPayload(), challenge_id: 'x'.repeat(SEMANTIC_LIMITS.challengeId + 1) }],
    ['non-integer revision', { ...validPayload(), revision: 1.5 }],
    ['negative revision', { ...validPayload(), revision: -1 }],
    ['missing approval token', { ...validPayload(), approval_token: '' }],
    ['overlong approval token', { ...validPayload(), approval_token: 'x'.repeat(SEMANTIC_LIMITS.approvalToken + 1) }],
    ['missing assertions', { ...validPayload(), assertions: undefined }],
    ['empty assertions', { ...validPayload(), assertions: [] }],
    ['overlong assertions', {
      ...validPayload(),
      assertions: Array.from({ length: SEMANTIC_LIMITS.assertions + 1 }, (_, index) => ({
        ...(validPayload().assertions as Array<Record<string, unknown>>)[0],
        assertion_id: `assertion_${index}`,
      })),
    }],
  ])('rejects %s', (_label, payload) => {
    const result = normalizeSemanticChallenge(payload);
    expect(result.ok).toBe(false);
  });

  it('counts Unicode source length the same way as the backend', () => {
    const payload = withFirstAssertion((row) => {
      row.context = '🙂'.repeat(12000) + '咖啡';
      row.quote = '咖啡';
      row.object_label = '咖啡';
    });
    expect(normalizeSemanticChallenge(payload).ok).toBe(true);
  });

  it('rejects hidden assertion fields that the user cannot review', () => {
    const payload = withFirstAssertion((row) => { row.hidden_query = '牛肉'; });
    expect(normalizeSemanticChallenge(payload).ok).toBe(false);
  });

  it('rejects a whole challenge when any assertion is malformed or duplicated', () => {
    const cases: Array<(row: Record<string, unknown>) => void> = [
      (row) => { row.assertion_id = ''; },
      (row) => { row.assertion_id = 'assertion_2'; },
      (row) => { row.source_kind = 'inferred_elsewhere'; },
      (row) => { row.context = '   '; },
      (row) => { row.context = 'x'.repeat(SEMANTIC_LIMITS.context + 1); },
      (row) => { row.question_context = 'x'.repeat(SEMANTIC_LIMITS.questionContext + 1); },
      (row) => { row.question_context = ''; },
      (row) => { row.quote = ''; },
      (row) => { row.quote = '不要博物馆'; },
      (row) => { row.quote = 'x'.repeat(SEMANTIC_LIMITS.quote + 1); },
      (row) => { row.object_label = '美术馆'; },
      (row) => { row.object_label = ''; },
      (row) => { row.object_label = 'x'.repeat(SEMANTIC_LIMITS.objectLabel + 1); },
      (row) => { row.domain_label = ''; },
      (row) => { row.domain_label = 'destination_researcher'; },
      (row) => { row.domain_label = 'x'.repeat(SEMANTIC_LIMITS.domainLabel + 1); },
      (row) => { row.allowed_decisions = []; },
      (row) => { row.allowed_decisions = 'avoid'; },
      (row) => { row.allowed_decisions = ['avoid', 'maybe']; },
      (row) => { row.allowed_decisions = ['avoid', 'avoid']; },
    ];

    for (const mutate of cases) {
      const result = normalizeSemanticChallenge(withFirstAssertion(mutate));
      expect(result.ok, mutate.toString()).toBe(false);
    }
  });

  it('does not drop a valid neighbour when one assertion is invalid', () => {
    const payload = withFirstAssertion((row) => {
      row.quote = '不在上下文里的句子';
      row.object_label = '不在上下文里的句子';
    });
    const result = normalizeSemanticChallenge(payload);
    expect(result.ok).toBe(false);
  });
});

describe('semantic decisions and callback payloads', () => {
  const challenge = challengeFrom();

  it('treats missing and unknown choices as incomplete', () => {
    expect(isSemanticDecisionComplete(challenge, {})).toBe(false);
    expect(isSemanticDecisionComplete(challenge, {
      assertion_1: 'unknown',
      assertion_2: 'include',
    })).toBe(false);
    expect(semanticDecidedCount(challenge, {
      assertion_1: 'unknown',
      assertion_2: 'include',
    })).toBe(1);
  });

  it('accepts only allowed non-unknown choices as complete', () => {
    expect(isSemanticDecisionComplete(challenge, {
      assertion_1: 'avoid',
      assertion_2: 'include',
    })).toBe(true);
    expect(isSemanticDecisionComplete(challenge, {
      assertion_1: 'include',
      assertion_2: 'include',
    })).toBe(false);
  });

  it('emits server token/id and per-item assertion_id/decision only', () => {
    const confirmation = buildSemanticConfirmation(challenge, {
      assertion_1: 'avoid',
      assertion_2: 'include',
    });

    expect(confirmation).toEqual({
      challenge_id: 'challenge_opaque_1',
      approval_token: 'token_opaque_1',
      revision: 2,
      decisions: [
        { assertion_id: 'assertion_1', decision: 'avoid' },
        { assertion_id: 'assertion_2', decision: 'include' },
      ],
    });
    expect(Object.keys(confirmation!.decisions[0])).toEqual(['assertion_id', 'decision']);
  });

  it('does not emit a confirmation while anything is unknown or absent', () => {
    expect(buildSemanticConfirmation(challenge, { assertion_1: 'avoid' })).toBeNull();
    expect(buildSemanticConfirmation(challenge, {
      assertion_1: 'unknown',
      assertion_2: 'include',
    })).toBeNull();
  });

  it('keeps correction text separate from confirmation decisions', () => {
    expect(buildSemanticSupplement(challenge, '  这里指的是室内展馆  ')).toEqual({
      challenge_id: 'challenge_opaque_1',
      approval_token: 'token_opaque_1',
      revision: 2,
      text: '这里指的是室内展馆',
    });
    expect(buildSemanticSupplement(challenge, '   ')).toBeNull();
    expect(buildSemanticSupplement(challenge, 'x'.repeat(SEMANTIC_LIMITS.supplement + 1))).toBeNull();
  });

  it('treats only a literal true callback result as accepted', () => {
    expect(isSemanticCallbackAccepted(true)).toBe(true);

    for (const result of [false, undefined, null, 0, 1, 'true', {}, []]) {
      expect(isSemanticCallbackAccepted(result), String(result)).toBe(false);
    }
  });

  it('keeps the draft for false, undefined or a wrong result and clears on true', () => {
    const storage = new MemoryStorage();
    const key = storageKeyFor(challenge, { sessionId: 'session_1', runId: 'run_1' });
    storage.setItem(key, 'draft');

    expect(clearSemanticDraftIfAccepted(storage, key, false)).toBe(false);
    expect(storage.values.get(key)).toBe('draft');
    expect(clearSemanticDraftIfAccepted(storage, key, undefined)).toBe(false);
    expect(storage.values.get(key)).toBe('draft');
    expect(clearSemanticDraftIfAccepted(storage, key, 'true')).toBe(false);
    expect(storage.values.get(key)).toBe('draft');

    expect(clearSemanticDraftIfAccepted(storage, key, true)).toBe(true);
    expect(storage.values.has(key)).toBe(false);
  });

  it('has human-readable labels for all decisions', () => {
    expect(SEMANTIC_DECISION_LABELS).toEqual({
      include: '按此理解执行',
      avoid: '不采用此理解',
      historical: '仅历史背景',
      unknown: '暂不确定',
    });
  });
});

describe('semantic draft storage', () => {
  const challenge = challengeFrom();
  const scope = { sessionId: 'session_1', runId: 'run_1' };

  it('isolates keys by exact session, run, challenge, revision and token', () => {
    const key = storageKeyFor(challenge, scope);
    expect(key).toContain('session_1');
    expect(key).toContain('run_1');
    expect(key).toContain('challenge_opaque_1');
    expect(key).toContain(':2:');
    expect(key).toContain(encodeURIComponent('token_opaque_1'));

    const otherRevision = challengeFrom({ ...validPayload(), revision: 3 });
    const otherToken = challengeFrom({ ...validPayload(), approval_token: 'token_opaque_2' });
    expect(storageKeyFor(challenge, { ...scope, sessionId: 'session_2' })).not.toBe(key);
    expect(storageKeyFor(challenge, { ...scope, runId: 'run_2' })).not.toBe(key);
    expect(storageKeyFor(otherRevision, scope)).not.toBe(key);
    expect(storageKeyFor(otherToken, scope)).not.toBe(key);
  });

  it('round-trips unsent choices and correction draft', () => {
    const storage = new MemoryStorage();
    const key = storageKeyFor(challenge, scope);
    const draft = {
      decisions: { assertion_1: 'unknown' as const, assertion_2: 'include' as const },
      supplement: '把博物馆改成室内展馆',
    };

    expect(saveSemanticDraft(storage, key, draft)).toBe(true);
    expect(loadSemanticDraft(storage, key, challenge)).toEqual({ draft, warning: null });
  });

  it('does not hydrate choices from another challenge key or disallowed options', () => {
    const storage = new MemoryStorage();
    const key = storageKeyFor(challenge, scope);
    storage.setItem(key, JSON.stringify({
      decisions: { assertion_1: 'include', assertion_2: 'avoid' },
      supplement: 42,
    }));

    expect(loadSemanticDraft(storage, key, challenge).draft).toEqual({
      decisions: {},
      supplement: '',
    });

    const otherKey = storageKeyFor(challenge, { ...scope, runId: 'run_2' });
    expect(loadSemanticDraft(storage, otherKey, challenge).draft).toEqual({
      decisions: {},
      supplement: '',
    });
  });

  it('fails closed for malformed Unicode in the storage key', () => {
    const result = semanticDraftStorageKey(challenge, {
      sessionId: '\ud800',
      runId: 'run_1',
    });
    expect(result).toEqual({ ok: false, warning: SEMANTIC_STORAGE_KEY_WARNING });
  });

  it('rejects an overlong stored correction draft instead of truncating it', () => {
    const storage = new MemoryStorage();
    const key = storageKeyFor(challenge, scope);
    storage.setItem(key, JSON.stringify({
      decisions: { assertion_1: 'avoid' },
      supplement: 'x'.repeat(SEMANTIC_LIMITS.supplement + 1),
    }));

    expect(loadSemanticDraft(storage, key, challenge)).toEqual({
      draft: { decisions: {}, supplement: '' },
      warning: SEMANTIC_STORAGE_READ_WARNING,
    });
  });

  it('reports blocked access and failed writes instead of throwing', () => {
    expect(loadSemanticDraft(null, 'key', challenge)).toEqual({
      draft: { decisions: {}, supplement: '' },
      warning: SEMANTIC_STORAGE_BLOCKED_WARNING,
    });
    expect(saveSemanticDraft(null, 'key', { decisions: {}, supplement: '' })).toBe(false);
    expect(clearSemanticDraft(null, 'key')).toBe(false);

    const blocked = new MemoryStorage();
    blocked.failReads = true;
    expect(loadSemanticDraft(blocked, 'key', challenge).warning).toBe(SEMANTIC_STORAGE_BLOCKED_WARNING);

    const unwritable = new MemoryStorage();
    unwritable.failWrites = true;
    expect(saveSemanticDraft(unwritable, 'key', { decisions: {}, supplement: '' })).toBe(false);
  });

  it('reports unreadable stored JSON and clears only the requested key', () => {
    const storage = new MemoryStorage();
    const key = storageKeyFor(challenge, scope);
    storage.setItem(key, '{not-json');
    expect(loadSemanticDraft(storage, key, challenge)).toEqual({
      draft: { decisions: {}, supplement: '' },
      warning: SEMANTIC_STORAGE_READ_WARNING,
    });

    storage.setItem(key, JSON.stringify({ decisions: {}, supplement: 'draft' }));
    storage.setItem('other-key', 'keep');
    expect(clearSemanticDraft(storage, key)).toBe(true);
    expect(storage.values.has(key)).toBe(false);
    expect(storage.values.get('other-key')).toBe('keep');
  });
});
