"""
Preset API 路由 (Serving Layer)
用户自定义旅行风格预设的 CRUD 和 AI 辅助生成。
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, HTTPException

from travel_agent.runtime.local_identity import LOCAL_USER_ID
from travel_agent.storage.preset_store import PresetStore
from travel_agent.conversation.preset_instructions import generate_preset_instructions
from ..schemas import (
    GenerateInstructionsRequest,
    PresetCreateRequest,
    PresetResponse,
    PresetUpdateRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/presets", tags=["presets"])

_store = PresetStore()


def _preset_to_response(preset) -> PresetResponse:
    return PresetResponse(
        id=preset.id,
        name=preset.name,
        description=preset.description,
        icon=preset.icon,
        category=preset.category,
        instructions=preset.instructions,
        constraints=preset.constraints,
        is_preset=preset.is_preset,
        usage_count=preset.usage_count,
        created_at=preset.created_at or "",
        updated_at=preset.updated_at or "",
    )


@router.get("", response_model=List[PresetResponse])
async def list_presets():
    """获取用户所有预设（含系统内置）"""
    try:
        presets = await _store.list_presets(LOCAL_USER_ID)
        return [_preset_to_response(p) for p in presets]
    except Exception as e:
        logger.error(f"获取预设列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{preset_id}", response_model=PresetResponse)
async def get_preset(preset_id: str):
    """获取单个预设"""
    preset = await _store.get_preset(preset_id, user_id=LOCAL_USER_ID)
    if not preset:
        raise HTTPException(status_code=404, detail="预设不存在")
    return _preset_to_response(preset)


@router.post("", response_model=PresetResponse)
async def create_preset(request: PresetCreateRequest):
    """创建新预设"""
    try:
        preset = await _store.create_preset(
            user_id=LOCAL_USER_ID,
            data=request.model_dump(),
        )
        return _preset_to_response(preset)
    except Exception as e:
        logger.error(f"创建预设失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{preset_id}", response_model=PresetResponse)
async def update_preset(preset_id: str, request: PresetUpdateRequest):
    """更新预设"""
    try:
        data = {k: v for k, v in request.model_dump().items() if v is not None}
        preset = await _store.update_preset(preset_id, LOCAL_USER_ID, data)
        if not preset:
            raise HTTPException(status_code=404, detail="预设不存在")
        return _preset_to_response(preset)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新预设失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{preset_id}")
async def delete_preset(preset_id: str):
    """删除预设"""
    try:
        deleted = await _store.delete_preset(preset_id, LOCAL_USER_ID)
        if not deleted:
            raise HTTPException(status_code=404, detail="预设不存在")
        return {"status": "ok", "message": "预设已删除"}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除预设失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-instructions")
async def generate_instructions(request: GenerateInstructionsRequest):
    """AI 辅助生成预设指令"""
    if len(request.description.strip()) < 5:
        raise HTTPException(status_code=400, detail="描述太短，请提供更详细的信息")
    try:
        return await generate_preset_instructions(request.description)
    except Exception as e:
        logger.error(f"AI 生成预设指令失败: {e}", exc_info=True)
        return {
            "success": False,
            "data": None,
            "error_message": "生成失败，请稍后重试或手动编写指令",
        }
