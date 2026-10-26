"""地点 Provider 的失败码与观测契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from typing import Dict
from typing import Literal


PlaceProviderFailureCode = Literal[
    "provider_unavailable",
    "provider_unparseable",
    "provider_invalid_payload",
]


class NominatimPlaceSearchError(RuntimeError):
    """地点 Provider 未能返回有效响应。

    ``code`` 是必填项。三种失败在运维上需要区别处理，而路由会丢弃 message、
    换成一句本地化字符串，只靠英文 message 区分会在边界处丢失信息。判据放在
    异常上，不通过匹配 message 判断失败类型。
    """

    def __init__(self, message: str, *, code: PlaceProviderFailureCode) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NominatimSearchObservation:
    """一次 ``/search`` 回答，以及 Provider 实际生成该回答的时间。

    ``observed_at`` 是 Provider 的观测时刻，不是本进程读取它的时刻：复用缓存时，
    它是原始实时调用的时间戳。把它转成证据的调用方必须发布这个值，而不是
    ``now``；这个区别正是原始响应可复用的前提。
    """

    items: list[Dict[str, Any]]
    observed_at: datetime
    origin: Literal["live", "cache"]
