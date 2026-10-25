"""Validate preference groups and update the user's explicit selections."""

from pydantic import ValidationError

from travel_agent.memory.preference_contracts import TravelPreference
from travel_agent.memory.user_profile import UserProfileMemory


class PreferenceRejected(ValueError):
    pass


def preference_rejection(error: ValidationError) -> str:
    """把 `TravelPreference` 的拒绝理由投影成一句客户端读得懂的话。

    只取校验器自己写的那句（Pydantic 会给它加一个 ``Value error, `` 前缀），
    **不带**类型名、字段路径与 ``errors.pydantic.dev`` 链接 —— 那些是内部实现细节，
    不该整段发给客户端。
    """

    messages = [
        str(err.get("msg", "")).removeprefix("Value error, ").strip()
        for err in error.errors()
    ]
    unique = list(dict.fromkeys(m for m in messages if m))
    return "；".join(unique) or "偏好取值不合法"


async def update_travel_preferences(
    memory: UserProfileMemory, user_id: str, preferences: dict
) -> None:
    unknown = sorted(set(preferences) - set(TravelPreference.model_fields))
    if unknown:
        raise PreferenceRejected(f"不认识这几组偏好：{'、'.join(unknown)}")
    try:
        await memory.update_preferences(user_id, preferences)
    except ValidationError as exc:
        raise PreferenceRejected(preference_rejection(exc)) from exc
