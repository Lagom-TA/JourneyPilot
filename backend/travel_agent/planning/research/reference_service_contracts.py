from __future__ import annotations

from datetime import date
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from typing import List
from typing import Literal
from typing import Optional


class ProviderReferenceService(BaseModel):
    """在非请求日期观察到的一条 Provider 班次，以及仍未确认的声明。

    ``unconfirmed_claims`` 原样复制自 Provider 信封的
    ``claims_not_confirmed_for_requested_date``，不在此处重新推导：哪些字段
    不能跨日期沿用只能由供应商声明，本地硬编码会在供应商变更后继续沿用旧答案。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    leg_role: Literal["outbound", "return"]
    from_name: str = Field(min_length=1)
    to_name: str = Field(min_length=1)
    service_number: str = Field(min_length=1)
    departure_time: str = Field(min_length=1)
    arrival_time: str = Field(min_length=1)
    duration_minutes: Optional[int] = Field(default=None, ge=0)
    lowest_observed_price_cny: Optional[float] = Field(default=None, ge=0)
    requested_date: date
    reference_date: date
    unconfirmed_claims: List[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dates(self) -> "ProviderReferenceService":
        if self.reference_date == self.requested_date:
            raise ValueError("a reference service is only a reference for another date")
        return self
