from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReactOutcome(str, Enum):
    FINAL_ANSWER = "final_answer"
    AWAITING_USER = "awaiting_user"
    ITERATION_LIMIT = "iteration_limit"
    BUDGET_LIMIT = "budget_limit"
    MODEL_FAILED = "model_failed"
    INCOMPLETE_STREAM = "incomplete_stream"


@dataclass(frozen=True)
class ReactResult:
    outcome: ReactOutcome
    content: str = ""
    summaries: list[str] = field(default_factory=list)
    pending_choice: dict[str, Any] | None = None
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def require_final_answer(self) -> str:
        if self.outcome is not ReactOutcome.FINAL_ANSWER or not self.content.strip():
            raise RuntimeError(f"ReAct {self.outcome.value}: {self.error or 'no final answer'}")
        return self.content
