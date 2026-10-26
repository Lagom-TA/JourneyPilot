"""长期用户画像记忆（Infrastructure Layer）。

基于 PostgreSQL 持久化用户偏好与系统画像。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text

from travel_agent.memory.preference_contracts import TravelPreference, UserProfile
from ..storage.database import get_db_session

logger = logging.getLogger(__name__)


def _bind_ts(value: Optional[str]) -> Optional[datetime]:
    """模型层时间戳是 ISO 字符串；asyncpg 的 timestamptz 参数只接受 datetime。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class UserProfileMemory:
    """用户画像持久化管理。"""

    async def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """从 PostgreSQL 获取用户画像；不存在时返回 None。"""
        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT * FROM user_profiles WHERE user_id = :uid"),
                {"uid": user_id},
            )
            row = result.mappings().first()
            if not row:
                return None
            return self._row_to_profile(dict(row))

    async def ensure_profile_for_write(self, user_id: str) -> UserProfile:
        """为真实写入获取画像；仅在调用方已有内容需要保存时创建。"""
        profile = await self.get_user_profile(user_id)
        if profile is None:
            profile = UserProfile(
                user_id=user_id,
                created_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.save_user_profile(profile)
        return profile

    async def get_revision(self, user_id: str) -> int:
        """返回画像版本号；延迟执行的后台任务用它固定入队时的画像版本。"""
        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT revision FROM user_profiles WHERE user_id = :uid"),
                {"uid": user_id},
            )
            return int(result.scalar() or 0)

    async def save_user_profile(self, profile: UserProfile) -> None:
        """保存或更新用户画像（upsert）。每次写入 revision 前进一格。"""
        now = datetime.now(timezone.utc).isoformat()
        profile.updated_at = now
        if not profile.created_at:
            profile.created_at = now

        async with get_db_session() as session:
            await session.execute(
                text("""
                    INSERT INTO user_profiles
                        (user_id, display_name, preferences, auto_portrait, revision,
                         created_at, updated_at)
                    VALUES
                        (:uid, :name, CAST(:prefs AS jsonb), :portrait, 1, :created, :updated)
                    ON CONFLICT (user_id) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        preferences = EXCLUDED.preferences,
                        auto_portrait = EXCLUDED.auto_portrait,
                        revision = user_profiles.revision + 1,
                        updated_at = EXCLUDED.updated_at
                """),
                {
                    "uid": profile.user_id,
                    "name": profile.display_name,
                    "prefs": json.dumps(profile.preferences.model_dump(), ensure_ascii=False),
                    "portrait": profile.auto_portrait,
                    "created": _bind_ts(profile.created_at) or datetime.now(timezone.utc),
                    "updated": _bind_ts(profile.updated_at) or datetime.now(timezone.utc),
                },
            )

    async def update_preferences(self, user_id: str, updates: Dict[str, Any]) -> None:
        """更新用户偏好：带上来的键整组覆盖，未带上来的键保持不变。

        因此 updates 不是完整期望状态，少带一组不会清空该组。偏好设置页每次保存
        都发送全套键。

        未更新的组保持原值；带上的列表组为覆盖而非追加。
        """
        profile = await self.ensure_profile_for_write(user_id)
        current = profile.preferences.model_dump()
        current.update(updates)
        profile.preferences = TravelPreference(**current)
        await self.save_user_profile(profile)

    async def clear_profile_memory(self, user_id: str) -> int:
        """清除画像中由系统生成的部分，用户手填的偏好保持不变。

        profile 行包含两类来源不同的数据：``preferences``（六组偏好与常用出发地，
        仅由 ``api/routes/user.py`` 的两条路由写入）与 ``auto_portrait``（系统从
        对话总结）。只有 ``auto_portrait`` 属于记忆，会被遗忘流程清除。

        该方法不提供参数，避免删除记忆时连带清除用户手填偏好。
        """
        if not user_id:
            return 0
        profile = await self.get_user_profile(user_id)
        if profile is None:
            return 0
        if not profile.auto_portrait:
            return 0
        profile.auto_portrait = ""
        await self.save_user_profile(profile)
        return 1

    # -----------------------------------------------------------------------
    # 辅助方法
    # -----------------------------------------------------------------------

    def _row_to_profile(self, row: Dict[str, Any]) -> UserProfile:
        prefs_data = row.get("preferences") or {}
        if isinstance(prefs_data, str):
            prefs_data = json.loads(prefs_data)

        return UserProfile(
            user_id=row["user_id"],
            display_name=row.get("display_name") or "",
            preferences=TravelPreference(**prefs_data),
            auto_portrait=row.get("auto_portrait") or "",
            revision=int(row.get("revision") or 0),
            created_at=str(row.get("created_at", "")),
            updated_at=str(row.get("updated_at", "")),
        )
