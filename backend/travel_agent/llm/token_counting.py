"""上下文估算与 usage 缺失诊断共用的离线估算器。

计费以 API 返回的 usage 为准。本地 tokenizer 无法精确计算聊天框架、图片或模型私有
词表；请求过程中不下载 tokenizer，估算结果不得当作 usage。
"""

from __future__ import annotations

import json
import math
import unicodedata
from typing import Any


def estimate_tokens(text: str, model_name: str = "") -> int:
    if not text:
        return 0
    # 只复用已加载的 tokenizer；get_encoding() 可能在运行时下载资源。
    try:
        import tiktoken
        from tiktoken.registry import ENCODINGS

        name = tiktoken.model.encoding_name_for_model(model_name.rsplit("/", 1)[-1])
        encoding = ENCODINGS.get(name)
        if encoding is not None:
            return len(encoding.encode(text, disallowed_special=()))
    except (ImportError, KeyError):
        pass
    # 中文字符与 emoji 不按 ASCII 的 len/4 比例估算。
    ascii_chars = sum(ord(char) < 128 for char in text)
    non_ascii = sum(
        2 if unicodedata.category(char) == "So" else 1
        for char in text if ord(char) >= 128
    )
    return math.ceil(ascii_chars / 4) + non_ascii


def estimate_json_tokens(value: Any, model_name: str = "") -> int:
    return estimate_tokens(json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                                      default=str), model_name)


def estimate_message_tokens(message: dict[str, Any], model_name: str = "") -> int:
    """估算消息 token，包含工具调用、调用 id、重放数据、角色与结构化内容。"""
    return estimate_json_tokens(message, model_name)


def estimate_request_tokens(payload: dict[str, Any], model_name: str = "") -> tuple[int, int]:
    visible = {key: payload[key] for key in (
        "messages", "input", "instructions", "tools", "response_format", "text"
    ) if key in payload}
    tools = payload.get("tools")
    return estimate_json_tokens(visible, model_name), (
        estimate_json_tokens(tools, model_name) if tools else 0
    )
