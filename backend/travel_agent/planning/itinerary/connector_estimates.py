from __future__ import annotations

import json
from typing import Any, Dict, List

from travel_agent.planning.itinerary.connectors import (
    LocalConnectorGap,
)
from travel_agent.planning.itinerary.draft import (
    AUTHORED_ROUTE_CLASS_BY_MODE,
    AuthoredRoute,
)


def _authored_connector_schema(gap_ids: List[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "connectors": {
                "type": "array",
                "minItems": len(gap_ids),
                "maxItems": len(gap_ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "gap_id": {"type": "string", "enum": gap_ids},
                        "mode": {
                            "type": "string",
                            "enum": sorted(AUTHORED_ROUTE_CLASS_BY_MODE),
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 360,
                        },
                        "selection_reason": {"type": "string", "minLength": 1},
                    },
                    "required": [
                        "gap_id",
                        "mode",
                        "duration_minutes",
                        "selection_reason",
                    ],
                },
            }
        },
        "required": ["connectors"],
    }


async def _author_connector_routes(
    llm: Any,
    gaps: List[LocalConnectorGap],
) -> Dict[str, AuthoredRoute]:
    """为没有 Provider 路线的每段相邻关系撰写一条门到门接驳。"""
    gap_ids = [gap.gap_id for gap in gaps]
    described = [
        {
            "gap_id": gap.gap_id,
            "day_date": gap.day_date.isoformat(),
            "from_place_id": gap.from_place_id,
            "to_place_id": gap.to_place_id,
            "from_endpoint": gap.from_endpoint.model_dump(mode="json")
            if gap.from_endpoint
            else None,
            "to_endpoint": gap.to_endpoint.model_dump(mode="json")
            if gap.to_endpoint
            else None,
            "leave_after": gap.departure_time.isoformat(),
            "arrive_before": gap.latest_arrival_time.isoformat(),
            "requested_modes": gap.requested_flexible_modes,
        }
        for gap in gaps
    ]
    schema = _authored_connector_schema(gap_ids)
    response = await llm.ainvoke(
        [
            {
                "role": "system",
                "content": (
                    "你是 JourneyPilot 的行程组合器。为下列相邻停留点之间各写一段市内交通："
                    "选一个出行方式，并给出门到门分钟数与一句选择理由。"
                    "根据真实端点名称和位置信息估算合理门到门耗时，不得为了装进时间窗压缩分钟数。"
                    "若合理耗时超过时间窗，仍返回真实估算，由行程安排自行调整。"
                    "端点由服务器按前后两个停留点填写，你不要写地点、线路号或票价。"
                ),
            },
            {
                "role": "user",
                "content": f"待补的相邻段：{json.dumps(described, ensure_ascii=False)}",
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "authored_local_connectors",
                "strict": True,
                "schema": schema,
            },
        },
        temperature=0,
    )
    content = response.content if hasattr(response, "content") else response
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    payload = json.loads(content)
    items = payload.get("connectors") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("connector authoring must return one connectors list")
    routes: Dict[str, AuthoredRoute] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        gap_id = str(item.get("gap_id") or "")
        if gap_id not in gap_ids or gap_id in routes:
            continue
        routes[gap_id] = AuthoredRoute(
            mode=item.get("mode"),
            duration_minutes=int(item.get("duration_minutes") or 0),
            selection_reason=str(item.get("selection_reason") or ""),
        )
    missing = [gap_id for gap_id in gap_ids if gap_id not in routes]
    if missing:
        raise ValueError(f"connector authoring skipped adjacencies: {missing}")
    return routes
