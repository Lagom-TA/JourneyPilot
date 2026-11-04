"""长期用户画像记忆（Infrastructure Layer）。

基于 PostgreSQL 持久化用户偏好与系统画像。
"""

from __future__ import annotations

import json
import logging
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text

from travel_agent.memory.preference_contracts import TravelPreference, UserProfile
from travel_agent.runtime.time import utc_now_iso
from ..storage.database import get_db_session
from ..storage.memory_lock import lock_user_memory

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

    async def get_user_profile(self, user_id: str, *, db_session: Any = None) -> Optional[UserProfile]:
        """从 PostgreSQL 获取用户画像；不存在时返回 None。"""
        async with (get_db_session() if db_session is None else nullcontext(db_session)) as session:
            result = await session.execute(
                text("SELECT * FROM user_profiles WHERE user_id = :uid"),
                {"uid": user_id},
            )
            row = result.mappings().first()
            if not row:
                return None
            return self._row_to_profile(dict(row))

    async def ensure_profile_for_write(
        self, user_id: str, *, db_session: Any = None, lock: bool = False
    ) -> UserProfile:
        """为真实写入获取画像；仅在调用方已有内容需要保存时创建。"""
        async with (get_db_session() if db_session is None else nullcontext(db_session)) as session:
            await session.execute(
                text("INSERT INTO user_profiles (user_id) VALUES (:uid) ON CONFLICT DO NOTHING"),
                {"uid": user_id},
            )
            statement = "SELECT * FROM user_profiles WHERE user_id = :uid"
            if lock:
                statement += " FOR UPDATE"
            result = await session.execute(text(statement), {"uid": user_id})
            return self._row_to_profile(dict(result.mappings().one()))

    async def get_revision(self, user_id: str) -> int:
        """返回画像版本号；延迟执行的后台任务用它固定入队时的画像版本。"""
        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT revision FROM user_profiles WHERE user_id = :uid"),
                {"uid": user_id},
            )
            return int(result.scalar() or 0)

    async def advance_memory_fence(self, user_id: str, *, db_session: Any) -> int:
        result = await db_session.execute(
            text("UPDATE user_profiles SET revision = revision + 1, updated_at = NOW() "
                 "WHERE user_id = :uid RETURNING revision"),
            {"uid": user_id},
        )
        return int(result.scalar_one())

    async def get_memory_management_history(
        self, user_id: str, *, db_session: Any = None,
    ) -> list[dict[str, Any]]:
        """读取用户对记忆的手动操作，供后续记忆总结参考。"""
        async with (get_db_session() if db_session is None else nullcontext(db_session)) as session:
            result = await session.execute(
                text("SELECT memory_management_history FROM user_profiles WHERE user_id = :uid"),
                {"uid": user_id},
            )
            history = result.scalar_one_or_none() or []
            if isinstance(history, str):
                history = json.loads(history)
            if not isinstance(history, list):
                raise ValueError("invalid memory management history")
            return history

    async def record_memory_management(
        self, user_id: str, operation: str, *, items: list[dict[str, Any]],
        db_session: Any, category: str | None = None, details: dict[str, Any] | None = None,
        reset: bool = False,
    ) -> int:
        """与手动操作在同一事务中写入时间顺序和操作内容。"""
        await self.ensure_profile_for_write(user_id, db_session=db_session, lock=True)
        revision = await self.advance_memory_fence(user_id, db_session=db_session)
        event = {
            "operation": operation,
            "revision": revision,
            "items": items,
            "created_at": utc_now_iso(),
        }
        if category is not None:
            event["category"] = category
        if details is not None:
            event["details"] = details
        expression = "CAST(:events AS jsonb)" if reset else "memory_management_history || CAST(:events AS jsonb)"
        await db_session.execute(
            text(f"UPDATE user_profiles SET memory_management_history = {expression} WHERE user_id = :uid"),
            {"uid": user_id, "events": json.dumps([event], ensure_ascii=False)},
        )
        return revision

    async def save_user_profile(self, profile: UserProfile) -> None:
        """保存或更新用户画像（upsert）。每次写入 revision 前进一格。"""
        now = datetime.now(timezone.utc).isoformat()
        profile.updated_at = now
        if not profile.created_at:
            profile.created_at = now

        async with get_db_session() as session:
            await lock_user_memory(session, profile.user_id)
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
        validated = TravelPreference(**updates)
        preferences = validated.model_dump(mode="json", include=set(updates))
        async with get_db_session() as session:
            await lock_user_memory(session, user_id)
            await session.execute(
                text("""
                    INSERT INTO user_profiles (user_id, preferences, revision)
                    VALUES (:uid, CAST(:prefs AS jsonb), 1)
                    ON CONFLICT (user_id) DO UPDATE SET
                        preferences = user_profiles.preferences || EXCLUDED.preferences,
                        revision = user_profiles.revision + 1,
                        updated_at = NOW()
                """),
                {"uid": user_id, "prefs": json.dumps(preferences, ensure_ascii=False)},
            )

    async def set_auto_portrait(
        self, user_id: str, portrait_text: str, *, db_session: Any = None
    ) -> None:
        """只更新系统画像，保留并发保存的用户偏好。"""
        async with (get_db_session() if db_session is None else nullcontext(db_session)) as session:
            await session.execute(
                text("""
                    INSERT INTO user_profiles (user_id, auto_portrait, revision)
                    VALUES (:uid, :portrait, 1)
                    ON CONFLICT (user_id) DO UPDATE SET
                        auto_portrait = EXCLUDED.auto_portrait,
                        revision = user_profiles.revision + 1,
                        updated_at = NOW()
                """),
                {"uid": user_id, "portrait": portrait_text},
            )

    async def clear_profile_memory(self, user_id: str, *, db_session: Any = None) -> int:
        """清除画像中由系统生成的部分，用户手填的偏好保持不变。

        profile 行包含两类来源不同的数据：``preferences``（六组偏好与常用出发地，
        仅由 ``api/routes/user.py`` 的两条路由写入）与 ``auto_portrait``（系统从
        对话总结）。只有 ``auto_portrait`` 属于记忆，会被遗忘流程清除。

        该方法不提供参数，避免删除记忆时连带清除用户手填偏好。
        """
        if not user_id:
            return 0
        async with (get_db_session() if db_session is None else nullcontext(db_session)) as session:
            result = await session.execute(
                text("""
                    UPDATE user_profiles
                    SET auto_portrait = '', revision = revision + 1, updated_at = NOW()
                    WHERE user_id = :uid AND auto_portrait <> ''
                    RETURNING user_id
                """),
                {"uid": user_id},
            )
            return int(result.scalar_one_or_none() is not None)

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
