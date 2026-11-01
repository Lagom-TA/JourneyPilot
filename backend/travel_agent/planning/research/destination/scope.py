from __future__ import annotations

import json
from typing import Any, Dict, List

from travel_agent.planning.research.destination.prompts import TASK_TEMPLATE

_NODE_NAME = "destination_researcher"


def build_destination_boundaries(
    controlled_trip_identity: Dict[str, Any] | None,
) -> List[Dict[str, Any]]:
    """把受控目的地投影成 worker 查询使用的边界结构。"""
    return [
        {
            "destination_id": str(item.get("place_id") or ""),
            "name": str(item.get("name") or ""),
            "country_code": str(item.get("country_code") or "").casefold(),
            "latitude": item.get("latitude"),
            "longitude": item.get("longitude"),
        }
        for item in (controlled_trip_identity or {}).get("destinations", [])
        if isinstance(item, dict)
    ]


def build_destination_task_prompt(
    *,
    task_desc: str,
    user_query: str,
    destination_boundaries: List[Dict[str, Any]] | None = None,
) -> str:
    """把受控目的地边界交给目的地研究员。"""
    boundaries = json.dumps(destination_boundaries or [], ensure_ascii=False)
    return (
        TASK_TEMPLATE.format(
            task_desc=task_desc,
            user_query=user_query,
        )
        + f"\n受控目的地边界：{boundaries}。所有地点必须保留 Provider 原始国家码并与对应 destination_id 一致。"
    )
