from __future__ import annotations

from datetime import datetime
from pydantic import Field
from pydantic import model_validator
from travel_agent.planning.itinerary.models import CustomBlock
from travel_agent.planning.itinerary.models import DiningStop
from travel_agent.planning.itinerary.models import LodgingStay
from travel_agent.planning.itinerary.models import StructuredItineraryV2
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.itinerary.models import VisitStop
from travel_agent.planning.transport import TransportMode
from travel_agent.planning.workspace import TripWorkspaceV2
from travel_agent.schema import StrictModel
from typing import Annotated
from typing import Literal
from typing import Optional
from typing import Union


class SelectOptionMutation(StrictModel):
    type: Literal["select_option"] = "select_option"
    selection_slot_id: str = Field(min_length=1)
    option_id: str = Field(min_length=1)


class MoveTimelineItemMutation(StrictModel):
    type: Literal["move_timeline_item"] = "move_timeline_item"
    item_id: str = Field(min_length=1)
    to_day_id: str = Field(min_length=1)
    before_entry_id: Optional[str] = Field(default=None, min_length=1)


class UpdateStopScheduleMutation(StrictModel):
    type: Literal["update_stop_schedule"] = "update_stop_schedule"
    item_id: str = Field(min_length=1)
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_change(self) -> "UpdateStopScheduleMutation":
        if not (
            {"planned_start", "planned_end", "duration_minutes"} & self.model_fields_set
        ):
            raise ValueError("schedule mutation requires at least one changed field")
        return self


class CreateCustomBlockMutation(StrictModel):
    type: Literal["create_custom_block"] = "create_custom_block"
    block: CustomBlock
    before_entry_id: Optional[str] = Field(default=None, min_length=1)


class UpdateCustomBlockMutation(StrictModel):
    type: Literal["update_custom_block"] = "update_custom_block"
    item_id: str = Field(min_length=1)
    title: Optional[str] = Field(default=None, min_length=1)
    note: Optional[str] = None
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_change(self) -> "UpdateCustomBlockMutation":
        if not (
            {"title", "note", "planned_start", "planned_end", "duration_minutes"}
            & self.model_fields_set
        ):
            raise ValueError(
                "custom block mutation requires at least one changed field"
            )
        return self


class DeleteCustomBlockMutation(StrictModel):
    type: Literal["delete_custom_block"] = "delete_custom_block"
    item_id: str = Field(min_length=1)


class DeleteTransportLegMutation(StrictModel):
    type: Literal["delete_transport_leg"] = "delete_transport_leg"
    transport_leg_id: str = Field(min_length=1)


class SetTransportModeMutation(StrictModel):
    type: Literal["set_transport_mode"] = "set_transport_mode"
    transport_leg_id: str = Field(min_length=1)
    selected_mode: TransportMode
    lock_mode: bool = True


class UpdateTransportModePreferenceMutation(StrictModel):
    type: Literal["update_transport_mode_preference"] = (
        "update_transport_mode_preference"
    )
    locked_mode: Optional[TransportMode] = None
    excluded_modes: Optional[list[TransportMode]] = None
    transport_leg_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_change(self) -> "UpdateTransportModePreferenceMutation":
        if not ({"locked_mode", "excluded_modes"} & self.model_fields_set):
            raise ValueError("transport preference mutation requires a changed field")
        return self


class DeleteLodgingStayMutation(StrictModel):
    type: Literal["delete_lodging_stay"] = "delete_lodging_stay"
    stay_id: str = Field(min_length=1)


class ApplyWeatherAdjustmentMutation(StrictModel):
    type: Literal["apply_weather_adjustment"] = "apply_weather_adjustment"
    proposal_id: str = Field(min_length=1)


class DismissWeatherAdjustmentMutation(StrictModel):
    type: Literal["dismiss_weather_adjustment"] = "dismiss_weather_adjustment"
    proposal_id: str = Field(min_length=1)


WorkspaceV2Mutation = Annotated[
    Union[
        SelectOptionMutation,
        MoveTimelineItemMutation,
        UpdateStopScheduleMutation,
        CreateCustomBlockMutation,
        UpdateCustomBlockMutation,
        DeleteCustomBlockMutation,
        DeleteTransportLegMutation,
        SetTransportModeMutation,
        UpdateTransportModePreferenceMutation,
        DeleteLodgingStayMutation,
        ApplyWeatherAdjustmentMutation,
        DismissWeatherAdjustmentMutation,
    ],
    Field(discriminator="type"),
]


SelectableEntity = Annotated[
    Union[DiningStop, LodgingStay, VisitStop, TransportLeg], Field(discriminator="type")
]


class SelectionInversePatch(StrictModel):
    type: Literal["selection"] = "selection"
    selection_slot_id: str = Field(min_length=1)
    applied_option_id: str = Field(min_length=1)
    applied_workspace_revision: int = Field(ge=1)
    previous_selected_option_id: Optional[str] = Field(default=None, min_length=1)
    previous_slot_status: Literal[
        "researching", "ready", "refreshing", "needs_user_decision"
    ]
    previous_entity: SelectableEntity


class ItineraryInversePatch(StrictModel):
    type: Literal["itinerary"] = "itinerary"
    applied_workspace_revision: int = Field(ge=1)
    previous_itinerary: StructuredItineraryV2


class WorkspaceSnapshotInversePatch(StrictModel):
    """撤销与恢复提交使用的强类型语义逆操作。

    快照只表示用户拥有的 workspace 状态；事实与天气快照不属于本补丁，应用
    逆操作时始终取自当前 Delivery Bundle。
    """

    type: Literal["workspace_snapshot"] = "workspace_snapshot"
    applied_workspace_revision: int = Field(ge=1)
    previous_workspace: TripWorkspaceV2


WorkspaceV2InversePatch = Annotated[
    Union[SelectionInversePatch, ItineraryInversePatch, WorkspaceSnapshotInversePatch],
    Field(discriminator="type"),
]


class WorkspaceV2MutationApplication(StrictModel):
    workspace: TripWorkspaceV2
    changed: bool
    label: Optional[str] = None
    inverse: Optional[WorkspaceV2InversePatch] = None


class WorkspaceV2MutationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
