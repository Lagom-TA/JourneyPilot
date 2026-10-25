from __future__ import annotations

__all__ = ["content_length", "is_blank"]


def content_length(text: str) -> int:
    # split() 也排除内部空白和全角空格；strip() 只能去掉首尾空白。
    return len("".join(text.split()))


def is_blank(text: str) -> bool:
    return content_length(text) == 0
