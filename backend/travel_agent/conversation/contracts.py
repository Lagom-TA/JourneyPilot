"""会话消息契约。"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel


class TaskType(str, Enum):
    """任务类型标记（由 Planner 设置）"""

    QUICK_QA = "quick_qa"
    TRAVEL_PLANNING = "travel_planning"
    DESTINATION_INFO = "destination_info"
    TRANSPORT_QUERY = "transport_query"
    ACCOMMODATION_QUERY = "accommodation_query"


class MessageItem(BaseModel):
    """单条对话消息"""

    role: str
    content: str
    message_id: str = ""
    type: str = "normal"
    step_name: str = ""
    agent_name: str = ""
