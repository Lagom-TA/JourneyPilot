"""运行控制命令的类型、状态与摘要规则。"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel
from pydantic import Field
from travel_agent.runtime.time import utc_now_iso
from typing import Any
from typing import Dict
from typing import Mapping
from typing import Optional
import hashlib
import json
import uuid


def generate_run_command_id() -> str:
    return f"cmd_{uuid.uuid4().hex[:16]}"


class RunCommandType(str, Enum):
    """可以对一个运行中 Run 下达的动作。

    只有产品面已经存在的两个。`pause` 之类没有入口的动作不提前实现 —— 一个没有消费者
    的命令类型只会让状态机多一条永远 pending 的分支。
    """

    CANCEL = "cancel"
    SUPPLEMENT = "supplement"


class RunCommandStatus(str, Enum):
    PENDING = "pending"

    CLAIMED = "claimed"
    CONSUMED = "consumed"

    REJECTED = "rejected"


OPEN_RUN_COMMAND_STATUSES: set[RunCommandStatus] = {
    RunCommandStatus.PENDING,
    RunCommandStatus.CLAIMED,
}


class RunCommand(BaseModel):
    """一条持久化的运行控制命令。**最终事实在 `trip_run_commands`**。

    进程内 registry 只负责唤醒执行器去读这张表，不再是命令存不存在的判据。
    """

    command_id: str
    run_id: str
    command_type: RunCommandType
    payload: Dict[str, Any] = Field(default_factory=dict)
    request_digest: str
    status: RunCommandStatus = RunCommandStatus.PENDING
    claimed_by: Optional[str] = None
    claimed_at: Optional[str] = None
    consumed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_RUN_COMMAND_STATUSES


def coerce_run_command_type(value: str | RunCommandType) -> RunCommandType:
    return value if isinstance(value, RunCommandType) else RunCommandType(str(value))


def coerce_run_command_status(value: str | RunCommandStatus) -> RunCommandStatus:
    return (
        value if isinstance(value, RunCommandStatus) else RunCommandStatus(str(value))
    )


def run_command_digest(
    command_type: str | RunCommandType,
    payload: Mapping[str, Any],
) -> str:
    """同一个意图的重复请求必须落在同一行上。

    `cancel` 的摘要只取类型：「停下这个 Run」是一个意图，点两次不是两件事，重发只该
    拿回同一张回执。`supplement` 的摘要取类别与正文：同一句要求说两遍仍然是一条要求，
    而一次重试的 POST 不该在调研提示里出现两遍。
    """

    kind = coerce_run_command_type(command_type)
    if kind is RunCommandType.CANCEL:
        material = kind.value
    else:
        material = json.dumps(
            {
                "type": kind.value,
                "category": str(payload.get("category") or ""),
                "content": str(payload.get("content") or ""),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
