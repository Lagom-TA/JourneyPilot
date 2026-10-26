"""记忆事实存储（Infrastructure Layer）。

原子事实存储与三因子语义检索。

存储结构：
  memory_facts 表：content + embedding + category + importance + created_at

三因子检索评分：
  Score = alpha × Relevance + beta × Recency + gamma × Importance

  Relevance  = 1 - cosine_distance（pgvector 余弦相似度）
  Recency    = exp(-lambda × hours_since_created)  指数衰减，lambda=0.01
  Importance = importance / 10.0                   归一化
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ..config.loader import get_settings
from travel_agent.memory.extraction_jobs import memory_fact_digest
from travel_agent.memory.lifecycle import MemoryRetentionPolicy, MemoryRetentionStatus
from ..storage.database import get_db_session
from ..storage.row_values import iso_or_empty as _iso

logger = logging.getLogger(__name__)

# 衰减系数：约 70 小时（~3天）后 Recency 降到 0.5
_RECENCY_LAMBDA = 0.01
# importance 取值范围
_IMPORTANCE_MIN = 1
_IMPORTANCE_MAX = 10

# 用户在「记忆与偏好」页手动添加的记忆，用固定 session_id 打标，
# 以便与自动抽取的记忆区分（列表 UI 显示「我添加的」，注入链路无条件全量前置）。
USER_MANUAL_SESSION_ID = "user-manual"
# 手动记忆固定用最高重要性档，保证在检索排序和保留策略中处于最高级。
USER_MANUAL_IMPORTANCE = _IMPORTANCE_MAX




def _fact_row(row: Any) -> Dict[str, Any]:
    """记忆事实的对外结构，列表、按 id 读回与按内容查找共用。

    ``source`` 由 ``session_id`` 投影，不是独立列：手动记忆使用固定的
    ``USER_MANUAL_SESSION_ID``。
    """
    return {
        "fact_id": str(row["fact_id"]),
        "content": row["content"],
        "category": row["category"],
        "importance": row["importance"],
        "source": "manual" if row.get("session_id") == USER_MANUAL_SESSION_ID else "auto",
        "created_at": _iso(row.get("created_at")),
        "expires_at": _iso(row.get("expires_at")),
    }


def _is_expired(expires_at: Any, *, now: Optional[datetime] = None) -> bool:
    if not expires_at:
        return False
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except Exception:
            return False
    if isinstance(expires_at, datetime):
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= now_dt
    return False


class MemoryStore:
    """原子事实存储与检索器。"""

    # -----------------------------------------------------------------------
    # 写入
    # -----------------------------------------------------------------------

    async def save_fact(
        self,
        user_id: str,
        session_id: str,
        content: str,
        category: str = "preference",
        importance: int = 5,
        retention_policy: Optional[MemoryRetentionPolicy] = None,
        source_message_id: str = "",
    ) -> Optional[int]:
        """计算 embedding 并把事实写入 memory_facts 表，返回该行的 ``fact_id``。

        返回写入行的标识，调用方无需按内容回读确认。失败时返回 ``None``；
        该路径非关键，不抛出异常。

        传入 ``source_message_id`` 时按 (user, 来源消息, 正文) 摘要去重，
        避免至少一次投递的任务重复写入同一句事实。
        """
        if not content or not user_id:
            return None
        try:
            import json as _json

            importance = max(_IMPORTANCE_MIN, min(_IMPORTANCE_MAX, importance))
            policy = retention_policy or MemoryRetentionPolicy()
            expires_at = policy.expires_at_for(category, importance)
            policy_metadata = policy.to_metadata(category, importance)
            digest = (
                memory_fact_digest(user_id, source_message_id, content)
                if source_message_id
                else None
            )
            vec_str = None
            if get_settings().embedding.enabled:
                embedding = await self._compute_embedding(content)
                vec_str = f"[{','.join(str(v) for v in embedding)}]"

            async with get_db_session() as session:
                result = await session.execute(
                    text("""
                        INSERT INTO memory_facts
                            (user_id, session_id, content, category, importance, embedding,
                             expires_at, retention_category, retention_policy,
                             source_message_id, fact_digest, created_at)
                        VALUES
                            (:uid, :sid, :content, :cat, :imp, CAST(:emb AS vector),
                             :expires_at, :retention_category, CAST(:retention_policy AS jsonb),
                             :source_message_id, :fact_digest, NOW())
                        ON CONFLICT (user_id, fact_digest) WHERE fact_digest IS NOT NULL
                        DO NOTHING
                        RETURNING fact_id
                    """),
                    {
                        "uid": user_id,
                        "sid": session_id,
                        "content": content,
                        "cat": category,
                        "imp": importance,
                        "emb": vec_str,
                        "expires_at": expires_at,
                        "retention_category": category or "standard",
                        "retention_policy": _json.dumps(policy_metadata, ensure_ascii=False),
                        "source_message_id": source_message_id,
                        "fact_digest": digest,
                    },
                )
                fact_id = result.scalar_one_or_none()
                if fact_id is None and digest is not None:
                    # 同一摘要已存在，重复投递时返回已有行。
                    existing = await session.execute(
                        text(
                            "SELECT fact_id FROM memory_facts "
                            "WHERE user_id = :uid AND fact_digest = :digest"
                        ),
                        {"uid": user_id, "digest": digest},
                    )
                    fact_id = existing.scalar_one_or_none()
            if fact_id is None:
                logger.warning(f"记忆事实写入没有交回 fact_id user={user_id} category={category}")
                return None
            logger.debug(f"MemoryStore: 写入事实 user={user_id} category={category} importance={importance}")
            return int(fact_id)
        except Exception as e:
            logger.warning(f"记忆事实写入失败 user={user_id} category={category}: {e}")
            return None

    # -----------------------------------------------------------------------
    # 检索
    # -----------------------------------------------------------------------

    async def search_facts(
        self,
        user_id: str,
        query_text: str,
        top_k: int = 5,
        alpha: float = 0.4,   # Relevance 权重
        beta: float = 0.3,    # Recency 权重
        gamma: float = 0.3,   # Importance 权重
        include_score_breakdown: bool = False,
        # 三因子归一化范围: Relevance∈[0,1], Recency∈(0,1], Importance∈[0.1,1.0]
    ) -> List[Dict[str, Any]]:
        """三因子语义检索。

        user_id: 仅检索该用户的记忆。
        query_text: 查询文本。
        top_k: 返回条数。
        alpha / beta / gamma: Relevance / Recency / Importance 权重。

        返回按综合分降序排列的事实，每条包含 content、category、importance、
        score 与 created_at。
        """
        if not get_settings().embedding.enabled:
            return []
        if not query_text or not user_id:
            return []
        try:
            embedding = await self._compute_embedding(query_text)
            vec_str = f"[{','.join(str(v) for v in embedding)}]"

            async with get_db_session() as session:
                result = await session.execute(
                    text(f"""
                        SELECT
                            fact_id,
                            content,
                            category,
                            importance,
                            created_at,
                            expires_at,
                            (1 - (embedding <=> CAST(:qvec AS vector))) AS relevance_score,
                            EXP(-{_RECENCY_LAMBDA} * EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600.0) AS recency_score,
                            (importance / {_IMPORTANCE_MAX}.0) AS importance_score,
                            (
                                :alpha * (1 - (embedding <=> CAST(:qvec AS vector)))
                                + :beta  * EXP(-{_RECENCY_LAMBDA} * EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600.0)
                                + :gamma * (importance / {_IMPORTANCE_MAX}.0)
                            ) AS score
                        FROM memory_facts
                        WHERE user_id = :uid
                          AND embedding IS NOT NULL
                          AND (expires_at IS NULL OR expires_at > NOW())
                        ORDER BY score DESC
                        LIMIT :topk
                    """),
                    {
                        "uid": user_id,
                        "qvec": vec_str,
                        "alpha": alpha,
                        "beta": beta,
                        "gamma": gamma,
                        "topk": top_k,
                    },
                )
                rows = result.mappings().fetchall()

            facts = []
            for row in rows:
                facts.append({
                    "fact_id": row["fact_id"],
                    "content": row["content"],
                    "category": row["category"],
                    "importance": row["importance"],
                    "score": float(row["score"]),
                    "created_at": row["created_at"],
                    "expires_at": row.get("expires_at"),
                    "retention_status": MemoryRetentionStatus.ACTIVE.value,
                })
                if include_score_breakdown:
                    facts[-1].update({
                        "relevance_score": float(row["relevance_score"]),
                        "recency_score": float(row["recency_score"]),
                        "importance_score": float(row["importance_score"]),
                        "score_weights": {"alpha": alpha, "beta": beta, "gamma": gamma},
                    })
            return facts

        except Exception as e:
            logger.debug(f"MemoryStore.search_facts 失败（非关键路径）: {e}")
            return []

    # -----------------------------------------------------------------------
    # 列表（非语义检索：直接查表，用于「记忆与偏好」页展示与手动记忆注入）
    # -----------------------------------------------------------------------

    async def list_facts(
        self,
        user_id: str,
        *,
        include_expired: bool = False,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """列出该用户全部记忆事实（按创建时间倒序），不走语义检索。

        每条包含 fact_id / content / category / importance / created_at /
        expires_at / source。source 为 'manual'（用户手动添加）或 'auto'（系统自动抽取）。
        """
        if not user_id:
            return []
        try:
            expiry_clause = "" if include_expired else "AND (expires_at IS NULL OR expires_at > NOW())"
            async with get_db_session() as session:
                result = await session.execute(
                    text(f"""
                        SELECT
                            fact_id,
                            content,
                            category,
                            importance,
                            session_id,
                            created_at,
                            expires_at
                        FROM memory_facts
                        WHERE user_id = :uid
                          {expiry_clause}
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {"uid": user_id, "limit": max(1, min(limit, 2000))},
                )
                rows = result.mappings().fetchall()

            return [_fact_row(row) for row in rows]
        except Exception as e:
            logger.debug(f"MemoryStore.list_facts 失败（非关键路径）: {e}")
            return []

    async def get_fact(self, user_id: str, fact_id: str | int) -> Optional[Dict[str, Any]]:
        """按身份读回一条记忆事实（含已过期的）。

        写入返回 ``fact_id`` 后，这里可直接读取刚创建的那一条，无需扫描全量列表。
        """
        if not user_id or fact_id is None:
            return None
        try:
            fact_id_int = int(fact_id)
        except (TypeError, ValueError):
            return None
        async with get_db_session() as session:
            result = await session.execute(
                text("""
                    SELECT fact_id, content, category, importance, session_id, created_at, expires_at
                    FROM memory_facts
                    WHERE user_id = :uid AND fact_id = :fact_id
                """),
                {"uid": user_id, "fact_id": fact_id_int},
            )
            row = result.mappings().first()
        return _fact_row(row) if row else None

    async def find_manual_fact(self, user_id: str, content: str) -> Optional[Dict[str, Any]]:
        """查找该用户仍然有效的同一句手动记忆；不存在时返回 None。

        这是「同一句话只保留一条」的判定依据，作用域仅限手动记忆：抽取器写入的
        同一句话不会阻止用户手动添加。已过期记录不参与判断。
        """
        if not user_id or not content:
            return None
        async with get_db_session() as session:
            result = await session.execute(
                text("""
                    SELECT fact_id, content, category, importance, session_id, created_at, expires_at
                    FROM memory_facts
                    WHERE user_id = :uid
                      AND session_id = :sid
                      AND content = :content
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY created_at ASC
                    LIMIT 1
                """),
                {"uid": user_id, "sid": USER_MANUAL_SESSION_ID, "content": content},
            )
            row = result.mappings().first()
        return _fact_row(row) if row else None

    async def list_manual_facts(self, user_id: str, *, limit: int) -> List[Dict[str, Any]]:
        """列出该用户手动添加的记忆（session_id = USER_MANUAL_SESSION_ID）。

        按创建时间倒序，供注入链路无条件全量前置，不依赖语义匹配。

        ``limit`` 必填且原样生效：条数由调用方的预算决定。上限只在
        ``ContextBudget.manual_memory_facts_limit`` 定义，存储层不设默认值或夹值。
        """
        if not user_id:
            return []
        try:
            async with get_db_session() as session:
                result = await session.execute(
                    text("""
                        SELECT fact_id, content, category, importance, created_at
                        FROM memory_facts
                        WHERE user_id = :uid
                          AND session_id = :sid
                          AND (expires_at IS NULL OR expires_at > NOW())
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {"uid": user_id, "sid": USER_MANUAL_SESSION_ID, "limit": limit},
                )
                rows = result.mappings().fetchall()
            return [
                {
                    "fact_id": str(row["fact_id"]),
                    "content": row["content"],
                    "category": row["category"],
                    "importance": row["importance"],
                    "created_at": _iso(row["created_at"]),
                }
                for row in rows
            ]
        except Exception as e:
            logger.debug(f"MemoryStore.list_manual_facts 失败（非关键路径）: {e}")
            return []

    # -----------------------------------------------------------------------
    # 删除 / retention cleanup
    # -----------------------------------------------------------------------

    async def delete_fact(self, user_id: str, fact_id: str | int) -> int:
        if not user_id or fact_id is None:
            return 0
        # fact_id 列是 bigint；路由层传入的是路径参数字符串，asyncpg 不做隐式转换
        try:
            fact_id_int = int(fact_id)
        except (TypeError, ValueError):
            return 0
        async with get_db_session() as session:
            result = await session.execute(
                text("""
                    DELETE FROM memory_facts
                    WHERE user_id = :uid AND fact_id = :fact_id
                    RETURNING fact_id
                """),
                {"uid": user_id, "fact_id": fact_id_int},
            )
            return len(result.fetchall())

    async def delete_by_category(self, user_id: str, category: str) -> int:
        if not user_id or not category:
            return 0
        async with get_db_session() as session:
            result = await session.execute(
                text("""
                    DELETE FROM memory_facts
                    WHERE user_id = :uid AND category = :category
                    RETURNING fact_id
                """),
                {"uid": user_id, "category": category},
            )
            return len(result.fetchall())

    async def delete_all_user_facts(self, user_id: str) -> int:
        if not user_id:
            return 0
        async with get_db_session() as session:
            result = await session.execute(
                text("""
                    DELETE FROM memory_facts
                    WHERE user_id = :uid
                    RETURNING fact_id
                """),
                {"uid": user_id},
            )
            return len(result.fetchall())

    async def delete_expired_facts(
        self,
        user_id: Optional[str] = None,
        *,
        now: Optional[datetime] = None,
        limit: int = 1000,
    ) -> int:
        params: Dict[str, Any] = {
            "now": now or datetime.now(timezone.utc),
            "limit": max(1, min(limit, 10_000)),
        }
        user_clause = ""
        if user_id:
            user_clause = "AND user_id = :uid"
            params["uid"] = user_id
        async with get_db_session() as session:
            result = await session.execute(
                text(f"""
                    WITH doomed AS (
                        SELECT fact_id
                        FROM memory_facts
                        WHERE expires_at IS NOT NULL
                          AND expires_at <= :now
                          {user_clause}
                        ORDER BY expires_at ASC
                        LIMIT :limit
                    )
                    DELETE FROM memory_facts mf
                    USING doomed
                    WHERE mf.fact_id = doomed.fact_id
                    RETURNING mf.fact_id
                """),
                params,
            )
            return len(result.fetchall())

    # -----------------------------------------------------------------------
    # 内部辅助
    # -----------------------------------------------------------------------

    async def _compute_embedding(self, text_content: str) -> List[float]:
        """通过 models.embedder.get_embedder() 计算向量（provider 由 config.embedding 决定）。"""
        from ..llm.embedder import get_embedder
        embedder = get_embedder()
        return await embedder.embed(text_content)

    def format_facts_for_prompt(self, facts: List[Dict[str, Any]]) -> str:
        """将检索到的事实格式化为可注入 system prompt 的字符串。"""
        if not facts:
            return ""
        lines = []
        for i, f in enumerate(facts, 1):
            importance = f.get("importance", 5)
            content = f.get("content", "")
            # 高重要性事实用 ⚠️ 标记，低重要性用普通序号
            prefix = "⚠️" if importance >= 8 else f"{i}."
            lines.append(f"{prefix} {content}")
        return "\n".join(lines)


class InMemoryMemoryStore(MemoryStore):
    """生命周期测试使用的内存记忆存储。"""

    def __init__(self, retention_policy: Optional[MemoryRetentionPolicy] = None) -> None:
        self._facts: List[Dict[str, Any]] = []
        self._next_id = 1
        self._policy = retention_policy or MemoryRetentionPolicy()

    async def save_fact(
        self,
        user_id: str,
        session_id: str,
        content: str,
        category: str = "preference",
        importance: int = 5,
        retention_policy: Optional[MemoryRetentionPolicy] = None,
        source_message_id: str = "",
    ) -> Optional[int]:
        # 与 SQL 实现相同契约：写入返回该行的 fact_id，摘要相同不写第二行。
        if not content or not user_id:
            return None
        importance = max(_IMPORTANCE_MIN, min(_IMPORTANCE_MAX, int(importance)))
        policy = retention_policy or self._policy
        created_at = datetime.now(timezone.utc)
        digest = (
            memory_fact_digest(user_id, source_message_id, content)
            if source_message_id
            else None
        )
        if digest is not None:
            for existing in self._facts:
                if existing.get("fact_digest") == digest and existing["user_id"] == user_id:
                    return int(existing["fact_id"])
        fact_id = self._next_id
        self._facts.append({
            "fact_id": fact_id,
            "user_id": user_id,
            "session_id": session_id,
            "content": content,
            "category": category,
            "importance": importance,
            "created_at": created_at,
            "source_message_id": source_message_id,
            "fact_digest": digest,
            "expires_at": policy.expires_at_for(category, importance, created_at=created_at),
            "retention_policy": policy.to_metadata(category, importance),
        })
        self._next_id += 1
        return fact_id

    async def search_facts(
        self,
        user_id: str,
        query_text: str,
        top_k: int = 5,
        alpha: float = 0.4,
        beta: float = 0.3,
        gamma: float = 0.3,
        include_score_breakdown: bool = False,
    ) -> List[Dict[str, Any]]:
        if not user_id or not query_text:
            return []
        now = datetime.now(timezone.utc)
        query_terms = set(str(query_text).lower().split())
        rows: List[Dict[str, Any]] = []
        for fact in self._facts:
            if fact["user_id"] != user_id or _is_expired(fact.get("expires_at"), now=now):
                continue
            content = str(fact.get("content") or "")
            content_terms = set(content.lower().split())
            overlap = len(query_terms & content_terms)
            relevance = min(1.0, overlap / max(1, len(query_terms))) if query_terms else 0.5
            age_hours = max(0.0, (now - fact["created_at"]).total_seconds() / 3600.0)
            recency = math.exp(-_RECENCY_LAMBDA * age_hours)
            importance_score = fact["importance"] / _IMPORTANCE_MAX
            score = alpha * relevance + beta * recency + gamma * importance_score
            row = {
                "fact_id": fact["fact_id"],
                "content": content,
                "category": fact["category"],
                "importance": fact["importance"],
                "score": score,
                "created_at": _iso(fact["created_at"]),
                "expires_at": _iso(fact.get("expires_at")),
                "retention_status": MemoryRetentionStatus.ACTIVE.value,
            }
            if include_score_breakdown:
                row.update({
                    "relevance_score": relevance,
                    "recency_score": recency,
                    "importance_score": importance_score,
                    "score_weights": {"alpha": alpha, "beta": beta, "gamma": gamma},
                })
            rows.append(row)
        rows.sort(key=lambda item: item["score"], reverse=True)
        return rows[: max(1, top_k)]

    async def list_facts(
        self,
        user_id: str,
        *,
        include_expired: bool = False,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        if not user_id:
            return []
        now = datetime.now(timezone.utc)
        rows: List[Dict[str, Any]] = []
        for fact in self._facts:
            if fact["user_id"] != user_id:
                continue
            if not include_expired and _is_expired(fact.get("expires_at"), now=now):
                continue
            rows.append(_fact_row(fact))
        rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return rows[: max(1, min(limit, 2000))]

    async def get_fact(self, user_id: str, fact_id: str | int) -> Optional[Dict[str, Any]]:
        if not user_id or fact_id is None:
            return None
        wanted = str(fact_id)
        for fact in self._facts:
            if fact["user_id"] == user_id and str(fact["fact_id"]) == wanted:
                return _fact_row(fact)
        return None

    async def find_manual_fact(self, user_id: str, content: str) -> Optional[Dict[str, Any]]:
        if not user_id or not content:
            return None
        now = datetime.now(timezone.utc)
        matches = [
            fact for fact in self._facts
            if fact["user_id"] == user_id
            and fact.get("session_id") == USER_MANUAL_SESSION_ID
            and fact.get("content") == content
            and not _is_expired(fact.get("expires_at"), now=now)
        ]
        if not matches:
            return None
        return _fact_row(min(matches, key=lambda fact: fact["created_at"]))

    async def list_manual_facts(self, user_id: str, *, limit: int) -> List[Dict[str, Any]]:
        # 与 DB 实现相同契约：``limit`` 必填且原样生效，存储层不替调用方决定条数。
        if not user_id:
            return []
        now = datetime.now(timezone.utc)
        rows: List[Dict[str, Any]] = []
        for fact in self._facts:
            if fact["user_id"] != user_id or fact.get("session_id") != USER_MANUAL_SESSION_ID:
                continue
            if _is_expired(fact.get("expires_at"), now=now):
                continue
            rows.append({
                "fact_id": str(fact["fact_id"]),
                "content": fact.get("content"),
                "category": fact.get("category"),
                "importance": fact.get("importance"),
                "created_at": _iso(fact.get("created_at")),
            })
        rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return rows[:limit]

    async def delete_fact(self, user_id: str, fact_id: str | int) -> int:
        before = len(self._facts)
        fact_id_text = str(fact_id)
        self._facts = [
            fact for fact in self._facts
            if not (fact["user_id"] == user_id and str(fact["fact_id"]) == fact_id_text)
        ]
        return before - len(self._facts)

    async def delete_by_category(self, user_id: str, category: str) -> int:
        before = len(self._facts)
        self._facts = [
            fact for fact in self._facts
            if not (fact["user_id"] == user_id and fact["category"] == category)
        ]
        return before - len(self._facts)

    async def delete_all_user_facts(self, user_id: str) -> int:
        before = len(self._facts)
        self._facts = [fact for fact in self._facts if fact["user_id"] != user_id]
        return before - len(self._facts)

    async def delete_expired_facts(
        self,
        user_id: Optional[str] = None,
        *,
        now: Optional[datetime] = None,
        limit: int = 1000,
    ) -> int:
        now_dt = now or datetime.now(timezone.utc)
        removed = 0
        kept: List[Dict[str, Any]] = []
        for fact in self._facts:
            matches_user = not user_id or fact["user_id"] == user_id
            if matches_user and removed < limit and _is_expired(fact.get("expires_at"), now=now_dt):
                removed += 1
                continue
            kept.append(fact)
        self._facts = kept
        return removed
