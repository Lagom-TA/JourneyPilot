"""Provider 数据环境（生产/沙箱）的识别。"""

from __future__ import annotations

from typing import Any
from typing import Literal
from typing import Mapping
from typing import Optional


DataEnvironment = Literal["production", "sandbox"]


SANDBOX_EVIDENCE_NOTE = (
    "本方案中部分交通班次的依据来自供应商的开发（沙箱）环境，"
    "班次、时刻与价格仅供规划参考，不可直接预订。"
)


_VALID: frozenset[str] = frozenset({"production", "sandbox"})


_ALWAYS_PRODUCTION_PROVIDERS = frozenset(
    {
        "transitous",
        "nominatim",
        "amap",
        "12306",
        "open-meteo",
    }
)


def snapshot_data_environment(
    snapshot: Optional[Mapping[str, Any]],
    *,
    provider_name: str,
) -> DataEnvironment:
    """从一份 Provider 快照中读取数据环境。

    ``snapshot`` 是 ``SourceRecord.snapshot``，有两种形状：经过快照缓存时是清洗后的
    Provider 载荷，否则是包在 ``sanitized_result`` 里的 Tool Envelope。这里两种
    都读取，使缓存命中与实时调用不会对同一响应的环境得出不同结论。

    Provider 声明了环境就采用；没有测试环境的 Provider 按身份视为生产。其他情况
    抛错：有沙箱的供应商返回未标注环境的响应，正是该字段要处理的情况，猜测为
    「生产」会掩盖问题。
    """

    declared = _declared(snapshot)
    if declared is not None:
        return declared
    if provider_name.strip().lower() in _ALWAYS_PRODUCTION_PROVIDERS:
        return "production"
    raise ValueError(
        f"provider {provider_name!r} did not state which data environment answered"
    )


def _declared(snapshot: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not isinstance(snapshot, Mapping):
        return None
    for payload in (snapshot, snapshot.get("sanitized_result")):
        if not isinstance(payload, Mapping):
            continue
        value = payload.get("data_environment")
        if isinstance(value, str) and value in _VALID:
            return value
    return None
