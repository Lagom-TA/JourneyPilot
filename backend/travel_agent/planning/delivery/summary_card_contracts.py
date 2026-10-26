"""旅行摘要卡契约。"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field
from typing import Literal
from typing import Optional


class TripSummaryFact(BaseModel):
    label: str = Field(min_length=1, max_length=24)
    value: str = Field(min_length=1, max_length=80)
    state: Literal["confirmed", "default", "deferred"]


class TripSummaryCard(BaseModel):
    """紧凑与展开两种调研摘要状态共用的稳定载荷。"""

    headline: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=240)
    facts: list[TripSummaryFact] = Field(default_factory=list, max_length=5)
    priorities: list[str] = Field(default_factory=list, max_length=6)
    current_focus: str = Field(min_length=1, max_length=140)
    next_milestone: Optional[str] = Field(default=None, max_length=120)
    compact_line: str = Field(min_length=1, max_length=140)
    requires_user_confirmation: bool = False
