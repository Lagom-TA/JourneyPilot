from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ..storage.database import get_db_session

logger = logging.getLogger(__name__)

_PRODUCED_RELATIONS = frozenset({"has_trait"})

# dimension → 中文分组标题
_DIMENSION_TITLES: Dict[str, str] = {
    "family": "家庭状况",
    "budget_class": "消费水平",
    "travel_style": "旅行风格",
    "lifestyle": "生活方式",
    "personality": "个性特点",
    "constraint": "特殊限制",
}
_DIMENSION_ORDER = list(_DIMENSION_TITLES.keys())


class MemoryGraph:
    """知识图谱读写器。"""

    # -----------------------------------------------------------------------
    # 写入方法
    # -----------------------------------------------------------------------

    async def upsert_entity(
        self,
        user_id: str,
        name: str,
        entity_type: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> int:
        """创建或更新实体节点。

        以 (user_id, name, entity_type) 唯一约束执行 upsert，返回 entity_id。
        """
        import json as _json
        props_json = _json.dumps(properties or {}, ensure_ascii=False)

        async with get_db_session() as session:
            result = await session.execute(
                text("""
                    INSERT INTO memory_entities
                        (user_id, name, entity_type, properties, created_at, updated_at)
                    VALUES
                        (:uid, :name, :etype, CAST(:props AS jsonb), NOW(), NOW())
                    ON CONFLICT (user_id, name, entity_type)
                    DO UPDATE SET
                        properties = EXCLUDED.properties,
                        updated_at = NOW()
                    RETURNING entity_id
                """),
                {"uid": user_id, "name": name, "etype": entity_type, "props": props_json},
            )
            row = result.mappings().first()
            return int(row["entity_id"]) if row else 0

    async def upsert_relation(
        self,
        user_id: str,
        source_name: str,
        source_type: str,
        target_name: str,
        target_type: str,
        relation: str,
        confidence: float = 1.0,
        evidence: str = "",
        session_id: str = "",
        source_properties: Optional[Dict[str, Any]] = None,
        target_properties: Optional[Dict[str, Any]] = None,
    ) -> None:
        """创建或更新关系边。

        1. 关系类型必须有产出方，否则拒绝（不创建实体、不写入关系）。
        2. upsert 两端实体。
        3. 插入关系；相同 source/target/relation 已存在时更新 confidence。

        写入关系不会修改已有的其他行：同一用户节点下的 trait 可以多值并存，
        因此这里没有 UPDATE 或 DELETE。
        """
        if relation not in _PRODUCED_RELATIONS:
            raise ValueError(
                f"关系类型 {relation!r} 在这个仓里没有产出方；"
                f"图谱只接 {sorted(_PRODUCED_RELATIONS)}，要加新的先把写入方一起加出来"
            )

        source_id = await self.upsert_entity(user_id, source_name, source_type, source_properties)
        target_id = await self.upsert_entity(user_id, target_name, target_type, target_properties)

        if not source_id or not target_id:
            return

        async with get_db_session() as session:
            # 插入或更新同一 (source, target, relation) 的关系
            await session.execute(
                text("""
                    INSERT INTO memory_relations
                        (user_id, source_id, target_id, relation, confidence,
                         evidence, valid_from, source_session, created_at)
                    VALUES
                        (:uid, :src, :tgt, :rel, :conf,
                         :evidence, NOW(), :sess, NOW())
                    ON CONFLICT (user_id, source_id, target_id, relation)
                    DO UPDATE SET
                        confidence = GREATEST(memory_relations.confidence, EXCLUDED.confidence),
                        evidence = CASE
                            WHEN EXCLUDED.evidence <> '' THEN EXCLUDED.evidence
                            ELSE memory_relations.evidence
                        END,
                        source_session = CASE
                            WHEN EXCLUDED.source_session <> '' THEN EXCLUDED.source_session
                            ELSE memory_relations.source_session
                        END
                """),
                {
                    "uid": user_id,
                    "src": source_id,
                    "tgt": target_id,
                    "rel": relation,
                    "conf": confidence,
                    "evidence": evidence,
                    "sess": session_id,
                },
            )

    async def update_portrait(
        self,
        user_id: str,
        portrait_items: List[Dict[str, Any]],
        session_id: str = "",
    ) -> None:
        """批量处理 portrait[] 提取结果。

        每个 trait 转为（用户节点）-[has_trait]->（trait 实体）关系；
        trait 实体的 properties 保存 dimension，供聚合时分组。
        """
        for item in portrait_items:
            trait = (item.get("trait") or "").strip()
            evidence = (item.get("evidence") or "").strip()
            dimension = (item.get("dimension") or "lifestyle").strip()

            if not trait:
                continue

            try:
                await self.upsert_relation(
                    user_id=user_id,
                    source_name="user",
                    source_type="person",
                    target_name=trait,
                    target_type="trait",
                    relation="has_trait",
                    confidence=1.0,
                    evidence=evidence,
                    session_id=session_id,
                    target_properties={"dimension": dimension},
                )
            except Exception as e:
                logger.debug(f"MemoryGraph.update_portrait 单条写入失败: {e}")

    # -----------------------------------------------------------------------
    # 读取方法
    # -----------------------------------------------------------------------

    async def get_relations(self, user_id: str) -> List[Dict[str, Any]]:
        async with get_db_session() as session:
            result = await session.execute(
                text("""
                    SELECT
                        r.relation_id,
                        r.relation,
                        r.confidence,
                        r.evidence,
                        r.valid_from,
                        se.name        AS source_name,
                        se.entity_type AS source_type,
                        te.name        AS target_name,
                        te.entity_type AS target_type,
                        te.properties  AS target_props
                    FROM memory_relations r
                    JOIN memory_entities se ON r.source_id = se.entity_id
                    JOIN memory_entities te ON r.target_id = te.entity_id
                    WHERE r.user_id = :uid
                    ORDER BY r.valid_from ASC
                """),
                {"uid": user_id},
            )
            rows = result.mappings().fetchall()
        return [dict(r) for r in rows]

    async def delete_user_graph(self, user_id: str) -> Dict[str, int]:
        """物理删除该用户的图谱实体与关系。"""
        if not user_id:
            return {"entities": 0, "relations": 0}
        async with get_db_session() as session:
            relation_result = await session.execute(
                text("""
                    DELETE FROM memory_relations
                    WHERE user_id = :uid
                    RETURNING relation_id
                """),
                {"uid": user_id},
            )
            entity_result = await session.execute(
                text("""
                    DELETE FROM memory_entities
                    WHERE user_id = :uid
                    RETURNING entity_id
                """),
                {"uid": user_id},
            )
            return {
                "relations": len(relation_result.fetchall()),
                "entities": len(entity_result.fetchall()),
            }

    async def delete_relation(self, user_id: str, relation_id: int | str) -> int:
        """物理删除该用户的一条关系。"""
        if not user_id or relation_id is None:
            return 0
        async with get_db_session() as session:
            result = await session.execute(
                text("""
                    DELETE FROM memory_relations
                    WHERE user_id = :uid AND relation_id = :relation_id
                    RETURNING relation_id
                """),
                {"uid": user_id, "relation_id": relation_id},
            )
            return len(result.fetchall())

    async def delete_entity(self, user_id: str, entity_id: int | str) -> Dict[str, int]:
        """物理删除一个实体及其关联关系。"""
        if not user_id or entity_id is None:
            return {"entities": 0, "relations": 0}
        async with get_db_session() as session:
            relation_result = await session.execute(
                text("""
                    DELETE FROM memory_relations
                    WHERE user_id = :uid AND (source_id = :entity_id OR target_id = :entity_id)
                    RETURNING relation_id
                """),
                {"uid": user_id, "entity_id": entity_id},
            )
            entity_result = await session.execute(
                text("""
                    DELETE FROM memory_entities
                    WHERE user_id = :uid AND entity_id = :entity_id
                    RETURNING entity_id
                """),
                {"uid": user_id, "entity_id": entity_id},
            )
            return {
                "relations": len(relation_result.fetchall()),
                "entities": len(entity_result.fetchall()),
            }

    async def aggregate_portrait(self, user_id: str) -> str:
        """从图谱聚合用户画像文本，使用纯模板，不调用 LLM。

        输出示例：
            家庭状况：已婚，有伴侣出行需求
            消费水平：中产阶级，追求品质但非奢侈
            特殊限制：对海鲜过敏

        无数据时返回空字符串。
        """
        relations = await self.get_relations(user_id)
        if not relations:
            return ""

        grouped: Dict[str, List[str]] = defaultdict(list)

        for r in relations:
            target_props = r.get("target_props") or {}
            if isinstance(target_props, str):
                import json as _json
                try:
                    target_props = _json.loads(target_props)
                except Exception:
                    target_props = {}

            dimension = target_props.get("dimension", "lifestyle")
            grouped[dimension].append(r["target_name"])

        # 按 _DIMENSION_ORDER 输出，保证同一份图谱两次读取得到相同文本。
        lines: List[str] = []
        for dim in _DIMENSION_ORDER:
            traits = grouped.get(dim, [])
            if traits:
                lines.append(f"{_DIMENSION_TITLES[dim]}：{'，'.join(traits)}")

        return "\n".join(lines)

    async def save_portrait_to_profile(self, user_id: str, portrait_text: str) -> None:
        """将已经聚合出的真实画像写入 profile；这是允许创建画像的写路径。"""
        from .user_profile import UserProfileMemory

        profile_memory = UserProfileMemory()
        profile = await profile_memory.ensure_profile_for_write(user_id)
        profile.auto_portrait = portrait_text
        await profile_memory.save_user_profile(profile)
