import { describe, expect, it } from 'vitest';
import type { UnderstandingQuestion } from '../types/planner';
import { formatUnderstandingAnswers } from './understandingAnswers';

const questions: UnderstandingQuestion[] = [
  { id: 'party', question: '这次是否有儿童同行？', kind: 'single', options: [] },
  { id: 'pace', question: '希望行程节奏如何？', kind: 'single', options: [] },
];

describe('理解问答消息', () => {
  it('一起保留问题和否定回答，并区分双方', () => {
    expect(formatUnderstandingAnswers(questions, [{ question_id: 'party', text: '没有儿童' }]))
      .toBe('助手提问：这次是否有儿童同行？\n旅行者回答：没有儿童');
  });

  it('按回答顺序保留多组问答', () => {
    expect(formatUnderstandingAnswers(questions, [
      { question_id: 'pace', text: '慢一些' },
      { question_id: 'party', text: '两位成人' },
    ])).toBe('助手提问：希望行程节奏如何？\n旅行者回答：慢一些\n\n助手提问：这次是否有儿童同行？\n旅行者回答：两位成人');
  });
});
