from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Tuple

from .governance import PROVIDER_RESULT_OUTCOME_EMPTY_SUCCESS


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


class ToolResultOutcome(str, Enum):
    "工具单次调用的三态结果。"

    FAILED = "failed"
    EMPTY_SUCCESS = PROVIDER_RESULT_OUTCOME_EMPTY_SUCCESS
    CONTENT = "content"


def classify_tool_result(tool_name: str, result: Any) -> Tuple[ToolResultOutcome, str]:
    "把一次工具返回归类为三态，并给出一句可直接进日志的原因。"
    if not isinstance(result, dict) or not result:
        return ToolResultOutcome.FAILED, f"{tool_name} 未返回结构化结果"
    if result.get("type") == "user_input_required":
        return ToolResultOutcome.CONTENT, ""
    if not result.get("success", True):
        return ToolResultOutcome.FAILED, str(
            result.get("error") or f"{tool_name} 报告失败"
        )
    payload = (
        result.get("content")
        or result.get("result")
        or result.get("results")
        or result.get("routes")
        or result.get("data")
        or result.get("text")
    )
    if _contains_tool_error_text(payload):
        return ToolResultOutcome.FAILED, f"{tool_name} 在成功标记下返回错误文本"
    if not payload:
        return (
            ToolResultOutcome.EMPTY_SUCCESS,
            f"{tool_name} 成功应答但结果集为空（keys={sorted(result.keys())}）",
        )
    return ToolResultOutcome.CONTENT, ""


def _contains_tool_error_text(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        return lowered.startswith(
            ("搜索出错", "search error", "error:", "duckduckgo search failed")
        )
    if isinstance(value, dict):
        return any(_contains_tool_error_text(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_tool_error_text(v) for v in value)
    return False
