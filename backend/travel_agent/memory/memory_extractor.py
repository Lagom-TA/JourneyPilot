"""记忆抽取器（应用层）。

由 `background_jobs` 的 memory_extraction 任务调用，单次 fast model 调用同时产出：
  - facts[]   : 结构化转述的具体事实（保留关键参数，短期可用）
  - portrait[]: 抽象推理的画像特征（归纳持久特征，长期积累）

提取结果分别写入：
  - memory_facts 表（事实 + embedding，用于语义检索）
  - memory_entities / memory_relations 表（知识图谱）
  - user_profiles.auto_portrait（图谱聚合后的文本快照）
"""

from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text

from travel_agent.runtime.job_contracts import BackgroundJob
from travel_agent.storage.database import get_db_session
from ..utils.json_helpers import safe_parse_json
from .extraction_stats import get_memory_extraction_stats

logger = logging.getLogger(__name__)

_USER_MSG_TRUNCATE = 600
_PORTRAIT_TRUNCATE = 400
_PORTRAIT_FALLBACK = "暂无"
_IMPORTANCE_MIN = 1
_IMPORTANCE_MAX = 10

_EXTRACTION_PROMPT = """你是一个专业的用户画像分析师。请只从当前用户亲自写下的消息中提取长期记忆候选。

## 当前用户消息（唯一事实来源）
{user_message}

## 已知用户画像（避免重复提取已有的特征）
{existing_portrait}

## 输出格式（严格输出 JSON，不要任何解释）
{{
  "facts": [
    {{
      "content": "对本轮对话关键信息的结构化转述（保留具体参数：日期、地点、金额、人数等）",
      "category": "trip_plan 或 preference 或 constraint 或 feedback",
      "importance": 1到10的整数（10=最重要，如过敏信息/预算上限；1=可忽略如寒暄）,
      "user_evidence": "可选：支撑该事实的用户原话片段"
    }}
  ],
  "portrait": [
    {{
      "trait": "从本次对话抽象推理出的持久性用户特征（不要复述事实，要归纳特征）",
      "dimension": "lifestyle 或 budget_class 或 travel_style 或 personality 或 family 或 constraint",
      "supporting_fact_indexes": ["支撑该画像的 facts 数组下标"]
    }}
  ]
}}

## 提取规则
1. facts：用户消息中有明确、持久、可复用的信息时提取，通常 1-3 条。请求助手查询、助手的结论、工具结果和系统状态都不是用户事实。
2. user_evidence 可填写支撑该事实的用户原话片段，便于后续追溯；不要用已知画像代替本轮用户消息。
3. portrait：从本轮 facts 归纳持久特征，并用 supporting_fact_indexes 指向支撑它的 facts。
4. 如果本轮只有寒暄、提问、查询请求、模糊确认（如“是的”“可以”）或没有用户明确事实，facts 和 portrait 均返回空数组 []。
5. 已知画像只用于避免重复 portrait，不是本轮事实来源。
6. importance：10=用户明确陈述的安全约束，8=明确需求，6=强偏好，4=一般偏好，2=模糊兴趣。"""


class ExtractedFactCandidate(BaseModel):
    """一条通过 Pydantic 合同校验的记忆事实候选。"""

    model_config = {"extra": "forbid"}

    content: str = Field(min_length=1)
    category: Literal["trip_plan", "preference", "constraint", "feedback"]
    importance: int = Field(ge=_IMPORTANCE_MIN, le=_IMPORTANCE_MAX, strict=True)
    user_evidence: str = ""


class ExtractedPortraitCandidate(BaseModel):
    """一条通过 Pydantic 合同校验的用户画像候选。"""

    model_config = {"extra": "forbid"}

    trait: str = Field(min_length=1)
    dimension: Literal[
        "lifestyle",
        "budget_class",
        "travel_style",
        "personality",
        "family",
        "constraint",
    ]
    supporting_fact_indexes: List[int] = Field(min_length=1)


def _parse_extraction_result(
    result: Dict[str, Any],
) -> tuple[List[ExtractedFactCandidate], List[Dict[str, Any]]]:
    """解析模型结果：逐条做 Pydantic 校验，通过的事实与画像全部保留。

    画像必须引用至少一条通过校验的事实；用户原话片段可缺省。
    """

    facts: List[ExtractedFactCandidate] = []
    evidence_by_index: Dict[int, str] = {}
    raw_facts = result.get("facts") if isinstance(result.get("facts"), list) else []
    for raw_index, raw_fact in enumerate(raw_facts):
        try:
            candidate = ExtractedFactCandidate.model_validate(raw_fact)
        except ValidationError:
            continue
        if not candidate.content.strip():
            continue
        facts.append(candidate)
        evidence_by_index[raw_index] = candidate.user_evidence.strip()

    portraits: List[Dict[str, Any]] = []
    raw_portraits = (
        result.get("portrait") if isinstance(result.get("portrait"), list) else []
    )
    for raw_portrait in raw_portraits:
        try:
            candidate = ExtractedPortraitCandidate.model_validate(raw_portrait)
        except ValidationError:
            continue
        if not candidate.trait.strip() or not any(
            index in evidence_by_index for index in candidate.supporting_fact_indexes
        ):
            continue
        supporting = [
            evidence_by_index[index]
            for index in dict.fromkeys(candidate.supporting_fact_indexes)
            if evidence_by_index.get(index)
        ]
        portraits.append(
            {
                "trait": candidate.trait.strip(),
                "dimension": candidate.dimension,
                "evidence": "；".join(supporting),
            }
        )
    return facts, portraits


@dataclass(frozen=True)
class MemoryExtractionOutcome:
    """一次抽取的结果。调用方为持久任务，失败时应抛出异常，不能编码为 False。"""

    facts_written: int = 0
    portraits_written: int = 0

    @property
    def wrote_anything(self) -> bool:
        return self.facts_written > 0 or self.portraits_written > 0


def _committed_outcome(result: Any) -> Optional[MemoryExtractionOutcome]:
    if not isinstance(result, dict):
        return None
    committed = result.get("memory_extraction_committed")
    if not isinstance(committed, dict):
        return None
    facts, portraits = committed.get("facts"), committed.get("portraits")
    if (type(facts) is not int or facts < 0
            or type(portraits) is not int or portraits < 0):
        raise MemoryExtractionFailed("记忆抽取已应用标记不合法")
    return MemoryExtractionOutcome(facts, portraits)


class MemoryExtractionFailed(RuntimeError):
    """抽取未完成（模型调用或解析失败），可重试。"""


class MemoryExtractor:
    """记忆提取器。

    由 `background_jobs` 的 memory_extraction 任务调用，写入 memory_facts 与知识图谱。
    """

    async def extract_from_turn(
        self,
        user_id: str,
        session_id: str,
        user_msg: str,
        existing_portrait: str = "",
        source_message_id: str = "",
        job: Optional[BackgroundJob] = None,
    ) -> MemoryExtractionOutcome:
        """从一轮对话中提取事实和画像并写入存储。

        事实、画像及任务已应用标记由同一事务提交；重领时直接复用该标记。
        """
        if not user_msg:
            return MemoryExtractionOutcome()
        if job is None or not job.lease_owner:
            raise MemoryExtractionFailed("记忆抽取缺少有效任务租约")

        committed = _committed_outcome(job.result)
        if committed is not None:
            return committed

        stats = get_memory_extraction_stats()
        stats.record_attempt()
        try:
            result = await self._call_llm(user_msg, existing_portrait)
        except Exception as exc:
            stats.record_failure(exc.__class__.__name__)
            raise MemoryExtractionFailed(str(exc)) from exc
        if result is None:
            stats.record_failure("llm_call_or_parse")
            raise MemoryExtractionFailed("记忆抽取模型调用或解析失败")

        try:
            facts, portrait = _parse_extraction_result(result)

            from travel_agent.config.loader import get_settings
            from .memory_store import MemoryStore

            store = MemoryStore()
            embeddings = [
                await store._compute_embedding(fact.content.strip())
                if get_settings().embedding.enabled else None
                for fact in facts
            ]
            outcome = await self._commit_extraction(
                job=job, user_id=user_id, session_id=session_id,
                source_message_id=source_message_id, facts=facts,
                embeddings=embeddings, portrait=portrait, store=store,
            )
        except Exception as exc:
            stats.record_failure(exc.__class__.__name__)
            logger.warning(
                f"记忆抽取写入失败 user={user_id} session={session_id}: {exc}", exc_info=True
            )
            raise

        stats.record_success(facts=outcome.facts_written, portraits=outcome.portraits_written)
        if outcome.wrote_anything:
            logger.info(
                f"记忆抽取入库 user={user_id} session={session_id} "
                f"facts={outcome.facts_written} portrait={outcome.portraits_written}"
            )
        else:
            logger.debug(
                f"记忆抽取本轮无值可写 user={user_id} session={session_id}"
            )
        return outcome

    async def _commit_extraction(
        self, *, job: BackgroundJob, user_id: str, session_id: str,
        source_message_id: str, facts: List[ExtractedFactCandidate],
        embeddings: List[Optional[List[float]]], portrait: List[Dict[str, Any]],
        store: Any,
    ) -> MemoryExtractionOutcome:
        from .memory_graph import MemoryGraph
        from .user_profile import UserProfileMemory

        async with get_db_session() as session:
            result = await session.execute(
                text("""
                    SELECT result FROM background_jobs
                    WHERE job_id = :job_id AND status = 'running'
                      AND lease_owner = :owner AND lease_expires_at > clock_timestamp()
                    FOR UPDATE
                """),
                {"job_id": job.job_id, "owner": job.lease_owner},
            )
            row = result.mappings().first()
            if row is None:
                raise MemoryExtractionFailed("记忆抽取任务租约已失效")
            committed = _committed_outcome(row["result"])
            if committed is not None:
                return committed

            if facts or portrait:
                await UserProfileMemory().ensure_profile_for_write(
                    user_id, db_session=session, lock=True
                )
            for fact, embedding in zip(facts, embeddings, strict=True):
                fact_id = await store.save_fact(
                    user_id=user_id, session_id=session_id, content=fact.content.strip(),
                    category=fact.category, importance=fact.importance,
                    source_message_id=source_message_id, db_session=session,
                    prepared_embedding=embedding,
                )
                if fact_id is None:
                    raise MemoryExtractionFailed("记忆事实写入失败")
            if portrait:
                graph = MemoryGraph()
                await graph.update_portrait(user_id, portrait, session_id, db_session=session)
                portrait_text = await graph.aggregate_portrait(user_id, db_session=session)
                await graph.save_portrait_to_profile(user_id, portrait_text, db_session=session)

            outcome = MemoryExtractionOutcome(len(facts), len(portrait))
            marked = await session.execute(
                text("""
                    UPDATE background_jobs SET result = CAST(:result AS jsonb), updated_at = NOW()
                    WHERE job_id = :job_id AND status = 'running' AND lease_owner = :owner
                      AND lease_expires_at > clock_timestamp()
                    RETURNING job_id
                """),
                {"job_id": job.job_id, "owner": job.lease_owner,
                 "result": json.dumps({"memory_extraction_committed": {
                     "facts": outcome.facts_written, "portraits": outcome.portraits_written,
                 }})},
            )
            if marked.scalar_one_or_none() is None:
                raise MemoryExtractionFailed("记忆抽取任务租约已失效")
            return outcome

    # -----------------------------------------------------------------------
    # 内部实现
    # -----------------------------------------------------------------------

    async def _call_llm(
        self,
        user_msg: str,
        existing_portrait: str,
    ) -> Optional[Dict[str, Any]]:
        """调用 fast model 提取事实和画像，返回解析后的字典；解析失败返回 None。

        调用异常原样抛出，供 job 层区分供应商超时与输出格式错误。
        """
        from ..llm.router import get_model_router
        router = get_model_router()
        llm = router.get_fast()

        user_truncated = user_msg[:_USER_MSG_TRUNCATE]
        portrait_truncated = existing_portrait[:_PORTRAIT_TRUNCATE] if existing_portrait else _PORTRAIT_FALLBACK

        prompt = _EXTRACTION_PROMPT.format(
            user_message=user_truncated,
            existing_portrait=portrait_truncated,
        )

        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        parsed = safe_parse_json(response)
        if parsed is not None:
            parsed.setdefault("facts", [])
            parsed.setdefault("portrait", [])
        return parsed
