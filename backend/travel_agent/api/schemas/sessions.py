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
    # 只读历史值：clarify 产品面已删除，没有任何代码再写入这个状态。它留在枚举里是因为
    # chat_sessions 表里仍有历史行带着它——删掉成员会让那些会话在读取时校验失败，比现状
    # （一个永远停在此状态的死会话）更糟。清库不覆盖聊天历史，所以这一条不会自然消失。
    AWAITING_CLARIFY = "awaiting_clarify"
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
    """会话详情 = **最新一页 turn**。更早的历史由 `/api/sessions/{id}/turns` 往回取。"""

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
