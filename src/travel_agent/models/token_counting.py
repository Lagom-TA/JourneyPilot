"""One offline estimator for context sizing and missing-usage diagnostics.

Reported API usage remains the billing authority. A local text tokenizer does
not account exactly for chat framing, images, or a model's private vocabulary.
Never download a tokenizer during a request or claim this estimate is usage.
"""

from __future__ import annotations

import json
import math
import unicodedata
from typing import Any


def estimate_tokens(text: str, model_name: str = "") -> int:
    if not text:
        return 0
    # Reuse only an already loaded tokenizer. get_encoding() can fetch assets.
    try:
        import tiktoken
        from tiktoken.registry import ENCODINGS

        name = tiktoken.model.encoding_name_for_model(model_name.rsplit("/", 1)[-1])
        encoding = ENCODINGS.get(name)
        if encoding is not None:
            return len(encoding.encode(text, disallowed_special=()))
    except (ImportError, KeyError):
        pass
    # Chinese characters and emoji must not receive the ASCII len/4 discount.
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
    """Include tool calls, call ids, replay data, roles and structured content."""
    return estimate_json_tokens(message, model_name)


def estimate_request_tokens(payload: dict[str, Any], model_name: str = "") -> tuple[int, int]:
    visible = {key: payload[key] for key in (
        "messages", "input", "instructions", "tools", "response_format", "text"
    ) if key in payload}
    tools = payload.get("tools")
    return estimate_json_tokens(visible, model_name), (
        estimate_json_tokens(tools, model_name) if tools else 0
    )
