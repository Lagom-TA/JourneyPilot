"""长途交通段判定。"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from travel_agent.planning.research.provider_contracts import ProviderRouteLegScope
from typing import Any
from typing import Mapping


def _identity_parts(
    controlled_trip_identity: Mapping[str, Any],
) -> tuple[str, list[str]]:
    origin = controlled_trip_identity.get("origin")
    destinations = controlled_trip_identity.get("destinations")
    origin_id = (
        str(origin.get("place_id") or "").strip() if isinstance(origin, Mapping) else ""
    )
    destination_ids = [
        str(item.get("place_id") or "").strip()
        for item in destinations or ()
        if isinstance(item, Mapping) and str(item.get("place_id") or "").strip()
    ]
    return origin_id, list(dict.fromkeys(destination_ids))


def build_required_long_distance_legs(
    controlled_trip_identity: Mapping[str, Any],
    *,
    cross_day_return_required: bool,
) -> list[ProviderRouteLegScope]:
    """推导行程链上每个长途交通段的职责。

    按访问顺序生成目的地之间的跨城段；已知出发地时，再生成往返段。
    每个目的地的停留天数在行程跨度内平均分配，余数给较早的城市；
    目的地之间的交通段在下一城市停留的第一天出发。
    """

    origin_id, destination_ids = _identity_parts(controlled_trip_identity)
    if not destination_ids:
        return []
    if origin_id and origin_id == destination_ids[0] and destination_ids[-1] == origin_id:
        return []
    try:
        start_date = date.fromisoformat(
            str(controlled_trip_identity.get("start_date") or "")[:10]
        )
        end_date = date.fromisoformat(
            str(controlled_trip_identity.get("end_date") or "")[:10]
        )
    except ValueError:
        return []
    if end_date < start_date:
        return []

    span_days = (end_date - start_date).days + 1
    num_destinations = len(destination_ids)

    base, remainder = divmod(span_days, num_destinations)
    per_city: list[int] = [
        base + (1 if i < remainder else 0) for i in range(num_destinations)
    ]

    starts: list[date] = []
    cursor = start_date
    for n in per_city:
        starts.append(cursor)
        cursor += timedelta(days=n)

    legs: list[ProviderRouteLegScope] = []
    if origin_id and destination_ids[0] != origin_id:
        legs.append(
            ProviderRouteLegScope(
                leg_role="outbound",
                from_place_id=origin_id,
                to_place_id=destination_ids[0],
                service_date=start_date,
                cross_day_required=False,
            )
        )

    for i in range(num_destinations - 1):
        legs.append(
            ProviderRouteLegScope(
                leg_role="inter_destination",
                from_place_id=destination_ids[i],
                to_place_id=destination_ids[i + 1],
                service_date=starts[i + 1],
                cross_day_required=False,
            )
        )
    if origin_id and destination_ids[-1] != origin_id:
        legs.append(
            ProviderRouteLegScope(
                leg_role="return",
                from_place_id=destination_ids[-1],
                to_place_id=origin_id,
                service_date=end_date,
                cross_day_required=cross_day_return_required,
            )
        )
    return legs

