from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class MemoryDeleteOptions(BaseModel):
    """删一条 / 删一类记忆时的开关。

    ``extra="forbid"`` 与下面那个是同一道锁，理由见 ``MemoryDeleteAllOptions``。
    """

    model_config = ConfigDict(extra="forbid")

    request_id: Optional[str] = None
    reason: str = ""
    clear_auto_portrait: bool = False
    clear_graph: bool = False
    clear_session_anchors: bool = False


class MemoryDeleteAllOptions(BaseModel):
    """「删除全部记忆」的开关。

    这里的 ``clear_auto_portrait`` 只管系统自己总结出来的那段画像
    （``UserProfile.auto_portrait``）。
    用户手填的六组偏好与常用出发地不在任何一次记忆删除的范围里。

    **``extra="forbid"`` 是这里配套的锁，不是洁癖。** 三个开关的默认值都是 ``True``：
    不禁多余键的话，过期客户端发来的旧字段会被静默丢掉，然后三个默认 True
    生效 —— 一次本该 422 的过期请求变成一次静默全清。那样硬断裂就退化成了兼容层。
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
    # 'created' = 这次真写了一条；'existing' = 同一句话本来就在，没有重复写入。
    # 界面靠这个字眼解释「点了添加但列表没变长」。
    status: str
    # **必填**：一次成功的添加必然对着一条真事实；它可空时，「回读把异常吞成
    # 空列表」会变成一个 `status="completed"` 而 `fact=None` 的回执。
    fact: MemoryFactItem
