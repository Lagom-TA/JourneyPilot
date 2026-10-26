from __future__ import annotations

from travel_agent.planning.costs.coverage import build_cost_coverage_summary
from travel_agent.planning.costs.coverage import itinerary_price_components
from travel_agent.planning.itinerary.highlights import with_derived_highlights
from travel_agent.planning.itinerary.models import StructuredItineraryV2


def _recompute_derived_itinerary_fields(
    itinerary: StructuredItineraryV2,
) -> StructuredItineraryV2:

    return with_derived_highlights(itinerary).model_copy(
        update={
            "cost_summary": build_cost_coverage_summary(
                itinerary_price_components(
                    visit_stops=itinerary.visit_stops,
                    dining_stops=itinerary.dining_stops,
                    lodging_stays=itinerary.lodging_stays,
                    transport_legs=itinerary.transport_legs,
                ),
                budget_cap_cny=itinerary.cost_summary.budget_cap_cny,
                llm_estimated_total_cny=itinerary.cost_summary.llm_estimated_total_cny,
            ),
        }
    )
