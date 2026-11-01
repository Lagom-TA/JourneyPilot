"""根据旅行基础信息创建并封存行程框架。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from travel_agent.planning.deadlines import build_run_deadline_snapshot
from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity
from travel_agent.planning.requirements.inputs import MinimumDeliveryDayShell, MinimumDeliveryDraft, UserInputAnchor
from travel_agent.runtime.budget import build_run_budget_snapshot
from travel_agent.runtime.deadlines import utc_now


def _canonical_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def build_minimum_delivery_draft(state: Any) -> Optional[MinimumDeliveryDraft]:
    if not state.controlled_trip_identity:
        return None
    if state.planning_generation is None or not state.run_id:
        raise ValueError("行程框架需要运行和规划版本")
    identity = ControlledTripIdentity.model_validate(state.controlled_trip_identity)
    identity_payload = identity.model_dump(mode="json")
    anchors = [UserInputAnchor(anchor_id="trip_identity", field_path="controlled_trip_identity", value=identity_payload, input_kind="controlled_identity")]
    if identity.origin.place_id:
        anchors.append(UserInputAnchor(anchor_id="origin", field_path="controlled_trip_identity.origin", value=identity_payload["origin"], input_kind="controlled_identity"))
    for index, destination in enumerate(identity_payload["destinations"]):
        anchors.append(UserInputAnchor(anchor_id=f"destination_{index}", field_path=f"controlled_trip_identity.destinations.{index}", value=destination, input_kind="controlled_identity"))
    anchors.append(UserInputAnchor(anchor_id="requirements", field_path="current_requirements", value=state.current_requirements, input_kind="requirements"))
    shells = []
    previous = None
    for index in range(identity.duration_days):
        destination = identity.destinations[min(index * len(identity.destinations) // identity.duration_days, len(identity.destinations) - 1)]
        shells.append(MinimumDeliveryDayShell(
            day_id=f"day_{index + 1}", day=index + 1, date=identity.start_date + timedelta(days=index), destination_id=destination.place_id,
            lodging_night=index < identity.duration_days - 1,
            arrival_from_destination_id=previous if previous and previous != destination.place_id else None,
        ))
        previous = destination.place_id
    material = {
        "run_id": state.run_id,
        "planning_generation_id": state.planning_generation.generation_id,
        "day_shells": [item.model_dump(mode="json") for item in shells],
        "user_input_anchors": [item.model_dump(mode="json") for item in anchors],
    }
    digest = _canonical_hash(material)
    return MinimumDeliveryDraft(draft_id=f"draft_{digest[:24]}", content_hash=digest, **material)


async def minimum_delivery_draft_builder_node(state: Any) -> Dict[str, Any]:
    draft = build_minimum_delivery_draft(state)
    if state.minimum_delivery_draft and draft and state.minimum_delivery_draft.draft_id == draft.draft_id:
        return {}
    return {"minimum_delivery_draft": draft}


def seal_minimum_delivery_draft(state: Any, *, authorized_at: Optional[datetime] = None) -> Dict[str, Any]:
    draft = state.minimum_delivery_draft
    if draft is None:
        raise ValueError("确认方案前需要行程框架")
    if draft.planning_authorized:
        return {"minimum_delivery_draft": draft, "run_deadline": state.run_deadline or build_run_deadline_snapshot(draft), "run_budget": state.run_budget or build_run_budget_snapshot()}
    previous_deadline = state.run_deadline
    authorization = (
        previous_deadline.planning_authorized_at
        if previous_deadline is not None
        else authorized_at or utc_now()
    )
    if authorization.tzinfo is None:
        raise ValueError("确认时间必须带时区")
    authorization = authorization.astimezone(timezone.utc)
    anchors = [*draft.user_input_anchors, UserInputAnchor(anchor_id=f"authorization_{draft.draft_id}", field_path="planning_authorization", value=authorization.isoformat(), input_kind="planning_authorization")]
    payload = draft.model_dump(mode="json")
    payload.update(planning_authorized=True, planning_authorized_at=authorization.isoformat(), user_input_anchors=[item.model_dump(mode="json") for item in anchors])
    payload.pop("content_hash")
    sealed = MinimumDeliveryDraft.model_validate({**payload, "content_hash": _canonical_hash(payload)})
    deadline = (
        previous_deadline.model_copy(update={"draft_id": sealed.draft_id})
        if previous_deadline is not None
        else build_run_deadline_snapshot(sealed)
    )
    return {"minimum_delivery_draft": sealed, "run_deadline": deadline, "run_budget": state.run_budget or build_run_budget_snapshot()}
