"""
Memory Extractor（应用层）

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
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from ..utils.json_helpers import safe_parse_json
from .extraction_stats import get_memory_extraction_stats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 局部配置常量
# ---------------------------------------------------------------------------

_USER_MSG_TRUNCATE = 600
_PORTRAIT_TRUNCATE = 400
_PORTRAIT_FALLBACK = "暂无"
_IMPORTANCE_MIN = 1
_IMPORTANCE_MAX = 10

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

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

    画像的 supporting_fact_indexes 只用于拼接证据文本；索引指向的事实未通过
    校验时，画像仍然写入，证据文本留空。
    """

    facts: List[ExtractedFactCandidate] = []
    evidence_by_index: Dict[int, str] = {}
    raw_facts = result.get("facts") if isinstance(result.get("facts"), list) else []
    for raw_index, raw_fact in enumerate(raw_facts):
        try:
            candidate = ExtractedFactCandidate.model_validate(raw_fact)
        except ValidationError:
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


# ---------------------------------------------------------------------------
# MemoryExtractor
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MemoryExtractionOutcome:
    """一次抽取的结果。调用方是 durable job，所以失败要抛，不要压成 False。"""

    facts_written: int = 0
    portraits_written: int = 0

    @property
    def wrote_anything(self) -> bool:
        return self.facts_written > 0 or self.portraits_written > 0


class MemoryExtractionFailed(RuntimeError):
    """抽取本身没跑成（模型调用或解析失败）。可重试。"""


class MemoryExtractor:
    """
    推理式记忆提取器。
    由 `background_jobs` 的 memory_extraction 任务调用，写入 memory_facts 和知识图谱。
    """

    async def extract_from_turn(
        self,
        user_id: str,
        session_id: str,
        user_msg: str,
        existing_portrait: str = "",
        source_message_id: str = "",
    ) -> MemoryExtractionOutcome:
        """从一轮对话中提取事实和画像并写入存储。

        `source_message_id` 是事实的幂等键来源：同一条来源消息抽出的同一句事实重复
        执行只入库一次。失败一律抛出，由 job 层决定重试还是死信。
        """
        if not user_msg:
            return MemoryExtractionOutcome()

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

            facts_written = 0
            portraits_written = 0

            if facts:
                from .memory_store import MemoryStore
                store = MemoryStore()
                for fact in facts:
                    fact_id = await store.save_fact(
                        user_id=user_id,
                        session_id=session_id,
                        content=fact.content.strip(),
                        category=fact.category,
                        importance=fact.importance,
                        source_message_id=source_message_id,
                    )
                    if fact_id is not None:
                        facts_written += 1

            # 图谱 upsert 与画像聚合都是可重算的：重复执行不会长出第二份画像。
            if portrait:
                from .memory_graph import MemoryGraph
                graph = MemoryGraph()
                await graph.update_portrait(
                    user_id=user_id,
                    portrait_items=portrait,
                    session_id=session_id,
                )
                portrait_text = await graph.aggregate_portrait(user_id)
                await graph.save_portrait_to_profile(user_id, portrait_text)
                portraits_written = len(portrait)

            # 事实已真正写入但没有可聚合 portrait 时，也要留下可追溯的真实用户画像。
            if facts_written and not portraits_written:
                from .user_profile import UserProfileMemory
                await UserProfileMemory().ensure_profile_for_write(user_id)
        except Exception as exc:
            stats.record_failure(exc.__class__.__name__)
            logger.warning(
                f"记忆抽取写入失败 user={user_id} session={session_id}: {exc}", exc_info=True
            )
            raise

        stats.record_success(facts=facts_written, portraits=portraits_written)
        outcome = MemoryExtractionOutcome(
            facts_written=facts_written,
            portraits_written=portraits_written,
        )
        if outcome.wrote_anything:
            logger.info(
                f"记忆抽取入库 user={user_id} session={session_id} "
                f"facts={facts_written} portrait={portraits_written}"
            )
        else:
            logger.debug(
                f"记忆抽取本轮无值可写 user={user_id} session={session_id}"
            )
        return outcome

    # -----------------------------------------------------------------------
    # 内部实现
    # -----------------------------------------------------------------------

    async def _call_llm(
        self,
        user_msg: str,
        existing_portrait: str,
    ) -> Optional[Dict[str, Any]]:
        """调用 fast model 提取事实和画像，返回解析后的字典（解析不出返回 None）。

        调用异常原样抛出：job 层要凭它区分「Provider 超时」与「答非所问」。
        """
        from ..llm.router import get_model_router
        router = get_model_router()
        llm = router.get_fast()

        # 截断过长内容，控制 token 消耗
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
