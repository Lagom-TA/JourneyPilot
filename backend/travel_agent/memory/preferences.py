"""校验偏好分组，并更新用户显式选择的偏好。"""

from pydantic import ValidationError

from travel_agent.memory.preference_contracts import TravelPreference
from travel_agent.memory.user_profile import UserProfileMemory


class PreferenceRejected(ValueError):
    pass


def preference_rejection(error: ValidationError) -> str:
    """把 `TravelPreference` 的校验失败原因转换为面向客户端的提示。

    只保留校验器写入的消息（去掉 Pydantic 的 ``Value error, `` 前缀），不包含
    类型名、字段路径或文档链接等内部实现细节。
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
