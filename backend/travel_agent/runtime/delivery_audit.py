"""Runtime delivery_audit."""

from __future__ import annotations

from typing import Any
from typing import Dict


def _as_mapping(value: Any) -> Dict[str, Any]:
    """Return a JSON-safe mapping from a Pydantic object or mapping."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return dict(value) if isinstance(value, dict) else {}


def audit_has_durable_bundle(completion_audit: Any) -> bool:
    """审计摘要里是否真的有一份已交付的 Bundle。

    判据与写它的那段（`formal_delivery` 上面那几行）放在一起：读的一方在别的模块里
    按字符串键自己拼一遍时，一次改名就让每个已完成的 deep run 都被判成没交付 ——
    而恢复扫描会照着那个结论把它们标成不可恢复。
    """

    delivery = _as_mapping(_as_mapping(completion_audit).get("formal_delivery"))
    return bool(delivery.get("has_bundle")) and bool(delivery.get("bundle_id"))
