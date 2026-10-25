from __future__ import annotations

import json
from typing import Any

from travel_agent.conversation.history import append_recent_history
from travel_agent.entities.state import TravelAgentState
from travel_agent.planning.itinerary.checks import validate_placement_skeleton
from travel_agent.planning.itinerary.connectors import (
    connector_mode_requests_from_constraint_pack,
    extract_local_connector_gaps,
)
from travel_agent.planning.itinerary.draft import (
    ItineraryCompositionDraft,
)
from travel_agent.planning.itinerary.locations import (
    _reuse_located_places,
    locate_authored_composition,
)
from travel_agent.planning.itinerary.model_schema import _composition_response_schema
from travel_agent.planning.itinerary.parsing import _parse_exact_llm_composition
from travel_agent.planning.itinerary.prompts import _build_composition_prompt
from travel_agent.planning.itinerary.requirements import _required_leg_scope_ids
from travel_agent.services.day_planning import (
    default_walking_days,
)


async def _compose_draft(
    state: TravelAgentState,
    task_desc: str,
    llm: Any,
    required_candidate_kinds: set[str],
    required_legs: list,
    unlocatable: set[str],
) -> ItineraryCompositionDraft:
    native_schema = bool(
        getattr(getattr(llm, "capabilities", None), "supports_json_schema", False)
    )
    prompt = _build_composition_prompt(
        state,
        task_desc,
        skeleton_only=True,
        required_candidate_kinds=required_candidate_kinds,
        required_long_distance_legs=required_legs,
        strict_wire_schema=native_schema,
    )
    messages = [{"role": "system", "content": prompt.system}]
    append_recent_history(messages, state, limit=4)
    messages.append({"role": "user", "content": prompt.runtime})
    kwargs = {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "itinerary_composition_draft",
                "strict": native_schema,
                "schema": _composition_response_schema(
                    state.recommendation_catalog,
                    skeleton_only=True,
                    strict_wire=native_schema,
                ),
            },
        },
        "temperature": 0,
    }
    previous = state.placement_skeleton
    for attempt in range(2):
        response = await llm.ainvoke(messages, **kwargs)
        content = response.content if hasattr(response, "content") else response
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        draft = None
        try:
            draft = _reuse_located_places(
                _parse_exact_llm_composition(content, state), previous
            )
            draft = await locate_authored_composition(draft, llm, state, unlocatable)
            previous = draft
            validate_placement_skeleton(
                draft,
                state.recommendation_catalog,
                required_candidate_kinds=required_candidate_kinds,
                required_long_distance_legs=required_legs,
                required_leg_scope_ids=_required_leg_scope_ids(
                    required_legs,
                    state.run_id,
                    state.constraint_pack_revision,
                ),
            )
            requests, required_pairs = connector_mode_requests_from_constraint_pack(
                draft,
                state.constraint_pack,
                state.recommendation_catalog,
            )
            extract_local_connector_gaps(
                draft,
                state.recommendation_catalog,
                weather_data_revision=state.recommendation_catalog.weather_data_revision,
                flexible_mode_requests=requests,
                required_flexible_mode_pairs=required_pairs,
                default_walk_day_ids=default_walking_days(state, draft),
                required_candidate_kinds=required_candidate_kinds,
            )
            return draft
        except ValueError as exc:
            draft = getattr(exc, "composition", None) or draft
            if draft is not None:
                previous = draft
            if attempt:
                exc.composition = previous
                raise
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": (
                            draft.model_dump_json() if draft is not None else content
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "修订以上完整草稿，只解决以下具体问题并保留未受影响的地点、活动、餐次、休息与固定长途。"
                            "仍返回不含市内交通的完整草稿，不得由服务器删除或机械移动内容。"
                            f"具体问题：{exc}"
                        ),
                    },
                ]
            )
    raise AssertionError("composition attempt budget exhausted")
