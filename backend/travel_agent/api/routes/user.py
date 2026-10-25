"""
用户配置 API (Serving Layer)
管理用户画像和偏好。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from travel_agent.memory.preferences import PreferenceRejected, update_travel_preferences

from travel_agent.bootstrap.registry import get_components
from travel_agent.memory.preference_contracts import TRAVEL_PREFERENCE_GROUPS, PreferenceOptionGroup, TravelPreference
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from travel_agent.api.schemas.sessions import ChatSessionDetail, ChatSessionSummary, UpdateSessionRequest
from travel_agent.api.schemas.profile import DefaultOriginRequest, DefaultOriginResponse, UpdatePreferencesRequest, UserProfileResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/user", tags=["user"])


@router.get("/preference-options", response_model=list[PreferenceOptionGroup])
async def get_preference_options() -> list[PreferenceOptionGroup]:
    """六组偏好各有哪些可选项 —— 界面画 chip 用的那张表。

    **这条路由存在的理由就是「那张表只许有一份」。** 表放在后端，因为取值原文要进模型
    （``panels/constraint.py``）。

    **不走数据库、也不进 ``product_configurations``**：这不是可以被运营改的产品配置，
    是 ``TravelPreference`` 自己的合同 —— 它的值决定模型读到什么。让它经过一张表只会
    给一件恒定的东西加一个 503（``/api/product/trip-planner`` 那条是 DB 支撑的，
    别把两者混成一副语法）。
    """

    return list(TRAVEL_PREFERENCE_GROUPS)


@router.get("/default-origin", response_model=DefaultOriginResponse)
async def get_default_origin():
    components = get_components()
    profile = await components.user_profile_memory.get_user_profile(LOCAL_USER_ID)
    return DefaultOriginResponse(
        place=profile.preferences.default_origin if profile else None,
    )


@router.put("/default-origin", response_model=DefaultOriginResponse)
async def set_default_origin(request: DefaultOriginRequest):
    from travel_agent.planning.requirements.identity_contracts import ORIGIN_PLACE_KINDS

    if request.place.kind not in ORIGIN_PLACE_KINDS:
        raise HTTPException(status_code=422, detail="常用出发地只支持城市、机场或火车站")
    components = get_components()
    await components.user_profile_memory.update_preferences(
        LOCAL_USER_ID, {"default_origin": request.place.model_dump(mode="json")}
    )
    return DefaultOriginResponse(place=request.place)


@router.get("/profile", response_model=UserProfileResponse)
async def get_user_profile():
    """获取用户画像"""
    components = get_components()
    try:
        profile = await components.user_profile_memory.get_user_profile(LOCAL_USER_ID)
        if profile is None:
            return UserProfileResponse(
                display_name="",
                preferences=TravelPreference().model_dump(),
            )
        return UserProfileResponse(
            display_name=profile.display_name,
            preferences=profile.preferences.model_dump(),
        )
    except Exception as e:
        logger.error(f"获取用户画像失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.patch("/preferences")
async def update_preferences(request: UpdatePreferencesRequest):
    """更新用户偏好（设置页显式编辑：带上来的每一组都按覆盖处理，取消勾选才能真正移除）"""
    components = get_components()
    try:
        await update_travel_preferences(components.user_profile_memory, LOCAL_USER_ID, request.preferences)
        return {"status": "success", "message": "用户偏好已更新"}
    except HTTPException:
        raise
    except PreferenceRejected as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.error(f"更新用户偏好失败: {e}")
        raise HTTPException(status_code=500, detail="保存偏好失败，请稍后重试")


@router.get("/sessions", response_model=list[ChatSessionSummary])
async def list_user_sessions():
    """获取用户会话摘要列表（按 updated_at 倒序）。"""
    components = get_components()
    try:
        return await components.chat_session_memory.list_sessions(LOCAL_USER_ID)
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_user_session_detail(session_id: str):
    """获取单个会话详情（含消息回放与澄清状态）。"""
    components = get_components()
    try:
        detail = await components.chat_session_memory.get_session_detail(LOCAL_USER_ID, session_id)
        if not detail:
            raise HTTPException(status_code=404, detail="会话不存在")
        return detail
    except PermissionError:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/sessions/{session_id}", response_model=ChatSessionSummary)
async def update_user_session(session_id: str, request: UpdateSessionRequest):
    """重命名会话标题，返回更新后的摘要。"""
    components = get_components()
    try:
        updated = await components.chat_session_memory.update_session_title(
            LOCAL_USER_ID, session_id, request.title
        )
        if not updated:
            raise HTTPException(status_code=404, detail="会话不存在")
        return updated
    except PermissionError:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重命名会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
async def delete_user_session(session_id: str):
    """删除指定会话（硬删除，级联事件）。"""
    components = get_components()
    try:
        deleted = await components.chat_session_memory.delete_session(LOCAL_USER_ID, session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"status": "success", "message": f"会话 [{session_id}] 已删除"}
    except PermissionError:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
