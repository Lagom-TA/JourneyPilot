"""长途交通段判定。"""

from __future__ import annotations

from datetime import date
from datetime import timedelta
from travel_agent.planning.research.provider_contracts import ProviderRouteLegScope
from typing import AbstractSet
from typing import Any
from typing import Mapping
from typing import Optional
from typing import Sequence
import re


_EXPLICIT_CROSS_DAY_RETURN = re.compile(
    r"跨日|跨夜|次日|翌日|第二天到达|凌晨到达|overnight|red[- ]?eye",
    re.IGNORECASE,
)


def explicit_cross_day_return_required(text: str) -> bool:
    """判断是否明确要求跨日历日的返程。"""

    return bool(_EXPLICIT_CROSS_DAY_RETURN.search(text or ""))


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

    多目的地行程是访问顺序上的链，而不是简单往返。对
    ``[origin, *destinations, origin]``，每个相邻对都需要一个长途段：
    ``origin→city_1``（outbound）、每个中间边界 ``city_i→city_{i+1}``
    （inter_destination），以及末站不是出发地时的 ``city_M→origin``（return）。
    中间城市之间的段同样需要研究和绑定。

    每个目的地的停留天数在行程跨度内平均分配，余数给较早的城市；
    inter_destination 段在下一城市停留的第一天出发。
    """

    origin_id, destination_ids = _identity_parts(controlled_trip_identity)
    if not origin_id or not destination_ids:
        return []
    if origin_id == destination_ids[0] and destination_ids[-1] == origin_id:
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

    legs: list[ProviderRouteLegScope] = [
        ProviderRouteLegScope(
            leg_role="outbound",
            from_place_id=origin_id,
            to_place_id=destination_ids[0],
            service_date=start_date,
            cross_day_required=False,
        )
    ]

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
    if destination_ids[-1] != origin_id:
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


def missing_long_distance_leg_roles(
    required_legs: Sequence[ProviderRouteLegScope],
    *,
    day_dates: AbstractSet[date],
    dates_with_long_distance: AbstractSet[date],
) -> Optional[list[str]]:
    """列出计划中的 Day 未交付的必需长途交通段角色。

    返回 ``None`` 表示无法评估，所有读取方必须保持沉默。三种情况：Run 本身
    不承担长途段；组合出的 Day 没有覆盖某个必需服务日期（身份与行程描述的不
    是同一趟旅行）；某个服务日期承担多段且至少已有一段（同日往返时「当天有
    长途段」无法区分一段到达还是两段到达）。

    沉默与空列表含义不同：空列表断言所有必需段都已交付。

    区分同日两段中哪一段缺失需要逐段的交付身份，而交付段的端点是 provider
    binder 生成的站点级 id（``12306:{telecode}``、机场代码），必需段的端点是
    受控身份的城市级 id（``osm:relation:…``）；两者不会相等，强行匹配只能靠猜。
    """

    if not required_legs or any(
        leg.service_date not in day_dates for leg in required_legs
    ):
        return None
    owed_per_date: dict[date, int] = {}
    for leg in required_legs:
        owed_per_date[leg.service_date] = owed_per_date.get(leg.service_date, 0) + 1
    if any(
        owed > 1 and service_date in dates_with_long_distance
        for service_date, owed in owed_per_date.items()
    ):
        return None
    return [
        leg.leg_role
        for leg in required_legs
        if leg.service_date not in dates_with_long_distance
    ]
