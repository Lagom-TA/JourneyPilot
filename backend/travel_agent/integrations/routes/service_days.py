"""线路名称中的运行日标记检查。"""

from __future__ import annotations

from datetime import date
from typing import Iterable
import re


def nominal_service_day_conflict(
    line_names: Iterable[str | None], service_date: date
) -> bool:
    """拒绝与星期明显不兼容的运行日标签，不据此推断节假日安排。

    星期匹配不能证明当天有服务：节假日与调休仍需运营方确认。存在无运行日限制的
    替代线路时，冲突标签是不足以选择该线路的证据。
    """
    weekend = service_date.weekday() >= 5
    for name in line_names:
        text = (name or "").casefold()
        if weekend and ("工作日" in text or re.search(r"\bweekdays?\b", text)):
            return True
        if (
            not weekend
            and "节假日" not in text
            and "holiday" not in text
            and (
                "双休日" in text or "周末" in text or re.search(r"\bweekends?\b", text)
            )
        ):
            return True
    return False
