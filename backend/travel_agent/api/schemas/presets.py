from __future__ import annotations

from typing import Optional
from pydantic import BaseModel
from pydantic import Field
from travel_agent.planning.requirements.preset_contracts import (
    PRESET_DESCRIPTION_MAX_CHARS,
)
from travel_agent.planning.requirements.preset_contracts import (
    PRESET_INSTRUCTIONS_MAX_CHARS,
)
from travel_agent.planning.requirements.preset_contracts import PRESET_NAME_MAX_CHARS
from travel_agent.planning.requirements.preset_contracts import PresetConstraints


class PresetCreateRequest(BaseModel):
    name: str = Field(max_length=PRESET_NAME_MAX_CHARS)
    description: str = Field(max_length=PRESET_DESCRIPTION_MAX_CHARS)
    icon: str = "compass"
    category: str = "custom"
    instructions: str = Field(max_length=PRESET_INSTRUCTIONS_MAX_CHARS)
    constraints: PresetConstraints = Field(default_factory=PresetConstraints)


class PresetUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=PRESET_NAME_MAX_CHARS)
    description: Optional[str] = Field(
        default=None, max_length=PRESET_DESCRIPTION_MAX_CHARS
    )
    icon: Optional[str] = None
    category: Optional[str] = None
    instructions: Optional[str] = Field(
        default=None, max_length=PRESET_INSTRUCTIONS_MAX_CHARS
    )
    constraints: Optional[PresetConstraints] = None


class PresetResponse(BaseModel):
    id: str
    name: str = Field(max_length=PRESET_NAME_MAX_CHARS)
    description: str = Field(max_length=PRESET_DESCRIPTION_MAX_CHARS)
    icon: str
    category: str
    instructions: str = Field(max_length=PRESET_INSTRUCTIONS_MAX_CHARS)
    constraints: PresetConstraints
    is_preset: bool
    usage_count: int
    created_at: str
    updated_at: str


class GenerateInstructionsRequest(BaseModel):
    description: str
