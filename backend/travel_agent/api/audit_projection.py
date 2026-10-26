"""检视与诊断数据的脱敏投影。

产品接口按 Bundle 模型构造载荷，检视接口则承载节点生命周期、运行状态摘要、
工具审计元数据等开放结构，字段分散在多个调用点且随流程变化。此处没有可用的
构造模型，因此按字段名剔除原始数据：未识别的诊断字段更可能是新增的原始 I/O
而非新产品字段，丢弃它是安全的。

允许保留：供应商/缓存/缺口分类、截止控制、哈希、归一化原因码、计数。
不得透出：prompt、消息正文、工具参数与结果、供应商快照、HTTP 请求/响应体、
供应商错误文本。
"""

from __future__ import annotations

from typing import Any, Mapping


_AUDIT_RAW_KEYS = frozenset(
    {
        "arguments",
        "argument",
        "args",
        "body",
        "content",
        "context",
        "detail",
        "error",
        "error_message",
        "headers",
        "input",
        "input_summary",
        "last_error",
        "message",
        "messages",
        "metadata",
        "output",
        "output_summary",
        "payload",
        "prompt",
        "prompts",
        "query",
        "request",
        "response",
        "summary",
        "tool_args",
        "tool_args_summary",
        "tool_calls",
        "tool_result",
        "tool_result_summary",
        "args_summary",
    }
)


def _audit_key_is_raw(key: str) -> bool:
    """判断诊断数据字段名是否可能承载用户或模型的原始内容。"""

    normalized = key.lower()
    if normalized in _AUDIT_RAW_KEYS:
        return True
    if normalized.startswith("raw_"):
        return True
    return (
        normalized.endswith(("_payload", "_body", "_headers"))
        or "prompt" in normalized
        or "message_content" in normalized
        or "request_body" in normalized
        or "response_body" in normalized
    )


def audit_safe_value(value: Any) -> Any:
    """将检视/诊断数据投影为标签与计数，剔除原始 I/O 与文本。"""

    if isinstance(value, Mapping):
        return {
            str(key): audit_safe_value(item)
            for key, item in value.items()
            if not _audit_key_is_raw(str(key))
        }
    if isinstance(value, (list, tuple, set)):
        return [audit_safe_value(item) for item in value]
    return value
