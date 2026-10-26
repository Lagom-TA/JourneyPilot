"""站表快照的时效判定。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Any
from typing import Literal
from typing import Mapping
from typing import Optional


FreshnessVerdict = Literal["current", "stale", "unknown"]


FreshnessCriterion = Literal["upstream_version", "age", "unreadable"]


@dataclass(frozen=True)
class SnapshotFreshness:
    """一份快照的判定结果，以及该判定回答的是哪个问题。"""

    verdict: FreshnessVerdict
    criterion: FreshnessCriterion
    detail: str
    age_days: Optional[int] = None
    declared_version: Optional[str] = None
    upstream_version: Optional[str] = None

    @property
    def is_current(self) -> bool:
        return self.verdict == "current"


def _parse_fetched_at(value: Any) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def station_snapshot_freshness(
    metadata: Optional[Mapping[str, Any]],
    *,
    now: date,
    max_age_days: int,
    upstream_version: Optional[str] = None,
) -> SnapshotFreshness:
    """根据快照自身的元数据判断已提交站表的新鲜度。

    ``unknown`` 不等于 ``current``：侧车文件不可读或没有日期时，无法判断表格
    有多旧；治理检查在没有答案时给出最乐观的答案，比没有检查更糟。
    """

    if not isinstance(metadata, Mapping) or not metadata:
        return SnapshotFreshness(
            verdict="unknown",
            criterion="unreadable",
            detail="站表 meta 缺失或不可解析：无法判断快照年龄",
        )

    declared = str(metadata.get("station_version") or "").strip() or None
    upstream = str(upstream_version or "").strip() or None
    if declared is not None and upstream is not None:
        matched = declared == upstream
        return SnapshotFreshness(
            verdict="current" if matched else "stale",
            criterion="upstream_version",
            detail=(
                f"station_version 与上游一致（{declared}）"
                if matched
                else f"station_version 落后于上游：本地 {declared}，上游 {upstream}"
            ),
            declared_version=declared,
            upstream_version=upstream,
        )

    fetched_at = _parse_fetched_at(metadata.get("fetched_at"))
    if fetched_at is None:
        return SnapshotFreshness(
            verdict="unknown",
            criterion="unreadable",
            detail="站表 meta 没有可解析的 fetched_at：无法判断快照年龄",
            declared_version=declared,
            upstream_version=upstream,
        )

    age_days = (now - fetched_at).days
    fresh = age_days <= max_age_days
    return SnapshotFreshness(
        verdict="current" if fresh else "stale",
        criterion="age",
        detail=(
            f"抓取于 {fetched_at.isoformat()}，{age_days} 天前"
            f"（阈值 {max_age_days} 天{'，未超龄' if fresh else '，已超龄'}）"
            + (
                "；上游未发布版本号，这里判的是年龄不是一致性"
                if declared is None
                else ""
            )
        ),
        age_days=age_days,
        declared_version=declared,
        upstream_version=upstream,
    )
