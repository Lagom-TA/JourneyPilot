"""数据库行值与 JSON 列值的转换。"""

from __future__ import annotations

from travel_agent.runtime.time import iso_or_none
from typing import Any
from typing import Dict
from typing import Mapping
import json


def iso_or_empty(value: Any) -> str:
    """同上，但空值 → 空串。给那些字段不可为 None 的领域对象。"""

    return iso_or_none(value) or ""


def json_dumps(value: Any, *, compact: bool = False) -> str:
    """写进 jsonb 列的负载。

    ``default=str``：payload 里带 datetime / Decimal 是常态，少了它那次写入抛
    TypeError，而调用方看到的是「这条命令没落库」。
    """

    separators = (",", ":") if compact else None
    return json.dumps(
        value if value is not None else {},
        ensure_ascii=False,
        default=str,
        separators=separators,
    )


def json_object(value: Any) -> Dict[str, Any]:
    """读回来的 jsonb → dict。不是映射就给空 dict，不让调用方判类型。"""

    return dict(value) if isinstance(value, Mapping) else {}
