import type { UnderstandingAnswer, UnderstandingQuestion } from '../types/planner';

export function formatUnderstandingAnswers(
  questions: readonly UnderstandingQuestion[],
  answers: readonly UnderstandingAnswer[],
): string {
  return answers.map((answer) => {
    const question = questions.find((item) => item.id === answer.question_id);
    return `助手提问：${question?.question ?? answer.question_id}\n旅行者回答：${answer.text}`;
  }).join('\n\n');
}
