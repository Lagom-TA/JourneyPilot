from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, List, Literal, Optional

from pydantic import Field, model_validator

from travel_agent.schema import StrictModel

if TYPE_CHECKING:
    from travel_agent.planning.itinerary.models import (
        DiningStop,
        LodgingStay,
        TransportLeg,
        VisitStop,
    )


def coverage_from_component_counts(
    *,
    priced_component_count: int,
    budget_relevant_component_count: int,
) -> Literal["none", "partial", "complete"]:

    if priced_component_count == 0:
        return "none"
    if priced_component_count == budget_relevant_component_count:
        return "complete"
    return "partial"


def itinerary_price_components(
    *,
    visit_stops: Iterable["VisitStop"],
    dining_stops: Iterable["DiningStop"],
    lodging_stays: Iterable["LodgingStay"],
    transport_legs: Iterable["TransportLeg"],
) -> List[Optional[float]]:

    return [
        *(item.estimated_cost_cny for item in visit_stops),
        *(item.estimated_cost_cny for item in dining_stops),
        *(item.total_price_cny for item in lodging_stays),
        *(item.total_cost_cny for item in transport_legs),
    ]


class CostCoverageSummary(StrictModel):
    known_subtotal_cny: Optional[float] = Field(default=None, ge=0)
    estimated_total_cny: Optional[float] = Field(default=None, ge=0)
    priced_component_count: int = Field(ge=0)
    budget_relevant_component_count: int = Field(ge=0)
    coverage: Literal["none", "partial", "complete"]
    budget_cap_cny: Optional[float] = Field(default=None, ge=0)
    budget_status: Literal["unknown", "within_cap", "over_cap"]

    # An inferred trip estimate never changes supplier totals or price coverage.
    llm_estimated_total_cny: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_coverage(self) -> "CostCoverageSummary":
        if self.priced_component_count > self.budget_relevant_component_count:
            raise ValueError(
                "priced component count cannot exceed budget-relevant count"
            )
        expected_coverage = coverage_from_component_counts(
            priced_component_count=self.priced_component_count,
            budget_relevant_component_count=self.budget_relevant_component_count,
        )
        if self.coverage != expected_coverage:
            raise ValueError("cost coverage does not match component counts")
        if self.coverage == "none" and self.known_subtotal_cny is not None:
            raise ValueError("cost coverage none cannot publish a known subtotal")
        if self.coverage != "none" and self.known_subtotal_cny is None:
            raise ValueError("priced components require a known subtotal")
        if self.coverage == "complete":
            if self.estimated_total_cny != self.known_subtotal_cny:
                raise ValueError(
                    "complete cost coverage requires an exact estimated total"
                )
        elif self.estimated_total_cny is not None:
            raise ValueError(
                "incomplete cost coverage cannot publish an estimated total"
            )
        expected_budget_status = "unknown"
        if (
            self.budget_cap_cny is not None
            and self.known_subtotal_cny is not None
            and self.known_subtotal_cny > self.budget_cap_cny
        ):
            expected_budget_status = "over_cap"
        elif self.budget_cap_cny is not None and self.coverage == "complete":
            expected_budget_status = "within_cap"
        if self.budget_status != expected_budget_status:
            raise ValueError("budget status does not match cost coverage and cap")
        return self

    @classmethod
    def empty(cls) -> "CostCoverageSummary":
        return cls(
            priced_component_count=0,
            budget_relevant_component_count=0,
            coverage="none",
            budget_status="unknown",
        )


def build_cost_coverage_summary(
    costs: Iterable[Optional[float]],
    *,
    budget_cap_cny: Optional[float] = None,
    llm_estimated_total_cny: Optional[float] = None,
) -> CostCoverageSummary:
    # Preserve the caller's cap and inferred estimate when rebuilding priced totals.
    components = list(costs)
    known = [float(cost) for cost in components if cost is not None]
    coverage = coverage_from_component_counts(
        priced_component_count=len(known),
        budget_relevant_component_count=len(components),
    )
    subtotal = sum(known) if known else None
    budget_status = (
        "over_cap"
        if budget_cap_cny is not None
        and subtotal is not None
        and subtotal > budget_cap_cny
        else "within_cap"
        if budget_cap_cny is not None and coverage == "complete"
        else "unknown"
    )
    return CostCoverageSummary(
        known_subtotal_cny=subtotal,
        estimated_total_cny=subtotal if coverage == "complete" else None,
        priced_component_count=len(known),
        budget_relevant_component_count=len(components),
        coverage=coverage,
        budget_cap_cny=budget_cap_cny,
        budget_status=budget_status,
        llm_estimated_total_cny=llm_estimated_total_cny,
    )
