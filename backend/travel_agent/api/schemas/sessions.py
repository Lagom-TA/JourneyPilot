from __future__ import annotations

from enum import Enum
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from pydantic import BaseModel
from pydantic import Field


class SessionStatus(str, Enum):
    ACTIVE = "active"
    INTERRUPTED = "interrupted"


class ChatSessionSummary(BaseModel):
    session_id: str
    title: str
    status: SessionStatus
    mode: str
    last_message_preview: str = ""
    created_at: str
    updated_at: str


class ChatSessionDetail(BaseModel):
    """会话详情，只包含最新一页 turn；更早历史由 `/api/sessions/{id}/turns` 分页读取。"""

    session_id: str
    title: str
    status: SessionStatus
    mode: str
    last_message_preview: str = ""
    created_at: str
    updated_at: str
    messages: List[Dict[str, Any]]
    #: 再往回翻的游标；`None` 表示这一页已经到底。
    next_before: Optional[str] = None
    has_more: bool = False


class SessionTurn(BaseModel):
    turn_id: str
    cursor: str
    messages: List[Dict[str, Any]]


class SessionTurnPage(BaseModel):
    turns: List[SessionTurn]
    next_before: Optional[str] = None
    has_more: bool = False


class UpdateSessionRequest(BaseModel):
    """会话重命名请求体。空标题在前端即视作取消，不会到达此处。"""

    title: str = Field(min_length=1)
