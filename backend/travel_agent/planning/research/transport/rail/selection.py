from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional

from travel_agent.planning.requirements.constraint_applicability import (
    active_hard_constraints,
)
from travel_agent.planning.research.transport.scope import _NODE_NAME

logger = logging.getLogger(__name__)


_HIGH_SPEED_PREFIXES = {"G", "D", "C"}


MIN_SAME_DAY_RETURN_STAY_MINUTES = 3 * 60


def _select_best_train(
    trains: List[Dict[str, Any]],
    *,
    requested_from: Optional[str] = None,
    requested_to: Optional[str] = None,
    leg_role: Optional[str] = None,
    depart_after: Optional[str] = None,
    same_day_roundtrip: bool = False,
) -> Optional[Dict[str, Any]]:
    """按明确的选车策略选择，不依赖 Provider 返回顺序。"""

    if not trains:
        return None

    if depart_after:
        after_minutes = _rail_time_to_minutes(depart_after)
        late_trains = [
            train
            for train in trains
            if _rail_time_to_minutes(str(train.get("departure_time") or ""))
            >= after_minutes
        ]
        if not late_trains:
            logger.info(
                "[transport_researcher] depart_after=%s after_min=%d candidates=%d late=%d -> FALLBACK",
                depart_after,
                after_minutes,
                len(trains),
                len(late_trains),
            )
        if late_trains:
            trains = late_trains

    if same_day_roundtrip and leg_role not in ("return", "inter_destination"):
        return min(
            trains,
            key=lambda t: _rail_time_to_minutes(
                str(t.get("departure_time") or "23:59")
            ),
        )

    def is_high_speed(train: Mapping[str, Any]) -> bool:
        return str(train.get("train_code") or "")[:1] in _HIGH_SPEED_PREFIXES

    def endpoint_rank(train: Mapping[str, Any]) -> int:
        matched = 0
        if requested_from and str(train.get("from_code") or "") == requested_from:
            matched += 1
        if requested_to and str(train.get("to_code") or "") == requested_to:
            matched += 1
        return -matched

    def policy_key(train: Mapping[str, Any]) -> tuple:
        return (
            0 if train.get("min_price_cny") is not None else 1,
            endpoint_rank(train),
            0 if is_high_speed(train) else 1,
            int(train.get("duration_minutes") or 10**9),
            _rail_time_to_minutes(str(train.get("departure_time") or "23:59")),
            str(train.get("train_code") or ""),
        )

    if leg_role in {"return", "inter_destination"}:
        day_window_candidates = [
            train
            for train in trains
            if _rail_time_to_minutes(str(train.get("departure_time") or "")) >= 8 * 60
        ]
        if day_window_candidates:
            return min(day_window_candidates, key=policy_key)

    return min(trains, key=policy_key)


def _rail_time_to_minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _clock_plus_buffer(clock: str, buffer_minutes: int) -> str:
    """返回向后推移 ``buffer_minutes`` 分钟的 ``HH:MM`` 时间。"""
    try:
        total = _rail_time_to_minutes(clock) + int(buffer_minutes or 0)
    except (TypeError, ValueError):
        return clock
    total %= 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"


def _rail_constraint_params(constraint_pack: Any) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for constraint in active_hard_constraints(
        constraint_pack,
        worker_kind=_NODE_NAME,
    ):
        if constraint.get("category") != "transport_constraint":
            continue
        params = constraint.get("params")
        if isinstance(params, Mapping):
            merged.update(params)
    return merged


def _filter_rail_trains(
    trains: List[Dict[str, Any]],
    constraint_params: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """在挑选班次前应用标准的交通硬约束。"""

    earliest = str(constraint_params.get("earliest_departure_local") or "")
    latest = str(constraint_params.get("latest_arrival_local") or "")
    avoid_overnight = constraint_params.get("avoid_overnight") is True
    filtered: List[Dict[str, Any]] = []
    for train in trains:
        departure = _rail_time_to_minutes(str(train["departure_time"]))
        arrival = _rail_time_to_minutes(str(train["arrival_time"]))
        if earliest and departure < _rail_time_to_minutes(earliest):
            continue
        if latest and arrival > _rail_time_to_minutes(latest):
            continue
        if avoid_overnight and arrival < departure:
            continue
        filtered.append(train)
    return filtered


def _rail_iso(date_str: str, clock: str) -> str:
    hours, minutes = clock.split(":")
    return f"{date_str}T{int(hours):02d}:{int(minutes):02d}:00+08:00"
