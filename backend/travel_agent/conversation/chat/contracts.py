from __future__ import annotations

from typing import List
from typing import Literal
from typing import Optional
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from pydantic import field_validator
from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity
from travel_agent.conversation.intake_contracts import RouteDecision
from travel_agent.conversation.intake_contracts import RouteName
from travel_agent.planning.requirements.understanding.contracts import UnderstandingAnswer


class ChatMessage(BaseModel):
    role: str
    content: str
    message_id: Optional[str] = None
    type: str = "normal"


class GateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # plan_gate：approve / supplement / retry / cancel；content 保存补充要求。
    # understanding_gate：answer；answers 是对当前待答问题的逐题回答。
    # approval_token 是 gate payload 下发的版本凭据；除 cancel 外必须回传，
    # 服务端用它确认用户看到并决定的是同一版内容。
    action: Literal["approve", "supplement", "retry", "cancel", "answer"]
    content: str = ""
    answers: List[UnderstandingAnswer] = Field(default_factory=list)
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
    def _validate_decision_payload(self) -> "GateDecision":
        if self.action == "supplement":
            if not self.content.strip():
                raise ValueError("补充要求不能为空")
            if self.answers:
                raise ValueError("补充要求不通过 answers 提交")
            return self
        if self.action == "answer":
            if self.content.strip():
                raise ValueError("回答不通过 content 提交")
            if not self.answers:
                raise ValueError("回答不能为空")
            if len({answer.question_id for answer in self.answers}) != len(self.answers):
                raise ValueError("回答包含重复的问题")
            return self
        if self.content.strip():
            raise ValueError("只有补充要求可以包含内容")
        if self.answers:
            raise ValueError("只有回答可以包含 answers")
        return self


class ChatRequest(BaseModel):
    # 拒收未知字段，避免静默忽略。
    model_config = ConfigDict(extra="forbid")

    messages: List[ChatMessage]
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    route: Optional[RouteName] = None
    route_decision: Optional[RouteDecision] = None
    controlled_trip_identity: Optional[ControlledTripIdentity] = None
    plan_gate: Optional[bool] = None
    gate_decision: Optional[GateDecision] = None
    preset_id: Optional[str] = None
