from __future__ import annotations

from datetime import timedelta

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from travel_agent.planning.itinerary.models import DayPlanV2
    from travel_agent.planning.itinerary.models import LodgingStay
    from travel_agent.planning.itinerary.models import StructuredItineraryV2


def day_lodging_bases(
    itinerary: StructuredItineraryV2, day: DayPlanV2
) -> tuple[LodgingStay | None, LodgingStay | None]:
    """返回当天出发时的住宿与当晚入住的住宿。

    实际住宿记录优先。长途出发/到达投影会在旅行者已经离开或尚未到达的一侧
    排除住宿。不推断酒店入住时间，也不推断预订可用性。
    """

    def base(night):
        return next(
            (
                stay
                for stay in itinerary.lodging_stays
                if stay.check_in_date <= night < stay.check_out_date
            ),
            None,
        )

    morning, evening = base(day.date - timedelta(days=1)), base(day.date)
    legs = {leg.transport_leg_id: leg for leg in itinerary.transport_legs}
    nodes = [
        ref
        for ref in day.timeline
        if str(getattr(ref.entity_type, "value", ref.entity_type))
        in {"visit_stop", "dining_stop"}
        or (
            ref.entity_id in legs
            and legs[ref.entity_id].transport_class == "long_distance"
        )
    ]
    if nodes:
        first = legs.get(nodes[0].entity_id)
        last = legs.get(nodes[-1].entity_id)
        if (
            first is not None
            and first.departure_at is not None
            and first.departure_at.date() < day.date
        ):
            morning = None
        if (
            last is not None
            and last.arrival_at is not None
            and last.arrival_at.date() > day.date
        ):
            evening = None

        first_destination_date = min(
            item.date
            for item in itinerary.day_plans
            if item.destination_id == day.destination_id
        )
        if (
            last is not None
            and last.departure_at is not None
            and last.arrival_at is not None
            and last.departure_at.date() == last.arrival_at.date()
            and day.date > first_destination_date
        ):
            evening = None
    return morning, evening
