"""会话消息契约。"""

from __future__ import annotations

from enum import Enum


class TaskType(str, Enum):
    """任务类型标记（由 Planner 设置）"""

    TRAVEL_PLANNING = "travel_planning"
