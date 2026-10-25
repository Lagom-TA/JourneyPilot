from __future__ import annotations

from typing import List
from typing import Literal
from typing import Optional
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity
from travel_agent.conversation.intake_contracts import GuidedIntakeState
from travel_agent.conversation.intake_contracts import RouteDecision
from travel_agent.conversation.intake_contracts import RouteName


class ChatMessage(BaseModel):
    role: str
    content: str
    message_id: Optional[str] = None
    type: str = "normal"


class GateDecision(BaseModel):
    # plan_gate：approve / edit / supplement / cancel。
    # content 是唯一的自由文本载体（编辑全文 / 补充要求）。
    action: Literal["approve", "edit", "supplement", "cancel"]
    content: str = ""

    @model_validator(mode="after")
    def _require_content_for_plan_revision(self) -> "GateDecision":
        # 计划批准门的编辑 / 补充必须携带非空 content（协议前移校验，不做静默兜底）。
        if self.action in ("edit", "supplement") and not self.content.strip():
            raise ValueError(f"gate_decision action={self.action!r} 需要非空 content")
        return self


class ChatRequest(BaseModel):
    # 拒收未知字段，而不是静默丢弃。Pydantic v2 的默认 `extra="ignore"` 会让一个
    # 已从服务端删掉的字段仍然被发上来并接受（返回 200，但字段没生效）。
    # 一个被删掉的旋钮如果发上来还是 200，调用方没有任何办法知道它没生效：
    # 「静默接受一个无效字段」和「悄悄支持它」在客户端看来是同一件事。
    model_config = ConfigDict(extra="forbid")

    messages: List[ChatMessage]
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    route: Optional[RouteName] = None
    route_decision: Optional[RouteDecision] = None
    controlled_trip_identity: Optional[ControlledTripIdentity] = None
    guided_intake: Optional[GuidedIntakeState] = None
    selected_mcp_servers: List[str] = Field(default_factory=list)
    plan_gate: Optional[bool] = None
    gate_decision: Optional[GateDecision] = None
    preset_id: Optional[str] = None
