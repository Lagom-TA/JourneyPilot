"""Api local identity."""

from __future__ import annotations

from travel_agent.runtime.local_identity import LOCAL_USER_ID


def get_local_user_id() -> str:
    """路由取本地身份的唯一入口（FastAPI 依赖）。"""

    return LOCAL_USER_ID
