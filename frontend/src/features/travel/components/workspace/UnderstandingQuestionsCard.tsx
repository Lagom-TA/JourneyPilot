import { Loader2, Send, Square } from 'lucide-react';
import { useApp } from '../../../../app/state/AppContext';
import { useSendMessage } from '../../../../app/session/useSendMessage';
import { useStopRun } from '../../../../app/session/useStopRun';
import { cn } from '../../../../lib/utils';
import React from 'react';
import type { UnderstandingQuestion } from '../../types/planner';

type AnswerDraft = { optionIds: string[]; freeText: string };

function answerText(question: UnderstandingQuestion, draft: AnswerDraft): string {
  const labels = draft.optionIds
    .map((id) => question.options.find((option) => option.id === id)?.label)
    .filter((label): label is string => Boolean(label));
  const free = draft.freeText.trim();
  return [labels.join('、'), free].filter(Boolean).join('；');
}

/**
 * 理解阶段的问答卡：模型在理解旅行想法时提出的问题在工作台内回答。
 * 选项只用于交互；提交时把所选含义与自由补充合并成完整文字。
 */
export const UnderstandingQuestionsCard: React.FC<{
  runId: string;
  revision: number;
  approvalToken: string;
  questions: UnderstandingQuestion[];
}> = ({ runId, revision, approvalToken, questions }) => {
  const { state } = useApp();
  const { sendMessage } = useSendMessage();
  const { stopRun } = useStopRun();
  const [drafts, setDrafts] = React.useState<Record<string, AnswerDraft>>({});
  const [submitting, setSubmitting] = React.useState(false);
  const formRef = React.useRef<HTMLFormElement>(null);

  const draftOf = (question: UnderstandingQuestion): AnswerDraft =>
    drafts[question.id] ?? { optionIds: [], freeText: '' };

  const allAnswered = questions.every((question) => answerText(question, draftOf(question)).trim().length > 0);

  const toggleOption = (question: UnderstandingQuestion, optionId: string) => {
    setDrafts((current) => {
      const draft = draftOf(question);
      let optionIds: string[];
      if (question.kind === 'multiple') {
        optionIds = draft.optionIds.includes(optionId)
          ? draft.optionIds.filter((id) => id !== optionId)
          : [...draft.optionIds, optionId];
      }
      else {
        optionIds = draft.optionIds.includes(optionId) ? [] : [optionId];
      }
      return { ...current, [question.id]: { ...draft, optionIds } };
    });
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!allAnswered || submitting || state.isStreaming) return;
    const answers = questions.map((question) => ({
      question_id: question.id,
      text: answerText(question, draftOf(question)),
    }));
    const displayText = answers
      .map((answer) => {
        const question = questions.find((item) => item.id === answer.question_id);
        return `${question?.question ?? answer.question_id}：${answer.text}`;
      })
      .join('\n');
    setSubmitting(true);
    try {
      await sendMessage(displayText, undefined, {
        resumeRunId: runId,
        route: 'trip_refinement',
        displayText: '已回答理解问题',
        gateDecision: { action: 'answer', answers, approval_token: approvalToken },
      });
    }
    finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      ref={formRef}
      className="understanding-questions-card"
      data-testid="understanding-questions-card"
      data-run={runId}
      data-revision={revision}
      onSubmit={(event) => void submit(event)}
    >
      <header className="understanding-questions-head">
        <h2>模型想先确认几件事</h2>
        <p>回答会直接进入你的旅行需求；也可以自由补充。</p>
      </header>
      <ol className="understanding-questions-list">
        {questions.map((question) => {
          const draft = draftOf(question);
          return (
            <li key={question.id} className="understanding-question" data-testid="understanding-question">
              <p className="understanding-question-text">{question.question}</p>
              {question.options.length > 0 && (
                <div className="understanding-question-options" role="group" aria-label={`回答方式：${question.question}`}>
                  {question.options.map((option) => {
                    const selected = draft.optionIds.includes(option.id);
                    return (
                      <button
                        key={option.id}
                        type="button"
                        className={cn('understanding-question-option', selected && 'is-selected')}
                        aria-pressed={selected}
                        onClick={() => toggleOption(question, option.id)}
                      >
                        {option.label}
                      </button>
                    );
                  })}
                </div>
              )}
              <textarea
                className="understanding-question-input"
                aria-label={`自由回答：${question.question}`}
                placeholder="或直接写下你的想法"
                rows={2}
                maxLength={2000}
                value={draft.freeText}
                onChange={(event) =>
                  setDrafts((current) => ({
                    ...current,
                    [question.id]: { ...draft, freeText: event.target.value },
                  }))
                }
              />
            </li>
          );
        })}
      </ol>
      <footer className="understanding-questions-actions">
        <button type="button" className="understanding-questions-cancel" onClick={() => void stopRun()} disabled={submitting}>
          <Square size={12} />取消规划
        </button>
        <button
          type="submit"
          className="understanding-questions-submit"
          data-testid="understanding-questions-submit"
          disabled={!allAnswered || submitting || state.isStreaming}
        >
          {submitting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          {submitting ? '正在提交' : '提交回答'}
        </button>
      </footer>
    </form>
  );
};
