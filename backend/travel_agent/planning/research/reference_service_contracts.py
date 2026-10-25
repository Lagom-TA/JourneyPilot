"""Planning research reference service contracts."""

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
    """One provider service observed off-date, with the claims that stay unconfirmed.

    ``unconfirmed_claims`` is copied verbatim from the provider envelope's
    ``claims_not_confirmed_for_requested_date``.  It is never re-derived here:
    which claims a supplier declines to carry across dates is the supplier's
    statement, and a hardcoded list here would keep asserting the old answer
    after the supplier changed it.
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
