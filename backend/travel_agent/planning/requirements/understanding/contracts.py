"""理解阶段的问题与回答契约。"""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field


# 一轮最多提出的问题数与每题选项数是失控保护，不是出题目标；
# 提示词要求模型只问确实影响方案的问题。
MAX_UNDERSTANDING_QUESTIONS_PER_ROUND = 4
MAX_UNDERSTANDING_OPTIONS_PER_QUESTION = 6
MAX_UNDERSTANDING_ANSWER_CHARS = 2000


class UnderstandingQuestionOption(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)


class UnderstandingQuestion(BaseModel):
    """模型向用户提出的一个问题；选项只是交互便利，回答含义以文字为准。"""

    model_config = {"extra": "ignore"}

    id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=500)
    kind: Literal["single", "multiple", "date_range"] = "single"
    options: List[UnderstandingQuestionOption] = Field(default_factory=list)


def validate_understanding_questions(raw: object) -> List[UnderstandingQuestion]:
    """把模型输出的问题列表整理成契约问题；形状不合法直接拒绝。"""

    if not isinstance(raw, list) or not raw:
        raise ValueError("questions 必须是非空数组")
    if len(raw) > MAX_UNDERSTANDING_QUESTIONS_PER_ROUND:
        raise ValueError("单轮问题过多")
    questions: List[UnderstandingQuestion] = []
    seen_ids: set[str] = set()
    for item in raw:
        question = UnderstandingQuestion.model_validate(item)
        if question.id in seen_ids:
            raise ValueError(f"问题标识重复: {question.id}")
        seen_ids.add(question.id)
        if len(question.options) > MAX_UNDERSTANDING_OPTIONS_PER_QUESTION:
            raise ValueError(f"问题 {question.id} 选项过多")
        questions.append(question)
    return questions


class UnderstandingAnswer(BaseModel):
    """用户对单个问题的回答；text 是完整含义，选项标签由前端并入文字。"""

    model_config = {"extra": "forbid"}

    question_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=MAX_UNDERSTANDING_ANSWER_CHARS)


def bind_understanding_answers(
    questions: List[UnderstandingQuestion], raw_answers: object
) -> List[UnderstandingAnswer]:
    """把提交的回答绑定到当前待答问题；缺答、错引或空文本都拒绝。"""

    if not isinstance(raw_answers, list):
        raise ValueError("answers 必须是数组")
    expected_ids = {question.id for question in questions}
    answers: List[UnderstandingAnswer] = []
    seen: set[str] = set()
    for item in raw_answers:
        answer = UnderstandingAnswer.model_validate(item)
        if answer.question_id not in expected_ids:
            raise ValueError(f"回答引用了不存在的问题: {answer.question_id}")
        if answer.question_id in seen:
            raise ValueError(f"问题 {answer.question_id} 有重复回答")
        if not answer.text.strip():
            raise ValueError("回答不能为空")
        seen.add(answer.question_id)
        answers.append(answer)
    if seen != expected_ids:
        missing = sorted(expected_ids - seen)
        raise ValueError(f"尚有未回答的问题: {', '.join(missing)}")
    return answers
