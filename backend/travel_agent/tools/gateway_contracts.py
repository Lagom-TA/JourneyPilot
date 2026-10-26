"""Tool Gateway 的合同类型。"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from travel_agent.runtime.time import utc_now_iso
from typing import Any
from typing import Dict
from typing import Optional
import uuid


def generate_tool_audit_id() -> str:
    return f"tool_{uuid.uuid4().hex[:12]}"


class ToolPermissionClass(str, Enum):
    READ_ONLY = "read_only"
    EXTERNAL_READ = "external_read"
    USER_DATA_READ = "user_data_read"
    WRITE = "write"
    TRANSACTIONAL = "transactional"
    ADMIN = "admin"


class ToolOperationSensitivity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    IRREVERSIBLE = "irreversible"


class ToolGatewayDecision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    NOT_APPLICABLE = "not_applicable"
    REFERENCE_ONLY = "reference_only"

    DEGRADE = "degrade"
    QUARANTINE_RESULT = "quarantine_result"


class ToolResultTrustPolicy(str, Enum):
    TRUSTED_SUMMARY = "trusted_summary"
    UNTRUSTED_SUMMARY = "untrusted_summary"
    QUARANTINE = "quarantine"


class ToolAuthBoundary(str, Enum):
    NONE = "none"
    SERVER_MANAGED = "server_managed"
    USER_OAUTH_REQUIRED = "user_oauth_required"
    PROVIDER_OAUTH_REQUIRED = "provider_oauth_required"
    FUTURE = "future"


class _StrictBoundaryModel(BaseModel):
    """API 与工具边界的 DTO：拒绝未知字段，不冻结。"""

    model_config = ConfigDict(extra="forbid")


class ToolManifest(_StrictBoundaryModel):
    tool_name: str
    source: str = "unknown"
    server_name: Optional[str] = None
    category: str = "other"
    permission_class: ToolPermissionClass = ToolPermissionClass.READ_ONLY
    operation_sensitivity: ToolOperationSensitivity = ToolOperationSensitivity.LOW

    auth_boundary: ToolAuthBoundary = ToolAuthBoundary.NONE
    allow_offline_fallback: bool = True
    evidence_allowed: bool = True
    side_effecting: bool = False
    irreversible: bool = False
    untrusted_content_policy: ToolResultTrustPolicy = (
        ToolResultTrustPolicy.UNTRUSTED_SUMMARY
    )
    disabled: bool = False


class ToolGatewayPolicyResult(_StrictBoundaryModel):
    decision: ToolGatewayDecision
    manifest: ToolManifest
    envelope: Optional[Dict[str, Any]] = None
    reason: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolAuditRecord(BaseModel):
    audit_id: str = Field(default_factory=generate_tool_audit_id)
    run_id: Optional[str] = None
    tool_name: str
    server_name: Optional[str] = None
    source_type: str = "tool"
    category: str = "other"
    permission_class: str = ToolPermissionClass.READ_ONLY.value
    operation_sensitivity: str = ToolOperationSensitivity.LOW.value
    status: str
    gateway_decision: str = ToolGatewayDecision.ALLOW.value
    args_digest: str
    result_digest: str = ""
    untrusted_content: bool = False
    quarantined: bool = False
    fallback_from: Optional[str] = None
    fallback_to: Optional[str] = None
    degradation_reason: Optional[str] = None
    error: Optional[str] = None
    evidence_allowed: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
