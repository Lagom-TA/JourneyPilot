"""在正式投影前，用真实日程生成一次自然短标题与每日主题。"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from travel_agent.planning.itinerary.materialize import (
    _controlled_destination_names,
)
from travel_agent.planning.workspace import TripWorkspace
from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.storage.worker_journal_store import JournalConflict

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """你是旅行行程的中文文案编辑。根据已安排的行程写总标题和每日主题，每段建议 10 到 15 个字。
输出一个 JSON 对象：{"title": "总标题", "days": [{"day_id": "对应的 day_id", "theme": "当天主题"}]}。
days 中的 day_id 与输入中的每一天一一对应。"""


def _day_copy_inputs(workspace: TripWorkspace) -> list[dict[str, Any]]:
    itinerary = workspace.itinerary
    destination_names = _controlled_destination_names(workspace.user_input_anchors)
    entries = {
        **{("visit_stop", stop.item_id): stop.name for stop in itinerary.visit_stops},
        **{("dining_stop", stop.item_id): stop.name for stop in itinerary.dining_stops},
        **{("custom_block", block.item_id): block.title for block in itinerary.custom_blocks},
        **{
            ("transport_leg", leg.transport_leg_id): (
                f"{leg.from_endpoint.name}→{leg.to_endpoint.name}"
                f"（{leg.selected_mode.value}）"
            )
            for leg in itinerary.transport_legs
        },
    }
    return [
        {
            "day_id": day.day_id,
            "day": day.day,
            "date": day.date.isoformat(),
            "city": destination_names.get(day.destination_id),
            "lodging": [
                stay.name
                for stay in itinerary.lodging_stays
                if stay.check_in_date <= day.date < stay.check_out_date
            ],
            "timeline": [
                {"type": entry.entity_type.value, "content": entries[key]}
                for entry in day.timeline
                if (key := (entry.entity_type.value, entry.entity_id)) in entries
            ],
        }
        for day in itinerary.day_plans
    ]


def _copy_payload(workspace: TripWorkspace) -> dict[str, Any]:
    itinerary = workspace.itinerary
    destination_names = _controlled_destination_names(workspace.user_input_anchors)
    return {
        "current_title": itinerary.title,
        "destinations": [
            destination_names.get(destination_id, destination_id)
            for destination_id in itinerary.destination_ids
        ],
        "duration_days": itinerary.duration_days,
        "days": _day_copy_inputs(workspace),
    }


def _message_text(response: Any) -> str:
    content = response.content if hasattr(response, "content") else response
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _copy_field(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"title response {field} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"title response is missing {field}")
    return text


def _parse_copy_response(
    text: str, day_ids: list[str]
) -> tuple[str, dict[str, str]]:
    try:
        payload = json.loads(_strip_code_fence(text))
    except (TypeError, ValueError) as exc:
        raise ValueError("title response is not a JSON object") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("title response must be an object")
    title = _copy_field(payload.get("title"), "trip title")
    raw_days = payload.get("days")
    if not isinstance(raw_days, list):
        raise ValueError("title response is missing day themes")
    themes: dict[str, str] = {}
    for item in raw_days:
        if not isinstance(item, Mapping):
            raise ValueError("title response day entry must be an object")
        raw_day_id = item.get("day_id")
        if not isinstance(raw_day_id, str) or not raw_day_id.strip():
            raise ValueError("title response day entry needs day_id and theme")
        day_id = raw_day_id.strip()
        theme = _copy_field(item.get("theme"), "day theme")
        if day_id in themes:
            raise ValueError(f"title response repeats day {day_id}")
        themes[day_id] = theme
    if set(themes) != set(day_ids):
        raise ValueError("title response must cover every day exactly once")
    return title, themes


async def write_itinerary_copy(
    workspace: TripWorkspace,
    llm: Any,
) -> TripWorkspace:
    """一次批量写回正式标题与每日主题；失败时保留已有的可交付行程。"""

    day_ids = [day.day_id for day in workspace.itinerary.day_plans]
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                _copy_payload(workspace), ensure_ascii=False, separators=(",", ":")
            ),
        },
    ]
    try:
        response = await llm.ainvoke(messages, temperature=0)
        title, themes = _parse_copy_response(_message_text(response), day_ids)
    except (RunCancelled, JournalConflict):
        raise
    except Exception as exc:
        logger.warning("itinerary title writing kept existing copy: %s", exc)
        return workspace
    itinerary = workspace.itinerary.model_copy(
        update={
            "title": title,
            "day_plans": [
                day.model_copy(update={"theme": themes[day.day_id]})
                for day in workspace.itinerary.day_plans
            ],
        }
    )
    return workspace.model_copy(update={"itinerary": itinerary})
