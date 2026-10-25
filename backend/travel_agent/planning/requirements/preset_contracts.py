"""Planning requirements preset contracts."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field
from typing import List
from typing import Optional


PRESET_INSTRUCTIONS_MAX_CHARS = 4000


PRESET_NAME_MAX_CHARS = 60


PRESET_DESCRIPTION_MAX_CHARS = 200


PRESET_CONSTRAINT_FIELD_MAX_CHARS = 200


class PresetConstraints(BaseModel):
    """Preset 结构化约束"""

    duration: Optional[str] = Field(
        default=None, max_length=PRESET_CONSTRAINT_FIELD_MAX_CHARS
    )
    budget: Optional[str] = Field(
        default=None, max_length=PRESET_CONSTRAINT_FIELD_MAX_CHARS
    )
    pace: Optional[str] = Field(
        default=None, max_length=PRESET_CONSTRAINT_FIELD_MAX_CHARS
    )
    focus_areas: List[str] = Field(default_factory=list)
    output_style: Optional[str] = Field(
        default=None, max_length=PRESET_CONSTRAINT_FIELD_MAX_CHARS
    )


class TravelPreset(BaseModel):
    """旅行风格预设"""

    id: str
    user_id: str
    name: str = Field(max_length=PRESET_NAME_MAX_CHARS)
    description: str = Field(max_length=PRESET_DESCRIPTION_MAX_CHARS)
    icon: str = "compass"
    category: str = "custom"
    instructions: str = Field(max_length=PRESET_INSTRUCTIONS_MAX_CHARS)
    constraints: PresetConstraints = Field(default_factory=PresetConstraints)
    is_preset: bool = False
    usage_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
