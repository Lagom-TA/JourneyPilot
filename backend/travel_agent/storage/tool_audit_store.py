"""Tool Gateway 执行记录的可审计持久化。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from travel_agent.tools.gateway_contracts import ToolAuditRecord, ToolGatewayDecision, ToolManifest
from travel_agent.runtime.time import utc_now_iso
from .database import get_db_session
from travel_agent.runtime.time import iso_or_none as _iso
from travel_agent.storage.row_values import json_dumps as _json_dumps

logger = logging.getLogger(__name__)


class ToolAuditConflict(Exception):
    """同一个 audit id 已存有不同内容。"""


_SENSITIVE_KEY_RE = re.compile(
    r"(raw|prompt|message|args|arguments|result|payload|provider|chunk|token|cookie|api[_-]?key|authorization|secret|passport|id[_-]?card|payment|credit[_-]?card|phone|mobile|email|证件|身份证|护照|支付|银行卡|手机号|邮箱|密钥)",
    re.IGNORECASE,
)
_SAFE_METADATA_KEYS = {
    "activation_source",
    "auth_boundary",
    "evidence_allowed",
    "gateway_decision",
    "irreversible",
    "operation_sensitivity",
    "permission_class",
    "quarantine_result",
    "recovered_after_retry",
    "retry_attempt",
    "retry_count",
    "retry_scheduled",
    "max_attempts",
    "result_trust_policy",
    "schema_version",
    "side_effecting",
    "snapshot_cache",
    "tool_poisoning_flags",
}
_SENSITIVE_VALUE_RE = re.compile(
    r"("
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
    r"|(?:\+?\d[\d\s().-]{7,}\d)"
    r"|(?:4\d{3}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4})"
    r"|(?:passport|id card|credit card|payment|token|cookie|api key|authorization|secret)"
    r"|(?:护照|身份证|证件|支付|银行卡|手机号|邮箱|令牌|密钥|Cookie)"
    r")",
    re.IGNORECASE,
)




def _json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value




def sanitize_audit_metadata(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        text = " ".join(value.split())
        text = _SENSITIVE_VALUE_RE.sub("[redacted]", text)
        return text[:300].rstrip()
    if depth >= 4:
        return sanitize_audit_metadata(str(value), depth=depth + 1)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in _SAFE_METADATA_KEYS:
                if item is None or isinstance(item, (int, float, bool)):
                    out[key_text] = item
                elif isinstance(item, str):
                    out[key_text] = " ".join(item.split())[:300].rstrip()
                else:
                    out[key_text] = sanitize_audit_metadata(item, depth=depth + 1)
                continue
            if _SENSITIVE_KEY_RE.search(key_text):
                out[key_text] = "[redacted]"
                continue
            out[key_text] = sanitize_audit_metadata(item, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        items = list(value)[:20]
        out = [sanitize_audit_metadata(item, depth=depth + 1) for item in items]
        if len(value) > len(items):
            out.append({"truncated_count": len(value) - len(items)})
        return out
    return sanitize_audit_metadata(str(value), depth=depth + 1)


def _digest_text(value: Any) -> str:
    payload = json.dumps(value if value is not None else "", ensure_ascii=False, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _record_from_row(row: Dict[str, Any]) -> ToolAuditRecord:
    return ToolAuditRecord(
        audit_id=row["audit_id"],
        run_id=row.get("run_id"),
        tool_name=row.get("tool_name") or "",
        server_name=row.get("server_name"),
        source_type=row.get("source_type") or "tool",
        category=row.get("category") or "other",
        permission_class=row.get("permission_class") or "read_only",
        operation_sensitivity=row.get("operation_sensitivity") or "low",
        status=row.get("status") or "failed",
        gateway_decision=row.get("gateway_decision") or "allow",
        args_digest=row.get("args_digest") or "",
        result_digest=row.get("result_digest") or "",
        untrusted_content=bool(row.get("untrusted_content")),
        quarantined=bool(row.get("quarantined")),
        fallback_from=row.get("fallback_from"),
        fallback_to=row.get("fallback_to"),
        degradation_reason=row.get("degradation_reason"),
        error=row.get("error"),
        evidence_allowed=bool(row.get("evidence_allowed")),
        metadata=dict(_json_loads(row.get("metadata"), {})),
        created_at=_iso(row.get("created_at")) or utc_now_iso(),
    )


def build_audit_record_from_envelope(
    envelope: Dict[str, Any],
    *,
    manifest: ToolManifest,
    run_id: Optional[str] = None,
    gateway_decision: str | ToolGatewayDecision = ToolGatewayDecision.ALLOW,
) -> ToolAuditRecord:
    metadata = dict(envelope.get("metadata") or {})
    metadata.setdefault("schema_version", envelope.get("schema_version"))
    metadata.setdefault("auth_boundary", manifest.auth_boundary.value)
    metadata.setdefault("side_effecting", manifest.side_effecting)
    metadata.setdefault("irreversible", manifest.irreversible)
    gateway_value = gateway_decision.value if isinstance(gateway_decision, ToolGatewayDecision) else str(gateway_decision)
    quarantined = bool(metadata.get("quarantine_result") or gateway_value == ToolGatewayDecision.QUARANTINE_RESULT.value)
    return ToolAuditRecord(
        audit_id=str(envelope.get("audit_id") or ""),
        run_id=run_id,
        tool_name=str(envelope.get("tool_name") or manifest.tool_name),
        server_name=envelope.get("server_name") or manifest.server_name,
        source_type=str(envelope.get("source_type") or manifest.source),
        category=str(envelope.get("category") or manifest.category),
        permission_class=manifest.permission_class.value,
        operation_sensitivity=manifest.operation_sensitivity.value,
        status=str(envelope.get("status") or "failed"),
        gateway_decision=gateway_value,
        args_digest=str(envelope.get("args_digest") or ""),
        result_digest=_digest_text(envelope.get("result_summary") or envelope.get("sanitized_result") or ""),
        untrusted_content=bool(envelope.get("untrusted_content")),
        quarantined=quarantined,
        fallback_from=envelope.get("fallback_from"),
        fallback_to=envelope.get("fallback_to"),
        degradation_reason=str(envelope.get("degradation_reason") or "")[:300] or None,
        error=str(envelope.get("error") or "")[:300] or None,
        evidence_allowed=bool(metadata.get("evidence_allowed", manifest.evidence_allowed)) and not quarantined,
        metadata=sanitize_audit_metadata(metadata),
    )


def _audit_identity(record: ToolAuditRecord) -> Tuple[Any, ...]:
    """同 id 幂等重放时必须一致的字段。

    只比较会影响审计结论的列；延迟、重试计数与 ``created_at`` 在重放时都会变化，
    比较它们只会产生误报冲突。

    ``run_id`` 不参与比较：``tool_execution_audits.run_id`` 在父 Run 删除时置
    NULL（ON DELETE SET NULL），而成本台账的 ``run_id`` 是级联删除。父 Run 已删除
    时，已存审计行的 ``run_id`` 为空，而重放的 envelope 仍带原值，这是该表的正常
    状态，不是内容冲突。
    """
    return (
        record.tool_name,
        record.server_name,
        record.source_type,
        record.status,
        record.gateway_decision,
        record.args_digest,
        record.result_digest,
    )


def _assert_audit_idempotent(
    existing: ToolAuditRecord, incoming: ToolAuditRecord
) -> None:
    """同一个 audit id 的第二个不同 envelope 会被拒绝，不会静默丢弃。"""
    if _audit_identity(existing) != _audit_identity(incoming):
        logger.error(
            "tool audit id conflict: audit_id=%s existing_status=%s incoming_status=%s",
            incoming.audit_id,
            existing.status,
            incoming.status,
        )
        raise ToolAuditConflict(
            f"Tool audit id {incoming.audit_id!r} already stored with different content"
        )


class ToolAuditStore:
    """PostgreSQL 工具审计仓储。"""

    async def record_envelope(
        self,
        envelope: Dict[str, Any],
        *,
        manifest: ToolManifest,
        run_id: Optional[str] = None,
        gateway_decision: str | ToolGatewayDecision = ToolGatewayDecision.ALLOW,
    ) -> ToolAuditRecord:
        record = build_audit_record_from_envelope(
            envelope,
            manifest=manifest,
            run_id=run_id,
            gateway_decision=gateway_decision,
        )
        async with get_db_session() as session:
            result = await session.execute(
                text("SELECT * FROM tool_execution_audits WHERE audit_id = :audit_id"),
                {"audit_id": record.audit_id},
            )
            row = result.mappings().first()
            if row:
                existing = _record_from_row(dict(row))
                _assert_audit_idempotent(existing, record)
                return existing
            await session.execute(
                text(
                    """
                    INSERT INTO tool_execution_audits
                        (audit_id, run_id, tool_name, server_name, source_type,
                         category, permission_class, operation_sensitivity, status,
                         gateway_decision, args_digest, result_digest, untrusted_content,
                         quarantined, fallback_from, fallback_to, degradation_reason,
                         error, evidence_allowed, metadata, created_at)
                    VALUES
                        (:audit_id, :run_id, :tool_name, :server_name, :source_type,
                         :category, :permission_class, :operation_sensitivity, :status,
                         :gateway_decision, :args_digest, :result_digest, :untrusted_content,
                         :quarantined, :fallback_from, :fallback_to, :degradation_reason,
                         :error, :evidence_allowed, CAST(:metadata AS jsonb), NOW())
                    """
                ),
                {
                    "audit_id": record.audit_id,
                    "run_id": record.run_id,
                    "tool_name": record.tool_name,
                    "server_name": record.server_name,
                    "source_type": record.source_type,
                    "category": record.category,
                    "permission_class": record.permission_class,
                    "operation_sensitivity": record.operation_sensitivity,
                    "status": record.status,
                    "gateway_decision": record.gateway_decision,
                    "args_digest": record.args_digest,
                    "result_digest": record.result_digest,
                    "untrusted_content": record.untrusted_content,
                    "quarantined": record.quarantined,
                    "fallback_from": record.fallback_from,
                    "fallback_to": record.fallback_to,
                    "degradation_reason": record.degradation_reason,
                    "error": record.error,
                    "evidence_allowed": record.evidence_allowed,
                    "metadata": _json_dumps(record.metadata),
                },
            )
        return record

    async def list_by_run(self, run_id: str, *, limit: int = 100) -> List[ToolAuditRecord]:
        async with get_db_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT *
                    FROM tool_execution_audits
                    WHERE run_id = :run_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"run_id": run_id, "limit": max(1, min(limit, 200))},
            )
            return [_record_from_row(dict(row)) for row in result.mappings().all()]


class InMemoryToolAuditStore(ToolAuditStore):
    """内存工具审计仓储，保持 audit_id 幂等语义。"""

    def __init__(self) -> None:
        self.records: Dict[str, ToolAuditRecord] = {}

    async def record_envelope(self, envelope: Dict[str, Any], **kwargs: Any) -> ToolAuditRecord:
        # 调用方漏传必需的 manifest 时立即报错。
        if "manifest" not in kwargs:
            raise KeyError("manifest")
        record = build_audit_record_from_envelope(envelope, **kwargs)
        if record.audit_id in self.records:
            existing = self.records[record.audit_id]
            _assert_audit_idempotent(existing, record)
            return existing
        record.metadata = sanitize_audit_metadata(record.metadata)
        self.records[record.audit_id] = record
        return record

    async def list_by_run(self, run_id: str, *, limit: int = 100) -> List[ToolAuditRecord]:
        records = [record for record in self.records.values() if record.run_id == run_id]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return records[: max(1, min(limit, 200))]


_tool_audit_store_singleton: Optional[ToolAuditStore] = None


def get_tool_audit_store() -> ToolAuditStore:
    global _tool_audit_store_singleton
    if _tool_audit_store_singleton is None:
        _tool_audit_store_singleton = ToolAuditStore()
    return _tool_audit_store_singleton
