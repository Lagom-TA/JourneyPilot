from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class MemoryDeleteOptions(BaseModel):
    """删除单条或某类记忆时的开关。

    ``extra="forbid"`` 配置与 ``MemoryDeleteAllOptions`` 一致。
    """

    model_config = ConfigDict(extra="forbid")

    request_id: Optional[str] = None
    reason: str = ""
    clear_auto_portrait: bool = False
    clear_graph: bool = False
    clear_session_anchors: bool = False


class MemoryDeleteAllOptions(BaseModel):
    """「删除全部记忆」的开关。

    ``clear_auto_portrait`` 仅控制系统生成的画像（``UserProfile.auto_portrait``）；
    用户手填的六组偏好与常用出发地不在任何一次记忆删除范围内。

    ``extra="forbid"`` 是必要配置：三个开关默认值均为 True，若允许多余键，
    过期客户端发来的旧字段会被静默忽略并启用默认值，使本应返回 422 的请求
    执行一次全量删除。
    """

    model_config = ConfigDict(extra="forbid")

    request_id: Optional[str] = None
    reason: str = ""
    clear_auto_portrait: bool = True
    clear_graph: bool = True
    clear_session_anchors: bool = True


class MemoryRetentionCleanupRequest(BaseModel):
    request_id: Optional[str] = None
    reason: str = "retention_cleanup"
    limit: int = 1000


class MemoryDeletionResponse(BaseModel):
    request_id: str
    scope: str
    category: Optional[str] = None
    fact_id: Optional[str] = None
    status: str
    affected_facts: int = 0
    affected_entities: int = 0
    affected_relations: int = 0
    affected_profiles: int = 0
    affected_session_anchors: int = 0
    boundary: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class MemoryForgettingAuditResponse(MemoryDeletionResponse):
    pass


class MemoryForgettingAuditListResponse(BaseModel):
    audits: List[MemoryForgettingAuditResponse] = Field(default_factory=list)
    total: int = 0


class MemoryFactItem(BaseModel):
    fact_id: str
    content: str
    category: Optional[str] = None
    importance: int = 5
    # 'manual' = 用户手动添加，'auto' = 系统自动抽取
    source: str = "auto"
    created_at: str = ""
    expires_at: str = ""


class MemoryFactListResponse(BaseModel):
    facts: List[MemoryFactItem] = Field(default_factory=list)
    total: int = 0


class AddMemoryFactRequest(BaseModel):
    content: str
    category: Optional[str] = None


class AddMemoryFactResponse(BaseModel):
    # 'created' = 本次写入；'existing' = 同一句话已存在，未重复写入。
    # 界面据此解释添加后列表未变长的情况。
    status: str
    # 必填：成功响应必须包含一条事实；若允许为空，回读异常会被表示成
    # status="completed" 且 fact=None 的回执。
    fact: MemoryFactItem
