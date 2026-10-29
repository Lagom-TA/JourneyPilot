from __future__ import annotations

from travel_agent.planning.costs.coverage import build_cost_coverage_summary
from travel_agent.planning.costs.coverage import itinerary_price_components
from travel_agent.planning.itinerary.highlights import with_derived_highlights
from travel_agent.planning.itinerary.models import StructuredItineraryV2


def _recompute_derived_itinerary_fields(
    itinerary: StructuredItineraryV2,
) -> StructuredItineraryV2:
    """重算可确定性派生的字段。

    ``title`` 与 ``theme`` 是正式文案快照，只由完整组合后的文案步骤生成。
    局部 mutation 在数据库事务里运行，不能在事务中调用模型，也不伪装成已刷新：
    这里保留原文案，下一次重新组合会基于新内容重新生成。
    """

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
