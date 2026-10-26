"""天气上下文展示。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from travel_agent.planning.state import TravelAgentState


def format_weather_context_for_planning(state: TravelAgentState) -> str:
    """保留逐小时细节供确定性检查使用，不在 prompt 中重复。"""

    context = state.weather_context
    if context is None:
        return ""
    destination_names = {
        item.destination_id: item.display_name for item in state.destination_geo
    }
    days: List[Dict[str, Any]] = []
    for item in context.days:
        days.append(
            {
                "destination_id": item.destination_id,
                "destination": destination_names.get(
                    item.destination_id, item.destination_id
                ),
                "date": item.date.isoformat(),
                "timezone": item.timezone,
                "data_kind": item.data_kind,
                "condition_code": item.condition_code,
                "condition_label": item.condition_label,
                "high_c": item.high_c,
                "low_c": item.low_c,
                "apparent_high_c": item.apparent_high_c,
                "precipitation_probability_pct": item.precipitation_probability_pct,
                "precipitation_mm": item.precipitation_mm,
                "wind_speed_kph": item.wind_speed_kph,
                "wind_gust_kph": item.wind_gust_kph,
                "fact_assertion_ids": item.fact_assertion_ids,
            }
        )
    payload = {
        "weather_data_revision": context.weather_data_revision,
        "trip_start_date": context.trip_start_date.isoformat(),
        "trip_end_date": context.trip_end_date.isoformat(),
        "days": days,
    }
    return (
        "【规划前天气事实】\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\n规则：forecast 可用于对应日期；seasonal_baseline 只能调整整体节奏、室内外平衡、"
        "穿衣与临行复查提醒，不得写成当天条件或触发逐日改动；data_kind=unavailable 时不得"
        "根据季节常识补写当天条件。"
    )
