from __future__ import annotations

from typing import List
from typing import Literal
from typing import Optional
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from pydantic import field_validator
from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity, PlaceIdentity
from travel_agent.conversation.intake_contracts import GuidedIntakeState
from travel_agent.conversation.intake_contracts import RouteDecision
from travel_agent.conversation.intake_contracts import RouteName


class ChatMessage(BaseModel):
    role: str
    content: str
    message_id: Optional[str] = None
    type: str = "normal"


class GateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # plan_gate：approve / supplement / retry / cancel。
    # content 保存补充要求。
    # approval_token 是 gate payload 下发的版本凭据；除 cancel 外必须回传，
    # 服务端用它确认用户看到并批准的是同一版计划。
    action: Literal["approve", "supplement", "retry", "cancel"]
    content: str = ""
    approval_token: Optional[str] = Field(default=None, max_length=200)

    @field_validator("approval_token", mode="before")
    @classmethod
    def _invalid_unicode_is_not_an_approval_token(cls, value):
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                return None
        return value

    @model_validator(mode="after")
    def _require_content_for_plan_revision(self) -> "GateDecision":
        if self.action == "supplement" and not self.content.strip():
            raise ValueError("补充要求不能为空")
        if self.action != "supplement" and self.content.strip():
            raise ValueError("只有补充要求可以包含内容")
        return self


class ChatRequest(BaseModel):
    # 拒收未知字段，避免静默忽略。Pydantic v2 默认的 extra="ignore" 会接受已从
    # 服务端删除的字段并返回 200，调用方无法得知该字段未生效。
    model_config = ConfigDict(extra="forbid")

    messages: List[ChatMessage]
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    route: Optional[RouteName] = None
    route_decision: Optional[RouteDecision] = None
    controlled_trip_identity: Optional[ControlledTripIdentity] = None
    guided_intake: Optional[GuidedIntakeState] = None
    intake_id: Optional[str] = Field(default=None, pattern=r"^(?:it|legacy)_[0-9a-f]{32}$")
    intake_revision: Optional[int] = Field(default=None, ge=0, strict=True)
    intake_destination: Optional[PlaceIdentity] = None
    selected_mcp_servers: List[str] = Field(default_factory=list)
    plan_gate: Optional[bool] = None
    gate_decision: Optional[GateDecision] = None
    preset_id: Optional[str] = None
