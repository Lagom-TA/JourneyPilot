"""运行中补充要求的命令与结果。"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import Field

from travel_agent.schema import StrictModel


class AmendmentImpact(str, Enum):
    RESEARCH_AFFECTING = "research_affecting"
    UNSUPPORTED = "unsupported"


class IntentAmendment(StrictModel):
    command_id: str = Field(min_length=1)
    category: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=2000)
    source_kind: Literal["plan_gate_amendment", "run_supplement"]
    impact: Optional[AmendmentImpact] = None


class IntentAmendmentRejection(StrictModel):
    command_id: str = Field(min_length=1)
    impact: AmendmentImpact
    reason_code: str = Field(min_length=1)
    requires_new_run: bool = False
