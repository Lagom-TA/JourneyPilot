"""交付投影错误。"""

from __future__ import annotations


class DeliveryProjectionError(ValueError):
    """不可变的 v2 事实无法生成可信投影时抛出。"""
