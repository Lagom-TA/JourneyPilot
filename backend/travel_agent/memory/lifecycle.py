"""记忆生命周期。"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from enum import Enum
from pydantic import BaseModel
from pydantic import Field
from travel_agent.runtime.time import utc_now_iso
from typing import Any
from typing import Dict
from typing import Optional
import re
import uuid


def generate_memory_forgetting_request_id() -> str:
    return f"memdel_{uuid.uuid4().hex[:16]}"


class MemoryCategory(str, Enum):
    TRIP_PLAN = "trip_plan"
    PREFERENCE = "preference"
    CONSTRAINT = "constraint"
    FEEDBACK = "feedback"
    PORTRAIT = "portrait"
    GRAPH = "graph"
    PROFILE = "profile"
    ANCHOR = "anchor"


class MemoryDeleteScope(str, Enum):
    FACT = "fact"
    CATEGORY = "category"
    ALL_USER = "all_user"
    GRAPH_ENTITY = "graph_entity"
    GRAPH_RELATION = "graph_relation"
    SESSION_ANCHOR = "session_anchor"
    EXPIRED = "expired"


class MemoryRetentionStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"


class ForgettingAuditStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class MemoryRetentionPolicy:
    """长期记忆事实的确定性保留策略。"""

    default_ttl_days: int = 180
    category_ttl_days: Dict[str, int] = field(
        default_factory=lambda: {
            MemoryCategory.TRIP_PLAN.value: 90,
            MemoryCategory.FEEDBACK.value: 180,
            MemoryCategory.PREFERENCE.value: 365,
            MemoryCategory.CONSTRAINT.value: 365,
        }
    )
    high_importance_min: int = 8
    high_importance_ttl_days: int = 730
    session_memory_ttl_days: int = 30
    never_retain_categories: set[str] = field(default_factory=set)

    def ttl_days_for(self, category: str, importance: int) -> int:
        category_value = (category or "").strip() or "preference"
        if category_value in self.never_retain_categories:
            return 0
        ttl = self.category_ttl_days.get(category_value, self.default_ttl_days)
        if (
            category_value == MemoryCategory.CONSTRAINT.value
            and importance >= self.high_importance_min
        ):
            ttl = max(ttl, self.high_importance_ttl_days)
        return max(0, int(ttl))

    def expires_at_for(
        self,
        category: str,
        importance: int,
        *,
        created_at: Optional[datetime] = None,
    ) -> Optional[datetime]:
        ttl_days = self.ttl_days_for(category, importance)
        if ttl_days <= 0:
            return created_at or datetime.now(timezone.utc)
        base = created_at or datetime.now(timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        return base + timedelta(days=ttl_days)

    def to_metadata(self, category: str, importance: int) -> Dict[str, Any]:
        return {
            "policy_version": "memory_retention_policy_v1",
            "category": category,
            "ttl_days": self.ttl_days_for(category, importance),
            "importance": importance,
            "high_importance_min": self.high_importance_min,
        }


class MemoryDeletionSummary(BaseModel):
    request_id: str = Field(default_factory=generate_memory_forgetting_request_id)
    user_id: str
    scope: MemoryDeleteScope
    category: Optional[str] = None
    fact_id: Optional[str] = None
    status: ForgettingAuditStatus = ForgettingAuditStatus.COMPLETED
    affected_facts: int = 0
    affected_entities: int = 0
    affected_relations: int = 0
    affected_profiles: int = 0
    affected_session_anchors: int = 0
    boundary: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)


class ForgettingAuditRecord(MemoryDeletionSummary):
    pass


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


_SENSITIVE_KEY_RE = re.compile(
    r"(raw|content|prompt|message|evidence|payload|provider|chunk|token|cookie|api[_-]?key|authorization|secret|passport|id[_-]?card|payment|credit[_-]?card|phone|mobile|email|证件|身份证|护照|支付|银行卡|手机号|邮箱|密钥)",
    re.IGNORECASE,
)


def sanitize_forgetting_metadata(value: Any, *, depth: int = 0) -> Any:
    """返回脱敏 JSON，不包含原始记忆内容或敏感值。"""

    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        text = " ".join(value.split())
        text = _SENSITIVE_VALUE_RE.sub("[redacted]", text)
        return text[:240].rstrip()
    if depth >= 4:
        return sanitize_forgetting_metadata(str(value), depth=depth + 1)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY_RE.search(key_text):
                out[key_text] = "[redacted]"
                continue
            out[key_text] = sanitize_forgetting_metadata(item, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        items = list(value)[:20]
        out = [sanitize_forgetting_metadata(item, depth=depth + 1) for item in items]
        if len(value) > len(items):
            out.append({"truncated_count": len(value) - len(items)})
        return out
    return sanitize_forgetting_metadata(str(value), depth=depth + 1)


def default_forgetting_boundary(
    *,
    physical_delete: bool = True,
    auto_portrait_cleared: bool = False,
    graph_cleared: bool = False,
    session_anchor_cleared: bool = False,
) -> Dict[str, Any]:
    """记录本次删除实际涉及的边界，写入 ``memory_forgetting_audits.boundary``。

    这些字段供合规审计、用户导出与事后追查阅读，没有代码按键取值，因此字段名必须
    准确描述实际清理的内容。

    ``auto_portrait_cleared`` 仅表示 ``auto_portrait`` 被清空；六组手填偏好与
    常用出发地不受影响，profile 行仍然存在。
    """
    return {
        "physical_delete": physical_delete,
        "long_term_memory_deleted": physical_delete,
        "auto_portrait_cleared": auto_portrait_cleared,
        "graph_cleared": graph_cleared,
        "session_anchor_cleared": session_anchor_cleared,
        "langgraph_checkpoint_replay_erased": False,
        "third_party_provider_delete": False,
        "memory_content_stored_in_audit": False,
        "background_scheduler_enabled": False,
    }
