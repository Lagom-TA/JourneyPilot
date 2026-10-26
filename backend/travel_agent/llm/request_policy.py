"""请求构造与任务输出预算共用的模型名规则。"""

from __future__ import annotations


def canonical_model_name(model_name: str) -> str:
    """去除模型名中的目录前缀，不依赖 API 端点。"""
    return model_name.strip().lower().rsplit("/", 1)[-1]


def is_openai_reasoning_model(model_name: str) -> bool:
    name = canonical_model_name(model_name)
    return name.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))


def model_reasoning_effort(model_name: str, effort: str) -> str:
    """DeepSeek V4 固定使用 low effort：其 medium 别名等价于 high effort。"""
    if effort not in {"low", "medium"}:
        raise ValueError("reasoning_effort must be low or medium")
    name = canonical_model_name(model_name)
    if name.startswith(("deepseek-v4", "deepseek-flash")):
        return "low"
    return effort
