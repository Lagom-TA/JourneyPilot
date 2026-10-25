from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Literal
from typing import Optional
from pydantic import BaseModel
from pydantic import Field


class TripRunControlRequest(BaseModel):
    action: Literal["cancel"]
    session_id: Optional[str] = None


class TripRunControlResponse(BaseModel):
    """取消回执。`status` 是命令的状态，`run_status` 是运行的状态 —— 两件事。

    命令已经落库，所以断线之后可以拿 `command_id` 去查结果，不必猜。
    """

    run_id: str
    action: str
    command_id: str
    accepted: bool
    status: str
    run_status: str
    message: str


class TripRunSupplementRequest(BaseModel):
    category: Literal["food", "transport", "accommodation", "pace", "must_do", "other"]
    content: str = Field(min_length=1, max_length=2000)
    session_id: Optional[str] = None


class TripRunSupplementResponse(BaseModel):
    run_id: str
    command_id: str
    accepted: bool
    status: str
    category: str
    message: str
    impact_scope: List[str] = Field(default_factory=list)


class TripRunCommandResponse(BaseModel):
    """一条控制命令此刻的结论。断线重连后查这里，而不是重发命令。"""

    command_id: str
    run_id: str
    command_type: str
    status: str
    run_status: str
    error_code: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    created_at: str
    updated_at: str
    consumed_at: Optional[str] = None
