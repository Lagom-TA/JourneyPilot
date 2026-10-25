from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from pydantic import BaseModel
from pydantic import Field


class ToolAuditRecordResponse(BaseModel):
    audit_id: str
    run_id: Optional[str] = None
    tool_name: str
    server_name: Optional[str] = None
    source_type: str = "tool"
    category: str = "other"
    permission_class: str = "read_only"
    operation_sensitivity: str = "low"
    status: str
    gateway_decision: str
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
    created_at: str


class ToolAuditListResponse(BaseModel):
    run_id: str
    audits: List[ToolAuditRecordResponse] = Field(default_factory=list)
    total: int = 0
