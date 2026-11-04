"""理解阶段的提问门：暂停等待用户回答后继续理解。"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict

from langgraph.types import interrupt

from travel_agent.planning.nodes import NODE_UNDERSTANDING_GATE
from travel_agent.planning.requirements.understanding.contracts import (
    bind_understanding_answers,
    validate_understanding_questions,
)
from travel_agent.runtime.cancellation import RunCancelled


def _build_understanding_gate_payload(state: Any) -> Dict[str, Any]:
    questions = (
        validate_understanding_questions(state.understanding_pending_questions)
        if state.understanding_pending_questions else []
    )
    payload: Dict[str, Any] = {
        "gate": "understanding",
        "revision": int(state.understanding_rounds or 0),
        "questions": [item.model_dump(mode="json") for item in questions],
        "decision_options": ["answer", "cancel"] if questions else ["retry", "cancel"],
    }
    material = {
        "run_id": state.run_id,
        "revision": payload["revision"],
        "questions": payload["questions"],
        "decision_options": payload["decision_options"],
    }
    digest = hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(":", ":")).encode()
    ).hexdigest()
    payload["approval_token"] = f"understanding_gate.approval:{digest}"
    return payload


async def understanding_gate_node(state: Any) -> Dict[str, Any]:
    payload = _build_understanding_gate_payload(state)
    questions = {
        item.id: item for item in validate_understanding_questions(payload["questions"])
    } if payload["questions"] else {}
    while True:
        decision = interrupt(payload)
        if not isinstance(decision, dict):
            continue
        action = str(decision.get("action") or "").lower()
        if action == "cancel":
            raise RunCancelled(state.run_id, NODE_UNDERSTANDING_GATE)
        if action not in payload["decision_options"]:
            continue
        supplied = str(decision.get("approval_token") or "")
        try:
            valid = bool(supplied) and hmac.compare_digest(
                supplied.encode(), str(payload["approval_token"]).encode()
            )
        except UnicodeEncodeError:
            valid = False
        if not valid:
            continue
        if action == "retry":
            return {
                "understanding_messages": [
                    *(state.understanding_messages or []),
                    {"role": "user", "content": "请重新查询尚未核实的地点，保留已知旅行信息。"},
                ],
                "understanding_pending_questions": None,
            }
        try:
            answers = bind_understanding_answers(list(questions.values()), decision.get("answers"))
        except ValueError:
            continue
        qa_rows = []
        answer_lines = []
        for answer in answers:
            question = questions[answer.question_id]
            qa_rows.append(
                {
                    "question_id": question.id,
                    "question": question.question,
                    "answer": answer.text.strip(),
                }
            )
            answer_lines.append(f"问：{question.question}\n答：{answer.text.strip()}")
        return {
            "understanding_qa": [
                *(state.understanding_qa or []),
                *qa_rows,
            ],
            "understanding_messages": [
                *(state.understanding_messages or []),
                {"role": "user", "content": "用户回答：\n" + "\n".join(answer_lines)},
            ],
            "understanding_pending_questions": None,
        }
