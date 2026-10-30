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
from travel_agent.planning.requirements.confirmation_contracts import AssertionDecisionInput
from travel_agent.conversation.intake_contracts import GuidedIntakeState
from travel_agent.conversation.intake_contracts import RouteDecision
from travel_agent.conversation.intake_contracts import RouteName


class ChatMessage(BaseModel):
    role: str
    content: str
    message_id: Optional[str] = None
    type: str = "normal"


class SemanticConfirmationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: str = Field(pattern=r"^challenge_[0-9a-f]{64}$")
    revision: int = Field(ge=0, strict=True)
    decisions: List[AssertionDecisionInput] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _unique_decisions(self) -> "SemanticConfirmationInput":
        ids = [item.assertion_id for item in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("semantic confirmation contains duplicate assertion ids")
        return self


class GateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # plan_gate：approve / edit / supplement / cancel。
    # content 是唯一的自由文本载体（编辑全文 / 补充要求）。
    # approval_token 是 gate payload 下发的版本凭据；除 cancel 外必须回传，
    # 服务端用它确认用户看到并批准的是同一版计划。
    action: Literal["approve", "edit", "supplement", "retry", "cancel"]
    content: str = ""
    approval_token: Optional[str] = Field(default=None, max_length=200)
    semantic_confirmation: Optional[SemanticConfirmationInput] = None

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
        # 结构化选择与自由补充必须区分；客户端不能同时提交值和修改文本。
        if self.semantic_confirmation is not None:
            if self.action != "supplement" or self.content.strip() or not self.approval_token:
                raise ValueError("semantic confirmation requires a versioned supplement without free text")
        elif self.action in ("edit", "supplement") and not self.content.strip():
            raise ValueError(f"gate_decision action={self.action!r} 需要非空 content")
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
