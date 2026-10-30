import React from 'react';
import { AlertTriangle, PencilLine } from 'lucide-react';
import { Button } from '../../../../components/ui/Button';
import {
  SEMANTIC_DECISION_LABELS,
  SEMANTIC_LIMITS,
  SEMANTIC_SOURCE_LABELS,
  SEMANTIC_STORAGE_BLOCKED_WARNING,
  buildSemanticConfirmation,
  buildSemanticSupplement,
  clearSemanticDraftIfAccepted,
  isSemanticDecisionComplete,
  isSemanticCallbackAccepted,
  loadSemanticDraft,
  saveSemanticDraft,
  semanticDecidedCount,
  semanticDraftStorageKey,
  type SemanticChallenge,
  type SemanticConfirmation,
  type SemanticDecision,
  type SemanticExecutionValue,
  type SemanticRequirementExecution,
  type SemanticStorage,
  type SemanticSupplement,
} from '../../model/semanticChallenge';
import './SemanticRequirementGate.css';

export interface SemanticRequirementGateProps {
  /** A challenge returned by `normalizeSemanticChallenge`; never a raw payload. */
  challenge: SemanticChallenge;
  sessionId: string;
  runId: string;
  /** Resolve with literal `true` only when the server accepted the submission. */
  onConfirm: (confirmation: SemanticConfirmation) => boolean | Promise<boolean>;
  /** Resolve with literal `true` only when the server accepted the correction. */
  onSupplement?: (supplement: SemanticSupplement) => boolean | Promise<boolean>;
  onCancel?: () => void;
  busy?: boolean;
  error?: string | null;
}

const EXECUTION_LABELS = {
  requirementType: { intent: '旅行需求', constraint: '约束条件' },
  polarity: { include: '正向包含', exclude: '明确排除', neutral: '规则或口径' },
  strength: { hard: '必须满足', soft: '偏好', informational: '参考信息' },
} as const;

const VALUE_KEY_LABELS: Record<string, string> = {
  value_type: '值类型', value: '内容', categories: '类别', operator: '数量关系',
  count: '数量', unit: '计数范围', frequency: '频率', time_window: '时间窗口',
  required_attributes: '必需属性', window: '时间范围', applies_to: '适用对象',
  ordered_items: '顺序', area: '区域', relation: '区域关系', required_field: '输出字段',
  distinction: '方案差异', amount: '金额', currency: '币种', per: '预算口径',
  allergens: '过敏原', prefer: '偏好', required_facilities: '必需设施',
  max_continuous_walk_minutes: '连续步行上限（分钟）', avoid_long_stairs: '避免长楼梯',
  preferred_local_modes: '偏好的市内交通', excluded_local_modes: '排除的市内交通',
  locked_local_mode: '指定市内交通', avoid_overnight: '避免过夜',
  earliest_departure_local: '最早出发时间', latest_arrival_local: '最晚到达时间',
};

function ExecutionValueView({ value }: { value: SemanticExecutionValue }) {
  if (Array.isArray(value)) {
    return <ol className="semantic-execution-list">{value.map((item, index) => (
      <li key={index}><ExecutionValueView value={item} /></li>
    ))}</ol>;
  }
  if (value !== null && typeof value === 'object') {
    return <dl className="semantic-execution-fields">{Object.entries(value).map(([key, item]) => (
      <div key={key}>
        <dt>{VALUE_KEY_LABELS[key] || key}</dt>
        <dd><ExecutionValueView value={item} /></dd>
      </div>
    ))}</dl>;
  }
  if (value === null) return <span>未指定</span>;
  if (typeof value === 'boolean') return <span>{value ? '是' : '否'}</span>;
  return <span>{String(value)}</span>;
}

function ExecutionDetails({ execution }: { execution: SemanticRequirementExecution }) {
  return (
    <section className="semantic-execution" aria-label="将执行的完整理解">
      <h4>将执行的完整理解</h4>
      <p className="semantic-execution-summary">{execution.publicSummary}</p>
      <dl className="semantic-execution-fields">
        <div><dt>类型</dt><dd>{EXECUTION_LABELS.requirementType[execution.requirementType]}</dd></div>
        <div><dt>正向或排除</dt><dd>{EXECUTION_LABELS.polarity[execution.polarity]}</dd></div>
        <div><dt>强度</dt><dd>{EXECUTION_LABELS.strength[execution.strength]}</dd></div>
        <div><dt>需求种类</dt><dd>{execution.kind}</dd></div>
        <div><dt>作用领域</dt><dd>{execution.target}</dd></div>
        <div><dt>作用范围</dt><dd>{execution.scope}</dd></div>
        <div><dt>适用人</dt><dd>{execution.appliesTo.join('；')}</dd></div>
      </dl>
      <div className="semantic-execution-value">
        <h5>全部执行参数</h5>
        <ExecutionValueView value={execution.value} />
      </div>
    </section>
  );
}

function getSessionStorage(): SemanticStorage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export const SemanticRequirementGate: React.FC<SemanticRequirementGateProps> = ({
  challenge,
  sessionId,
  runId,
  onConfirm,
  onSupplement,
  onCancel,
  busy = false,
  error,
}) => {
  const idBase = React.useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const titleId = `semantic-gate-title-${idBase}`;
  const errorTitleId = `semantic-gate-error-${idBase}`;
  const correctionTitleId = `semantic-gate-correction-${idBase}`;
  const correctionFieldId = `semantic-gate-correction-field-${idBase}`;
  const storageKeyResult = React.useMemo(
    () => semanticDraftStorageKey(challenge, { sessionId, runId }),
    [challenge, runId, sessionId],
  );
  const storageKey = storageKeyResult.ok ? storageKeyResult.key : null;
  const storageKeyWarning = storageKeyResult.ok ? '' : storageKeyResult.warning;

  const [decisions, setDecisions] = React.useState<Record<string, SemanticDecision>>({});
  const [supplement, setSupplement] = React.useState('');
  const [loadedKey, setLoadedKey] = React.useState<string | null>(null);
  const [storageWarning, setStorageWarning] = React.useState('');
  const [localError, setLocalError] = React.useState('');
  const [status, setStatus] = React.useState('');
  const [submitting, setSubmitting] = React.useState<'confirm' | 'supplement' | null>(null);
  const errorHeadingRef = React.useRef<HTMLHeadingElement>(null);

  const controlsBusy = busy || submitting !== null;
  const decidedCount = semanticDecidedCount(challenge, decisions);
  const complete = isSemanticDecisionComplete(challenge, decisions);
  const displayError = (error || '').trim() || localError;

  React.useEffect(() => {
    if (!storageKey) {
      setDecisions({});
      setSupplement('');
      setStorageWarning(storageKeyWarning);
      setLoadedKey(null);
      setLocalError('');
      setStatus('');
      return;
    }
    const loaded = loadSemanticDraft(getSessionStorage(), storageKey, challenge);
    setDecisions(loaded.draft.decisions);
    setSupplement(loaded.draft.supplement);
    setStorageWarning(loaded.warning || '');
    setLoadedKey(storageKey);
    setLocalError('');
    setStatus('');
    // Only an exact session/run/challenge/version key change should rehydrate.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey, storageKeyWarning]);

  React.useEffect(() => {
    if (!storageKey || loadedKey !== storageKey) return;
    const saved = saveSemanticDraft(getSessionStorage(), storageKey, { decisions, supplement });
    if (!saved) {
      setStorageWarning((current) => current || SEMANTIC_STORAGE_BLOCKED_WARNING);
    }
  }, [decisions, loadedKey, storageKey, supplement]);

  React.useEffect(() => {
    if (displayError) errorHeadingRef.current?.focus();
  }, [displayError]);

  const choose = (assertionId: string, decision: SemanticDecision) => {
    if (controlsBusy) return;
    setLocalError('');
    setStatus('');
    setDecisions((current) => ({ ...current, [assertionId]: decision }));
  };

  const submitConfirmation = async () => {
    if (controlsBusy) return;
    const confirmation = buildSemanticConfirmation(challenge, decisions);
    if (!confirmation) {
      setLocalError('还有需求没有明确。请为每条选择“按此理解执行”“不采用此理解”或“仅历史背景”；“暂不确定”不算完成。');
      setStatus('');
      return;
    }

    setSubmitting('confirm');
    setLocalError('');
    setStatus('');
    try {
      const accepted = await onConfirm(confirmation);
      if (!isSemanticCallbackAccepted(accepted)) {
        setLocalError('服务端没有接受这次需求确认。未提交的选择和更正仍保留在本机，请重试或先更正。');
        setStatus('');
        return;
      }

      // Only a literal `true` clears the draft. A redisplayed gate, a cancel or
      // an unresolved/undefined callback must keep the user's choices.
      if (
        storageKey
        && !clearSemanticDraftIfAccepted(getSessionStorage(), storageKey, accepted)
      ) {
        setStorageWarning(SEMANTIC_STORAGE_BLOCKED_WARNING);
      }
      setStatus('这次需求确认已提交。');
    } catch {
      setLocalError('这次确认没有提交成功，未提交的选择和更正已暂存在本机，请重试。');
      setStatus('');
    } finally {
      setSubmitting(null);
    }
  };

  const submitSupplement = async () => {
    if (controlsBusy || !onSupplement) return;
    const payload = buildSemanticSupplement(challenge, supplement);
    if (!payload) {
      setLocalError('请先写下需要更正的内容，再单独提交。');
      setStatus('');
      return;
    }

    setSubmitting('supplement');
    setLocalError('');
    setStatus('');
    try {
      const accepted = await onSupplement(payload);
      if (!isSemanticCallbackAccepted(accepted)) {
        setLocalError('服务端没有确认收到更正说明。已输入的内容仍保留在本机，请重试。');
        setStatus('');
        return;
      }
      setStatus('更正说明已提交。请按更新后的理解重新选择，更正说明本身不代表确认。');
    } catch {
      setLocalError('更正说明没有提交成功，已输入的内容仍保留在本机，请重试。');
      setStatus('');
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <section className="semantic-gate" aria-labelledby={titleId} data-testid="semantic-requirement-gate">
      <header className="semantic-gate-header">
        <p className="semantic-gate-eyebrow">需求理解确认</p>
        <h2 id={titleId} tabIndex={-1}>请逐条确认我们对需求的理解</h2>
        <p>
          下面的来源文字和识别对象都来自服务器提供的本次会话。每条都要单独选择。
          选择“暂不确定”的项目仍未完成，需要先更正或重新选择。
        </p>
      </header>

      <p className="semantic-gate-progress" role="status" aria-live="polite">
        已明确 {decidedCount} / {challenge.assertions.length} 条
      </p>

      {storageWarning && (
        <p className="semantic-gate-storage-warning" role="status">
          <AlertTriangle size={16} aria-hidden="true" />
          <span>{storageWarning}</span>
        </p>
      )}

      {displayError && (
        <div className="semantic-gate-error" role="alert">
          <h3 id={errorTitleId} ref={errorHeadingRef} tabIndex={-1}>提交未完成</h3>
          <p>{displayError}</p>
        </div>
      )}

      <ol className="semantic-gate-list">
        {challenge.assertions.map((assertion, index) => {
          const itemTitleId = `semantic-gate-object-${idBase}-${index}`;
          const unknownHintId = `semantic-gate-unknown-${idBase}-${index}`;
          const groupName = `semantic-gate-radio-${idBase}-${index}`;
          const allowsUnknown = assertion.allowedDecisions.includes('unknown');

          return (
            <li key={assertion.assertionId} className="semantic-gate-item">
              <article className="semantic-gate-card" aria-labelledby={itemTitleId}>
                <header className="semantic-gate-card-header">
                  <span className="semantic-gate-source">{SEMANTIC_SOURCE_LABELS[assertion.sourceKind]}</span>
                  <span className="semantic-gate-domain">{assertion.domainLabel}</span>
                </header>

                <h3 id={itemTitleId} className="semantic-gate-object">{assertion.objectLabel}</h3>

                <div className="semantic-gate-context-block">
                  <h4>来源上下文</h4>
                  <p className="semantic-gate-context">{assertion.context}</p>
                </div>

                {assertion.questionContext && (
                  <div className="semantic-gate-question-block">
                    <h4>模型问题原文</h4>
                    <p className="semantic-gate-question-context">{assertion.questionContext}</p>
                    <p className="semantic-gate-question-note">
                      仅用于展示问题背景，不作为本条需求的原文依据。
                    </p>
                  </div>
                )}

                <div className="semantic-gate-quote-block">
                  <h4>对应原文</h4>
                  <blockquote className="semantic-gate-quote">“{assertion.quote}”</blockquote>
                </div>

                <ExecutionDetails execution={assertion.execution} />

                <fieldset
                  className="semantic-gate-fieldset"
                  aria-describedby={allowsUnknown ? unknownHintId : undefined}
                >
                  <legend>对“{assertion.objectLabel}”这条完整理解的处理</legend>
                  <div className="semantic-gate-options">
                    {assertion.allowedDecisions.map((decision) => {
                      const optionId = `semantic-gate-radio-${idBase}-${index}-${decision}`;
                      return (
                        <label className="semantic-gate-option" htmlFor={optionId} key={decision}>
                          <input
                            id={optionId}
                            type="radio"
                            name={groupName}
                            value={decision}
                            checked={decisions[assertion.assertionId] === decision}
                            disabled={controlsBusy}
                            onChange={() => choose(assertion.assertionId, decision)}
                          />
                          <span>{SEMANTIC_DECISION_LABELS[decision]}</span>
                        </label>
                      );
                    })}
                  </div>
                  {allowsUnknown && (
                    <p id={unknownHintId} className="semantic-gate-unknown-hint">
                      “暂不确定”表示这条理解尚未完成，不能作为确认提交。
                    </p>
                  )}
                </fieldset>
              </article>
            </li>
          );
        })}
      </ol>

      <section className="semantic-gate-correction" aria-labelledby={correctionTitleId}>
        <h3 id={correctionTitleId}>要更正哪条理解？</h3>
        <p>这里仅用于补充更正说明；提交说明不会替代上面的逐条选择，也不会自动确认任何需求。</p>
        <label htmlFor={correctionFieldId}>更正说明</label>
        <textarea
          id={correctionFieldId}
          value={supplement}
          onChange={(event) => {
            setSupplement(event.target.value);
            setStatus('');
          }}
          disabled={controlsBusy}
          rows={3}
          maxLength={SEMANTIC_LIMITS.supplement}
          placeholder="例如：这里的“不要博物馆”仅指室内展馆，开放街区里的展陈仍可以安排。"
        />
        <div className="semantic-gate-correction-actions">
          <Button
            type="button"
            variant="secondary"
            onClick={() => void submitSupplement()}
            disabled={controlsBusy || !onSupplement || !supplement.trim()}
            loading={submitting === 'supplement'}
          >
            <PencilLine size={15} aria-hidden="true" />
            提交更正说明
          </Button>
        </div>
      </section>

      {status && <p className="semantic-gate-status" role="status" aria-live="polite">{status}</p>}

      <footer className="semantic-gate-actions">
        <p>
          {complete
            ? '每条需求都已明确，可以提交这次需求确认。'
            : '请为每条需求选择“按此理解执行”“不采用此理解”或“仅历史背景”；“暂不确定”不算完成。'}
        </p>
        <div className="semantic-gate-action-buttons">
          {onCancel && (
            <Button type="button" variant="ghost" onClick={onCancel} disabled={controlsBusy}>
              返回修改需求
            </Button>
          )}
          <Button
            type="button"
            onClick={() => void submitConfirmation()}
            disabled={controlsBusy || !complete}
            loading={submitting === 'confirm'}
          >
            提交需求确认
          </Button>
        </div>
      </footer>
    </section>
  );
};
