"""规划阶段的交通语义。"""

from __future__ import annotations

from typing import Iterable
from typing import Protocol


class _ServiceSegment(Protocol):
    mode: object
    service_number: str | None
    line_name: str | None
    operator_name: str | None


_SERVICE_MODES = {
    "flight",
    "high_speed_rail",
    "train",
    "coach",
    "ferry",
    "metro",
    "bus",
    "tram",
}

_ROAD_DISPLAY_MODES = frozenset({"taxi", "ride_hailing"})


def _mode_value(mode: object) -> str:
    return str(getattr(mode, "value", mode))


def provider_route_mode(requested_mode: object) -> str:
    """把展示方式映射为路线 Provider 支持的道路查询方式。"""
    requested = _mode_value(requested_mode)
    return "drive" if requested in _ROAD_DISPLAY_MODES else requested


def transport_mode_satisfies(provider_mode: object, requested_mode: object) -> bool:
    """判断 Provider 方式能否承载指定展示方式，出租车与网约车共用道路几何。"""
    provider = _mode_value(provider_mode)
    requested = _mode_value(requested_mode)
    return provider == requested or (
        provider == "drive" and requested in _ROAD_DISPLAY_MODES
    )


def replacement_display_mode(current_mode: object, candidate_mode: object) -> object:
    """替换道路候选时保留当前出租车或网约车展示方式，其余候选保持原方式。"""
    if _mode_value(current_mode) in _ROAD_DISPLAY_MODES and transport_mode_satisfies(
        candidate_mode, current_mode
    ):
        return current_mode
    return candidate_mode


def count_service_transfers(segments: Iterable[_ServiceSegment]) -> int:
    """统计已证实的乘坐服务变更次数，忽略进出站段。

    同一趟车或同一条线路可能由多个 provider segment 描述；同模式下未命名的
    segment 不能证明发生换乘，因此沿用上一个已知身份，而不是据此新增换乘。
    """
    previous_mode: str | None = None
    previous_number: str | None = None
    previous_line: str | None = None
    previous_operator: str | None = None
    transfers = 0
    for segment in segments:
        mode = str(getattr(segment.mode, "value", segment.mode))
        if mode not in _SERVICE_MODES:
            continue
        number = (segment.service_number or "").strip().casefold() or None
        line = (segment.line_name or "").strip().casefold() or None
        operator = (segment.operator_name or "").strip().casefold() or None
        different_service = (
            number != previous_number
            if number is not None and previous_number is not None
            else line is not None
            and previous_line is not None
            and line != previous_line
        )
        changed = previous_mode is not None and (
            mode != previous_mode
            or different_service
            or (
                operator is not None
                and previous_operator is not None
                and operator != previous_operator
            )
        )
        if changed:
            transfers += 1
        if changed or previous_mode is None:
            previous_number = number
            previous_line = line
            previous_operator = operator
        else:
            previous_number = number or previous_number
            previous_line = line or previous_line
            previous_operator = operator or previous_operator
        previous_mode = mode
    return transfers
