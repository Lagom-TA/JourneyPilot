"""Model-name rules shared by request construction and task output budgets."""

from __future__ import annotations


def canonical_model_name(model_name: str) -> str:
    """Remove a catalog namespace without depending on the API endpoint."""
    return model_name.strip().lower().rsplit("/", 1)[-1]


def is_openai_reasoning_model(model_name: str) -> bool:
    name = canonical_model_name(model_name)
    return name.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))


def model_reasoning_effort(model_name: str, effort: str) -> str:
    """Keep DeepSeek V4 in low effort: its medium alias means high effort."""
    if effort not in {"low", "medium"}:
        raise ValueError("reasoning_effort must be low or medium")
    name = canonical_model_name(model_name)
    if name.startswith(("deepseek-v4", "deepseek-flash")):
        return "low"
    return effort
