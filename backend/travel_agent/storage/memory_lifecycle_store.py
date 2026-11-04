"""记忆删除流程的编排与审计持久化。"""

from __future__ import annotations

import json
from contextlib import nullcontext
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from travel_agent.memory.lifecycle import ForgettingAuditRecord, ForgettingAuditStatus, MemoryDeleteScope, MemoryDeletionSummary, default_forgetting_boundary, generate_memory_forgetting_request_id, sanitize_forgetting_metadata
from travel_agent.runtime.time import utc_now_iso
from ..memory.chat_session import ChatSessionMemory
from ..memory.memory_graph import MemoryGraph
from ..memory.memory_store import MemoryStore
from ..memory.user_profile import UserProfileMemory
from .database import get_db_session
from .background_job_store import BackgroundJobStore
from .memory_lock import lock_user_memory
from .row_values import iso_or_empty as _iso, json_dumps as _json_dumps




def _json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value




def _record_from_row(row: Dict[str, Any]) -> ForgettingAuditRecord:
    return ForgettingAuditRecord(
        request_id=row["request_id"],
        user_id=row.get("user_id") or "",
        scope=MemoryDeleteScope(row.get("scope") or MemoryDeleteScope.ALL_USER.value),
        category=row.get("category"),
        fact_id=row.get("fact_id"),
        status=ForgettingAuditStatus(row.get("status") or ForgettingAuditStatus.COMPLETED.value),
        affected_facts=int(row.get("affected_facts") or 0),
        affected_entities=int(row.get("affected_entities") or 0),
        affected_relations=int(row.get("affected_relations") or 0),
        affected_profiles=int(row.get("affected_profiles") or 0),
        affected_session_anchors=int(row.get("affected_session_anchors") or 0),
        boundary=dict(_json_loads(row.get("boundary"), {})),
        metadata=dict(_json_loads(row.get("metadata"), {})),
        created_at=_iso(row.get("created_at")) or utc_now_iso(),
    )


class MemoryLifecycleStore:
    """PostgreSQL 后端的记忆生命周期服务。"""

    def __init__(
        self,
        *,
        memory_store: Optional[MemoryStore] = None,
        memory_graph: Optional[MemoryGraph] = None,
        user_profile_memory: Optional[UserProfileMemory] = None,
        chat_session_memory: Optional[ChatSessionMemory] = None,
    ) -> None:
        self.memory_store = memory_store or MemoryStore()
        self.memory_graph = memory_graph or MemoryGraph()
        self.user_profile_memory = user_profile_memory or UserProfileMemory()
        self.chat_session_memory = chat_session_memory or ChatSessionMemory()

    async def delete_one_fact(
        self,
        *,
        user_id: str,
        fact_id: str,
        request_id: Optional[str] = None,
        reason: str = "",
    ) -> MemoryDeletionSummary:
        summary = MemoryDeletionSummary(
            request_id=request_id or generate_memory_forgetting_request_id(),
            user_id=user_id,
            scope=MemoryDeleteScope.FACT,
            fact_id=str(fact_id),
            affected_facts=await self.memory_store.delete_fact(user_id, fact_id),
            boundary=default_forgetting_boundary(),
            metadata=sanitize_forgetting_metadata({"reason": reason, "fact_id": str(fact_id)}),
        )
        await self.record_audit(summary)
        return summary

    async def _clear_system_learned_memory(
        self,
        user_id: str,
        *,
        clear_auto_portrait: bool,
        clear_graph: bool,
        clear_session_anchors: bool,
        db_session: Any = None,
    ) -> Dict[str, int]:
        """清除系统自动学习的数据，用户手填的偏好不动。

        「一次删除只处理它声明的范围」这一规则只在这里实现，按类别与全部两个
        删除入口共用。

        六组偏好与常用出发地（``default_origin``）存放在同一个
        ``TravelPreference`` 上，由用户在「我的偏好」界面填写，写入方只有
        ``api/routes/user.py`` 的两条路由，遗忘流程不修改它们。这里只决定
        是否清除画像。
        """
        counts = {"entities": 0, "relations": 0, "profiles": 0, "anchors": 0}
        if clear_graph:
            graph_counts = await self.memory_graph.delete_user_graph(user_id, db_session=db_session)
            counts["entities"] = int(graph_counts.get("entities", 0))
            counts["relations"] = int(graph_counts.get("relations", 0))
        if clear_auto_portrait:
            counts["profiles"] = await self.user_profile_memory.clear_profile_memory(
                user_id, db_session=db_session
            )
        if clear_session_anchors:
            counts["anchors"] = await self.chat_session_memory.clear_user_anchors(user_id, db_session=db_session)
        return counts

    async def delete_by_category(
        self,
        *,
        user_id: str,
        category: str,
        request_id: Optional[str] = None,
        reason: str = "",
        clear_auto_portrait: bool = False,
        clear_graph: bool = False,
        clear_session_anchors: bool = False,
    ) -> MemoryDeletionSummary:
        affected_facts = await self.memory_store.delete_by_category(user_id, category)
        cleared = await self._clear_system_learned_memory(
            user_id,
            clear_auto_portrait=clear_auto_portrait,
            clear_graph=clear_graph,
            clear_session_anchors=clear_session_anchors,
        )

        summary = MemoryDeletionSummary(
            request_id=request_id or generate_memory_forgetting_request_id(),
            user_id=user_id,
            scope=MemoryDeleteScope.CATEGORY,
            category=category,
            affected_facts=affected_facts,
            affected_entities=cleared["entities"],
            affected_relations=cleared["relations"],
            affected_profiles=cleared["profiles"],
            affected_session_anchors=cleared["anchors"],
            boundary=default_forgetting_boundary(
                auto_portrait_cleared=clear_auto_portrait,
                graph_cleared=clear_graph,
                session_anchor_cleared=clear_session_anchors,
            ),
            metadata=sanitize_forgetting_metadata({
                "reason": reason,
                "category": category,
                "clear_auto_portrait": clear_auto_portrait,
                "clear_graph": clear_graph,
                "clear_session_anchors": clear_session_anchors,
            }),
        )
        await self.record_audit(summary)
        return summary

    async def delete_all_user_memory(
        self,
        *,
        user_id: str,
        request_id: Optional[str] = None,
        reason: str = "",
        clear_auto_portrait: bool = True,
        clear_graph: bool = True,
        clear_session_anchors: bool = True,
    ) -> MemoryDeletionSummary:
        if not user_id:
            raise ValueError("user_id is required")
        async with get_db_session() as session:
            await lock_user_memory(session, user_id)
            # 抽取写入先锁任务再锁画像；删除保持相同顺序。
            await BackgroundJobStore().cancel_memory_extractions(user_id, db_session=session)
            await self.user_profile_memory.ensure_profile_for_write(user_id, db_session=session, lock=True)
            affected_facts = await self.memory_store.delete_all_user_facts(user_id, db_session=session)
            cleared = await self._clear_system_learned_memory(
                user_id,
                clear_auto_portrait=clear_auto_portrait,
                clear_graph=clear_graph,
                clear_session_anchors=clear_session_anchors,
                db_session=session,
            )
            fence_revision = await self.user_profile_memory.advance_memory_fence(user_id, db_session=session)
            summary = MemoryDeletionSummary(
                request_id=request_id or generate_memory_forgetting_request_id(),
                user_id=user_id,
                scope=MemoryDeleteScope.ALL_USER,
                affected_facts=affected_facts,
                affected_entities=cleared["entities"],
                affected_relations=cleared["relations"],
                affected_profiles=cleared["profiles"],
                affected_session_anchors=cleared["anchors"],
                boundary=default_forgetting_boundary(
                    auto_portrait_cleared=clear_auto_portrait,
                    graph_cleared=clear_graph,
                    session_anchor_cleared=clear_session_anchors,
                ),
                metadata=sanitize_forgetting_metadata({
                    "reason": reason,
                    "clear_auto_portrait": clear_auto_portrait,
                    "clear_graph": clear_graph,
                    "clear_session_anchors": clear_session_anchors,
                    "memory_fence_revision": fence_revision,
                }),
            )
            await self.record_audit(summary, db_session=session, require_insert=True)
            return summary

    async def delete_expired(
        self,
        *,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
        reason: str = "retention_cleanup",
        limit: int = 1000,
    ) -> MemoryDeletionSummary:
        affected_facts = await self.memory_store.delete_expired_facts(user_id, limit=limit)
        summary = MemoryDeletionSummary(
            request_id=request_id or generate_memory_forgetting_request_id(),
            user_id=user_id or "*",
            scope=MemoryDeleteScope.EXPIRED,
            affected_facts=affected_facts,
            boundary=default_forgetting_boundary(),
            metadata=sanitize_forgetting_metadata({"reason": reason, "limit": limit}),
        )
        await self.record_audit(summary)
        return summary

    async def record_audit(
        self, summary: MemoryDeletionSummary, *, db_session: Any = None, require_insert: bool = False,
    ) -> ForgettingAuditRecord:
        record = ForgettingAuditRecord(**summary.model_dump())
        record.metadata = sanitize_forgetting_metadata(record.metadata)
        async with (get_db_session() if db_session is None else nullcontext(db_session)) as session:
            result = await session.execute(
                text("""
                    INSERT INTO memory_forgetting_audits
                        (request_id, user_id, scope, category, fact_id, status,
                         affected_facts, affected_entities, affected_relations,
                         affected_profiles, affected_session_anchors, boundary,
                         metadata, created_at)
                    VALUES
                        (:request_id, :user_id, :scope, :category, :fact_id, :status,
                         :affected_facts, :affected_entities, :affected_relations,
                         :affected_profiles, :affected_session_anchors,
                         CAST(:boundary AS jsonb), CAST(:metadata AS jsonb), NOW())
                    ON CONFLICT (request_id) DO NOTHING
                    RETURNING request_id
                """),
                {
                    "request_id": record.request_id,
                    "user_id": record.user_id,
                    "scope": record.scope.value,
                    "category": record.category,
                    "fact_id": record.fact_id,
                    "status": record.status.value,
                    "affected_facts": record.affected_facts,
                    "affected_entities": record.affected_entities,
                    "affected_relations": record.affected_relations,
                    "affected_profiles": record.affected_profiles,
                    "affected_session_anchors": record.affected_session_anchors,
                    "boundary": _json_dumps(record.boundary),
                    "metadata": _json_dumps(record.metadata),
                },
            )
            if require_insert and result.scalar_one_or_none() is None:
                raise ValueError("memory deletion request_id already exists")
        return record

    async def list_audits(self, user_id: str, *, limit: int = 50) -> List[ForgettingAuditRecord]:
        async with get_db_session() as session:
            result = await session.execute(
                text("""
                    SELECT *
                    FROM memory_forgetting_audits
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"user_id": user_id, "limit": max(1, min(limit, 200))},
            )
            return [_record_from_row(dict(row)) for row in result.mappings().all()]


_memory_lifecycle_store_singleton: Optional[MemoryLifecycleStore] = None


def get_memory_lifecycle_store() -> MemoryLifecycleStore:
    global _memory_lifecycle_store_singleton
    if _memory_lifecycle_store_singleton is None:
        _memory_lifecycle_store_singleton = MemoryLifecycleStore()
    return _memory_lifecycle_store_singleton
