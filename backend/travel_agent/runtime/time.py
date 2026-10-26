"""运行时的 UTC 时间格式化。"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_or_none(value: Any) -> Optional[str]:
    """行里的时间戳 → ISO 字符串。空值（含空串）→ None。"""

    if value is None:
        return None
    if isinstance(value, datetime):
        moment = (
            value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        )
        return moment.isoformat()
    text = str(value).strip()
    return text or None
