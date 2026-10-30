/**
 * Server-provided semantic requirement challenges.
 *
 * The server is the only source of context, quotes and allowed decisions. This
 * module validates that payload strictly and keeps the UI contract separate
 * from raw server objects. A malformed challenge is rejected as a whole; it is
 * never partially rendered.
 */

export const SEMANTIC_SOURCE_KINDS = [
  'current_request',
  'explicit_supplement',
  'structured_form',
  'saved_preference',
  'trip_context',
  'explicit_selection',
] as const;

export type SemanticSourceKind = (typeof SEMANTIC_SOURCE_KINDS)[number];

export const SEMANTIC_DECISIONS = ['include', 'avoid', 'historical', 'unknown'] as const;

export type SemanticDecision = (typeof SEMANTIC_DECISIONS)[number];

export const SEMANTIC_DECISION_LABELS: Record<SemanticDecision, string> = {
  include: '按此理解执行',
  avoid: '不采用此理解',
  historical: '仅历史背景',
  unknown: '暂不确定',
};

export const SEMANTIC_SOURCE_LABELS: Record<SemanticSourceKind, string> = {
  current_request: '本次请求原文',
  explicit_supplement: '补充说明',
  structured_form: '结构化表单',
  saved_preference: '已保存偏好',
  trip_context: '行程背景',
  explicit_selection: '用户选中标签',
};

export const SEMANTIC_LIMITS = {
  challengeId: 256,
  assertionId: 256,
  approvalToken: 200,
  context: 20000,
  questionContext: 4000,
  quote: 500,
  objectLabel: 200,
  domainLabel: 200,
  assertions: 128,
  supplement: 2000,
} as const;

export type SemanticExecutionValue = string | number | boolean | null
  | SemanticExecutionValue[] | { [key: string]: SemanticExecutionValue };

export interface SemanticRequirementExecution {
  requirementId: string;
  requirementType: 'intent' | 'constraint';
  kind: string;
  target: string;
  polarity: 'include' | 'exclude' | 'neutral';
  strength: 'hard' | 'soft' | 'informational';
  value: { [key: string]: SemanticExecutionValue };
  appliesTo: string[];
  scope: string;
  publicSummary: string;
}

export interface SemanticAssertion {
  assertionId: string;
  sourceKind: SemanticSourceKind;
  /** Complete backend SourceEvidence.text. */
  context: string;
  /** Display-only model question; never evidence for authorization. */
  questionContext: string | null;
  /** Literal excerpt of `context` supplied by the server. */
  quote: string;
  /** Literal object phrase inside `quote`. */
  objectLabel: string;
  domainLabel: string;
  allowedDecisions: SemanticDecision[];
  execution: SemanticRequirementExecution;
}

export interface SemanticChallenge {
  phase: 'semantics';
  challengeId: string;
  revision: number;
  approvalToken: string;
  assertions: SemanticAssertion[];
}

export type SemanticChallengeResult =
  | { ok: true; challenge: SemanticChallenge }
  | { ok: false; error: string };

const SEMANTIC_DOMAIN_LABELS = new Set([
  '地点', '景点与体验', '餐饮', '住宿', '交通', '节奏', '预算', '无障碍', '时间安排', '其他限制', '输出要求',
]);

const ASSERTION_VISIBLE_FIELDS = new Set([
  'assertion_id', 'source_kind', 'context', 'question_context', 'quote',
  'object_label', 'domain_label', 'allowed_decisions', 'execution',
]);

function reject(error: string): SemanticChallengeResult {
  return { ok: false, error };
}

function requiredString(
  value: unknown,
  label: string,
  maxLength: number,
): { value: string } | { error: string } {
  if (typeof value !== 'string' || value.trim().length === 0) {
    return { error: `${label}缺失。` };
  }
  // Backend lengths and evidence spans count Unicode code points, not UTF-16 units.
  if (Array.from(value).length > maxLength) {
    return { error: `${label}过长。` };
  }
  return { value };
}

const EXECUTION_FIELDS = new Set([
  'requirement_id', 'requirement_type', 'kind', 'target', 'polarity', 'strength',
  'value', 'applies_to', 'scope', 'public_summary',
]);

function isExecutionValue(value: unknown, depth = 0): value is SemanticExecutionValue {
  if (depth > 8) return false;
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.every((item) => isExecutionValue(item, depth + 1));
  if (value && typeof value === 'object') {
    return Object.values(value as Record<string, unknown>).every((item) => isExecutionValue(item, depth + 1));
  }
  return false;
}

function normalizeExecution(raw: unknown):
  | { execution: SemanticRequirementExecution }
  | { error: string } {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { error: '执行语义缺失。' };
  const row = raw as Record<string, unknown>;
  if (Object.keys(row).some((key) => !EXECUTION_FIELDS.has(key))) return { error: '执行语义包含隐藏字段。' };
  const strings = {
    requirement_id: 128, kind: 64, target: 200, scope: 128, public_summary: 500,
  } as const;
  const parsed: Record<string, string> = {};
  for (const [key, limit] of Object.entries(strings)) {
    const value = requiredString(row[key], '执行语义字段', limit);
    if ('error' in value) return value;
    parsed[key] = value.value;
  }
  if (row.requirement_type !== 'intent' && row.requirement_type !== 'constraint') return { error: '执行语义类型不受支持。' };
  if (row.polarity !== 'include' && row.polarity !== 'exclude' && row.polarity !== 'neutral') return { error: '执行语义极性不受支持。' };
  if (row.strength !== 'hard' && row.strength !== 'soft' && row.strength !== 'informational') return { error: '执行语义强度不受支持。' };
  if (!row.value || typeof row.value !== 'object' || Array.isArray(row.value) || !isExecutionValue(row.value)) {
    return { error: '执行参数不是有效的结构化值。' };
  }
  if (!Array.isArray(row.applies_to) || row.applies_to.length === 0 || row.applies_to.length > 32) {
    return { error: '执行语义的适用人缺失。' };
  }
  const appliesTo: string[] = [];
  for (const item of row.applies_to) {
    const value = requiredString(item, '执行语义适用人', 128);
    if ('error' in value) return value;
    appliesTo.push(value.value);
  }
  try {
    if (JSON.stringify(row.value).length > 8000) return { error: '执行参数过长。' };
  } catch {
    return { error: '执行参数无法读取。' };
  }
  return {
    execution: {
      requirementId: parsed.requirement_id,
      requirementType: row.requirement_type,
      kind: parsed.kind,
      target: parsed.target,
      polarity: row.polarity,
      strength: row.strength,
      value: row.value as { [key: string]: SemanticExecutionValue },
      appliesTo,
      scope: parsed.scope,
      publicSummary: parsed.public_summary,
    },
  };
}

/**
 * Validate a raw `phase === 'semantics'` payload.
 *
 * Validation is intentionally all-or-nothing: duplicate assertion IDs, a
 * non-literal quote/object, an unknown decision or any overlong field rejects
 * the complete challenge instead of dropping a single assertion.
 */
export function normalizeSemanticChallenge(raw: unknown): SemanticChallengeResult {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return reject('语义确认数据格式不正确。');
  }

  const payload = raw as Record<string, unknown>;
  if (payload.phase !== 'semantics') {
    return reject('语义确认数据阶段不正确。');
  }

  const challengeId = requiredString(payload.challenge_id, '确认编号', SEMANTIC_LIMITS.challengeId);
  if ('error' in challengeId) return reject(challengeId.error);

  const approvalToken = requiredString(payload.approval_token, '确认凭据', SEMANTIC_LIMITS.approvalToken);
  if ('error' in approvalToken) return reject(approvalToken.error);

  const revision = payload.revision;
  if (
    typeof revision !== 'number'
    || !Number.isSafeInteger(revision)
    || revision < 0
  ) {
    return reject('确认版本号必须是非负整数。');
  }

  if (!Array.isArray(payload.assertions)) {
    return reject('语义确认条目缺失。');
  }
  if (payload.assertions.length === 0) {
    return reject('语义确认至少需要一条内容。');
  }
  if (payload.assertions.length > SEMANTIC_LIMITS.assertions) {
    return reject('语义确认条数过多。');
  }

  const seenAssertionIds = new Set<string>();
  const assertions: SemanticAssertion[] = [];

  for (let index = 0; index < payload.assertions.length; index += 1) {
    const entry = payload.assertions[index];
    const position = `第 ${index + 1} 条语义确认`;
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
      return reject(`${position}格式不正确。`);
    }
    const row = entry as Record<string, unknown>;
    if (Object.keys(row).some((key) => !ASSERTION_VISIBLE_FIELDS.has(key))) {
      return reject(`${position}包含未展示的字段，无法确认。`);
    }

    const assertionId = requiredString(row.assertion_id, `${position}编号`, SEMANTIC_LIMITS.assertionId);
    if ('error' in assertionId) return reject(assertionId.error);
    if (seenAssertionIds.has(assertionId.value)) {
      return reject(`${position}编号重复。`);
    }
    seenAssertionIds.add(assertionId.value);

    if (
      typeof row.source_kind !== 'string'
      || !(SEMANTIC_SOURCE_KINDS as readonly string[]).includes(row.source_kind)
    ) {
      return reject(`${position}的来源类型不受支持。`);
    }
    const sourceKind = row.source_kind as SemanticSourceKind;

    const context = requiredString(row.context, `${position}的来源上下文`, SEMANTIC_LIMITS.context);
    if ('error' in context) return reject(context.error);

    let questionContext: string | null = null;
    if (row.question_context !== undefined && row.question_context !== null) {
      const parsedQuestionContext = requiredString(
        row.question_context,
        `${position}的问题上下文`,
        SEMANTIC_LIMITS.questionContext,
      );
      if ('error' in parsedQuestionContext) return reject(parsedQuestionContext.error);
      questionContext = parsedQuestionContext.value;
    }

    const quote = requiredString(row.quote, `${position}的原文摘录`, SEMANTIC_LIMITS.quote);
    if ('error' in quote) return reject(quote.error);

    const objectLabel = requiredString(row.object_label, `${position}的识别对象`, SEMANTIC_LIMITS.objectLabel);
    if ('error' in objectLabel) return reject(objectLabel.error);

    const domainLabel = requiredString(row.domain_label, `${position}的领域`, SEMANTIC_LIMITS.domainLabel);
    if ('error' in domainLabel) return reject(domainLabel.error);
    if (!SEMANTIC_DOMAIN_LABELS.has(domainLabel.value)) return reject(`${position}的领域不受支持。`);

    if (!quote.value.includes(objectLabel.value)) {
      return reject(`${position}的识别对象不是原文摘录中的原样文字。`);
    }
    if (!context.value.includes(quote.value)) {
      return reject(`${position}的原文摘录不是来源上下文中的原样文字。`);
    }

    if (!Array.isArray(row.allowed_decisions)) {
      return reject(`${position}缺少可选处理方式。`);
    }
    const rawDecisions = row.allowed_decisions;
    if (rawDecisions.length === 0) {
      return reject(`${position}至少需要一种可选处理方式。`);
    }
    if (rawDecisions.length > SEMANTIC_DECISIONS.length) {
      return reject(`${position}的可选处理方式过多。`);
    }

    const seenDecisions = new Set<SemanticDecision>();
    const allowedDecisions: SemanticDecision[] = [];
    for (const rawDecision of rawDecisions) {
      if (
        typeof rawDecision !== 'string'
        || !(SEMANTIC_DECISIONS as readonly string[]).includes(rawDecision)
      ) {
        return reject(`${position}包含未知的处理方式。`);
      }
      const decision = rawDecision as SemanticDecision;
      if (seenDecisions.has(decision)) {
        return reject(`${position}包含重复的处理方式。`);
      }
      seenDecisions.add(decision);
      allowedDecisions.push(decision);
    }

    if ((sourceKind === 'saved_preference' || sourceKind === 'trip_context')
      && allowedDecisions.some((decision) => decision === 'include' || decision === 'avoid')) {
      return reject(`${position}的历史来源不能直接授权本次需求。`);
    }

    const execution = normalizeExecution(row.execution);
    if ('error' in execution) return reject(`${position}${execution.error}`);

    assertions.push({
      assertionId: assertionId.value,
      sourceKind,
      context: context.value,
      questionContext,
      quote: quote.value,
      objectLabel: objectLabel.value,
      domainLabel: domainLabel.value,
      allowedDecisions,
      execution: execution.execution,
    });
  }

  return {
    ok: true,
    challenge: {
      phase: 'semantics',
      challengeId: challengeId.value,
      revision,
      approvalToken: approvalToken.value,
      assertions,
    },
  };
}

/* -------------------------------------------------------------------------- */
/* Draft storage                                                              */
/* -------------------------------------------------------------------------- */

export const SEMANTIC_DRAFT_STORAGE_PREFIX = 'journeypilot.semantic-gate.v1';
export const SEMANTIC_STORAGE_BLOCKED_WARNING =
  '浏览器阻止了本地暂存：未提交的选择和更正只保留在当前页面，刷新后会丢失。';
export const SEMANTIC_STORAGE_READ_WARNING =
  '本地暂存的选择无法读取，已从空白开始。';
export const SEMANTIC_STORAGE_KEY_WARNING =
  '当前会话包含无法安全暂存的字符：未提交的选择和更正只保留在当前页面，刷新后会丢失。';

export interface SemanticDraftScope {
  sessionId: string;
  runId: string;
}

export interface SemanticDraft {
  decisions: Record<string, SemanticDecision>;
  supplement: string;
}

export interface SemanticDraftLoad {
  draft: SemanticDraft;
  warning: string | null;
}

export interface SemanticStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export type SemanticDraftStorageKeyResult =
  | { ok: true; key: string }
  | { ok: false; warning: string };

export const emptySemanticDraft = (): SemanticDraft => ({ decisions: {}, supplement: '' });

/**
 * The key contains the exact session, run, challenge, revision and approval
 * token. A regenerated challenge therefore cannot hydrate stale radio choices.
 */
export function semanticDraftStorageKey(
  challenge: SemanticChallenge,
  scope: SemanticDraftScope,
): SemanticDraftStorageKeyResult {
  try {
    const encode = (value: string) => encodeURIComponent(value);
    return {
      ok: true,
      key: [
        SEMANTIC_DRAFT_STORAGE_PREFIX,
        encode(scope.sessionId),
        encode(scope.runId),
        encode(challenge.challengeId),
        String(challenge.revision),
        encode(challenge.approvalToken),
      ].join(':'),
    };
  } catch {
    // encodeURIComponent throws on lone surrogates. Do not fall back to a
    // colliding key: the UI must keep the draft in memory and warn instead.
    return { ok: false, warning: SEMANTIC_STORAGE_KEY_WARNING };
  }
}

function isSemanticDecision(value: unknown): value is SemanticDecision {
  return typeof value === 'string' && (SEMANTIC_DECISIONS as readonly string[]).includes(value);
}

export function loadSemanticDraft(
  storage: SemanticStorage | null,
  key: string,
  challenge: SemanticChallenge,
): SemanticDraftLoad {
  const fallback = { draft: emptySemanticDraft(), warning: null };
  if (!storage) {
    return { draft: emptySemanticDraft(), warning: SEMANTIC_STORAGE_BLOCKED_WARNING };
  }

  let raw: string | null;
  try {
    raw = storage.getItem(key);
  } catch {
    return { draft: emptySemanticDraft(), warning: SEMANTIC_STORAGE_BLOCKED_WARNING };
  }
  if (!raw) return fallback;

  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { draft: emptySemanticDraft(), warning: SEMANTIC_STORAGE_READ_WARNING };
    }
    const source = parsed as Record<string, unknown>;
    const sourceDecisions = source.decisions && typeof source.decisions === 'object' && !Array.isArray(source.decisions)
      ? source.decisions as Record<string, unknown>
      : {};

    const decisions: Record<string, SemanticDecision> = {};
    for (const assertion of challenge.assertions) {
      const candidate = sourceDecisions[assertion.assertionId];
      if (isSemanticDecision(candidate) && assertion.allowedDecisions.includes(candidate)) {
        decisions[assertion.assertionId] = candidate;
      }
    }

    if (
      typeof source.supplement === 'string'
      && source.supplement.length > SEMANTIC_LIMITS.supplement
    ) {
      return { draft: emptySemanticDraft(), warning: SEMANTIC_STORAGE_READ_WARNING };
    }
    const supplement = typeof source.supplement === 'string' ? source.supplement : '';

    return { draft: { decisions, supplement }, warning: null };
  } catch {
    return { draft: emptySemanticDraft(), warning: SEMANTIC_STORAGE_READ_WARNING };
  }
}

export function saveSemanticDraft(
  storage: SemanticStorage | null,
  key: string,
  draft: SemanticDraft,
): boolean {
  if (!storage) return false;
  try {
    storage.setItem(key, JSON.stringify(draft));
    return true;
  } catch {
    return false;
  }
}

export function clearSemanticDraft(storage: SemanticStorage | null, key: string): boolean {
  if (!storage) return false;
  try {
    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

/**
 * Callback acceptance is deliberately strict: only a literal `true` means the
 * server accepted the submission. `undefined`, `false`, thrown errors and
 * truthy non-boolean values must all preserve the local draft.
 */
export function isSemanticCallbackAccepted(result: unknown): result is true {
  return result === true;
}

/**
 * Clear the draft only after an explicit `true` callback result. This keeps a
 * failed request, `false`, `undefined`, a redisplyed gate or a cancel from
 * silently discarding the user's choices.
 */
export function clearSemanticDraftIfAccepted(
  storage: SemanticStorage | null,
  key: string,
  result: unknown,
): boolean {
  if (!isSemanticCallbackAccepted(result)) return false;
  return clearSemanticDraft(storage, key);
}

/* -------------------------------------------------------------------------- */
/* Decision completeness and callback payloads                                */
/* -------------------------------------------------------------------------- */

export function semanticDecidedCount(
  challenge: SemanticChallenge,
  decisions: Record<string, SemanticDecision>,
): number {
  return challenge.assertions.filter((assertion) => {
    const decision = decisions[assertion.assertionId];
    return decision !== undefined && decision !== 'unknown' && assertion.allowedDecisions.includes(decision);
  }).length;
}

/**
 * `unknown` is a valid radio choice but is explicitly not a completed answer.
 */
export function isSemanticDecisionComplete(
  challenge: SemanticChallenge,
  decisions: Record<string, SemanticDecision>,
): boolean {
  return semanticDecidedCount(challenge, decisions) === challenge.assertions.length;
}

export interface SemanticDecisionSubmission {
  assertion_id: string;
  decision: SemanticDecision;
}

export interface SemanticConfirmation {
  challenge_id: string;
  approval_token: string;
  revision: number;
  decisions: SemanticDecisionSubmission[];
}

export interface SemanticSupplement {
  challenge_id: string;
  approval_token: string;
  revision: number;
  text: string;
}

/**
 * Builds the confirmation payload from server-provided IDs and the user's
 * choices only. Context, quotes and object labels are never echoed back as if
 * the user had edited them.
 */
export function buildSemanticConfirmation(
  challenge: SemanticChallenge,
  decisions: Record<string, SemanticDecision>,
): SemanticConfirmation | null {
  if (!isSemanticDecisionComplete(challenge, decisions)) return null;

  return {
    challenge_id: challenge.challengeId,
    approval_token: challenge.approvalToken,
    revision: challenge.revision,
    decisions: challenge.assertions.map((assertion) => ({
      assertion_id: assertion.assertionId,
      decision: decisions[assertion.assertionId],
    })),
  };
}

export function buildSemanticSupplement(
  challenge: SemanticChallenge,
  text: string,
): SemanticSupplement | null {
  const trimmed = text.trim();
  if (!trimmed || trimmed.length > SEMANTIC_LIMITS.supplement) return null;
  return {
    challenge_id: challenge.challengeId,
    approval_token: challenge.approvalToken,
    revision: challenge.revision,
    text: trimmed,
  };
}
