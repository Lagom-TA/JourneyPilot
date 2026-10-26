"""地名处理。"""

from __future__ import annotations

from typing import Mapping
from typing import Optional


CONTROLLED_DESTINATION_ANCHOR_PREFIX = "controlled_trip_identity.destinations."


def controlled_public_place_name(value: Mapping) -> Optional[str]:
    """返回受控身份 anchor 值中携带的公开地名。

    没有可用名称时返回 ``None``，由调用方决定是否可以接受：组合阶段会退回用
    Day 自身的地点命名，投影阶段则拒绝发布。
    """

    name = str(value.get("name") or "").strip()
    return name or None
