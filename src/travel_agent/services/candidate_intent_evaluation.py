from __future__ import annotations

import json
import logging
import re
from ..models.task_routing import TaskLLM, QualityFeedback, with_quality_feedback

from collections import defaultdict
from typing import Any, Mapping, Sequence

from ..entities.candidate_intent import CandidateIntentMatch, IntentMatchStatus
from ..entities.delivery_bundle import (
    FactAssertion,
    RecommendationCatalog,
    ResearchCandidate,
)
from ..entities.intent_spec import (
    CategoryIntentValue,
    IntentItem,
    IntentKind,
    IntentSpec,
    IntentTarget,
    VerificationMode,
    canonical_json_hash,
)
from ..workflows.run_control import current_node, current_run_id

logger = logging.getLogger(__name__)

# 这个模块的三条静默降级路径共用的归因前缀。
#
# 为什么必须带轮次/身份而不只是打一句「解析失败」：这张图有修复回边、有并发扇出，
# 一条 backend.log 里三个 worker 的输出会交织。run_id 与 node 从
# `workflows/run_control` 的 contextvar 取（低层调用点拿不到 TravelAgentState，
# 这两个 contextvar 就是为此存在的），domain 与本轮规模从本地作用域取。
#
# 缺口，写在这里而不是留给下一个人猜：**每个域的 attempt 计数拿不到**。它在
# `TravelAgentState.candidate_gate_attempts`（entities/state.py:385）上，只有调用方
# `agents/orchestrator/candidate_gate.py` 手里有；为了记日志给
# `evaluate_candidate_intents` 新增一个参数穿透进来不值得，所以这里用
# run_id + node + domain 定位到「哪一次节点执行的哪个域」，同一 run 里同一 node 的
# 多轮之间靠日志的时间顺序区分。


def _trace_scope() -> str:
    """当前执行上下文的归因串：交织的日志里靠它认出是谁打的。"""
    return f"run={current_run_id.get() or '-'} node={current_node.get() or '-'}"


INTENT_EVALUATION_POLICY_VERSION = "candidate_intent_evaluation.v1"
INTENT_EVALUATION_PROMPT_VERSION = "candidate_intent_evaluation.prompt.v1"


_KIND_TARGET = {
    "visit": IntentTarget.VISIT,
    "dining": IntentTarget.DINING,
    "lodging": IntentTarget.LODGING,
    "transport": None,
}


def _candidate_target(candidate: ResearchCandidate) -> IntentTarget:
    if candidate.candidate_kind != "transport":
        return _KIND_TARGET[candidate.candidate_kind]  # type: ignore[return-value]
    return (
        IntentTarget.LONG_DISTANCE_TRANSPORT
        if candidate.transport_class == "long_distance"
        else IntentTarget.LOCAL_TRANSPORT
    )


def _terms(intent: IntentItem) -> list[str]:
    if isinstance(intent.value, CategoryIntentValue):
        values = intent.value.categories
    else:
        values = [intent.public_summary]
    terms: list[str] = []
    for value in values:
        normalized = value.casefold().strip()
        normalized = re.sub(
            r"^(?:不要|不去|避开|禁止|排除|avoid\s+|no\s+)",
            "",
            normalized,
        ).strip()
        if normalized:
            terms.append(normalized)
    return terms


def _candidate_evidence(
    catalog: RecommendationCatalog,
    candidate: ResearchCandidate,
) -> tuple[list[FactAssertion], list[str], str]:
    facts = [
        fact
        for packet in catalog.research_packets
        for fact in packet.fact_assertions
        if fact.fact_assertion_id in candidate.fact_assertion_ids
        and fact.status == "verified"
    ]
    source_ids = list(candidate.source_record_ids)
    searchable = json.dumps(
        {
            "candidate": candidate.model_dump(mode="json"),
            "facts": [
                {
                    "field_path": fact.field_path,
                    "asserted_value": fact.asserted_value,
                }
                for fact in facts
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).casefold()
    return facts, source_ids, searchable


def _not_applicable(candidate: ResearchCandidate, intent: IntentItem) -> bool:
    return intent.target not in {_candidate_target(candidate), IntentTarget.TRIP}


def _deterministic_match(
    *,
    candidate: ResearchCandidate,
    intent: IntentItem,
    facts: Sequence[FactAssertion],
    source_ids: Sequence[str],
    searchable: str,
) -> CandidateIntentMatch | None:
    if _not_applicable(candidate, intent):
        return CandidateIntentMatch(
            candidate_id=candidate.candidate_id,
            intent_id=intent.intent_id,
            status=IntentMatchStatus.NOT_APPLICABLE,
            method="deterministic",
            reason_code="intent_target_not_applicable",
        )
    if (
        intent.kind
        not in {
            IntentKind.MUST_INCLUDE,
            IntentKind.MUST_EXCLUDE,
            IntentKind.ATTRIBUTE_PREFERENCE,
            IntentKind.GEOGRAPHIC,
            IntentKind.TIME_WINDOW,
        }
        or intent.verification_mode is VerificationMode.SEMANTIC
    ):
        return None
    matched_terms = [term for term in _terms(intent) if term in searchable]
    if not matched_terms:
        # Exact evidence matching is a cheap proof, not a semantic parser.  The
        # IntentSpec has already been authored by the LLM; when its canonical
        # category and the Provider's typed value use different languages or
        # vocabularies (for example a localized request and an enum value), let
        # the bounded structured semantic evaluator decide.  With no model this
        # still resolves to UNKNOWN below, so the safety boundary is unchanged.
        #
        # DEBUG 而不是 WARNING：上面那段注释说的是设计意图，这条移交本身是正常
        # 路径，只是发生时原来不留痕。本轮规模在这里拿不到（这个函数一次只看一对
        # 候选×intent），它由调用方那条按域打的 DEBUG 给出。
        logger.debug(
            "candidate intent deferred to semantic evaluator | %s domain=%s "
            "candidate=%s intent=%s kind=%s",
            _trace_scope(),
            _candidate_target(candidate).value,
            candidate.candidate_id,
            intent.intent_id,
            intent.kind.value,
        )
        return None
    status = (
        IntentMatchStatus.VIOLATED
        if intent.kind is IntentKind.MUST_EXCLUDE
        else IntentMatchStatus.MATCHED
    )
    return CandidateIntentMatch(
        candidate_id=candidate.candidate_id,
        intent_id=intent.intent_id,
        status=status,
        score=0.0 if status is IntentMatchStatus.VIOLATED else 1.0,
        method="deterministic",
        supporting_fact_assertion_ids=[fact.fact_assertion_id for fact in facts],
        supporting_source_record_ids=list(source_ids),
        reason_code=(
            "excluded_category_present"
            if status is IntentMatchStatus.VIOLATED
            else "verified_candidate_attribute_match"
        ),
        public_reason=(
            f"已验证信息包含：{matched_terms[0]}" if matched_terms else None
        ),
    )


def _cache_key(
    intent: IntentItem,
    candidate: ResearchCandidate,
    facts: Sequence[FactAssertion],
    *,
    model_version: str,
) -> str:
    return canonical_json_hash(
        {
            "intent": intent.model_dump(mode="json"),
            "candidate_id": candidate.candidate_id,
            "candidate_facts": [fact.model_dump(mode="json") for fact in facts],
            "policy_version": INTENT_EVALUATION_POLICY_VERSION,
            "model_version": model_version,
            "prompt_version": INTENT_EVALUATION_PROMPT_VERSION,
        }
    )


async def _semantic_batch_call(llm, messages, **kwargs):
    response = await llm.ainvoke(messages, **kwargs)
    if not isinstance(llm, TaskLLM):
        return response
    try:
        content = response.content if hasattr(response, "content") else response
        parsed = json.loads(content)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("matches"), list):
            raise ValueError("missing matches array")
    except (ValueError, TypeError):
        repair_llm = with_quality_feedback(llm, QualityFeedback(schema_failures=1))
        logger.info("candidate batch quality repair model=%s", repair_llm.route.model_name)
        return await repair_llm.ainvoke(messages, **kwargs)
    return response


async def evaluate_candidate_intents(
    *,
    catalog: RecommendationCatalog,
    intent_spec: IntentSpec,
    llm: Any | None = None,
    cache: Mapping[str, CandidateIntentMatch] | None = None,
    model_version: str = "fast",
) -> tuple[list[CandidateIntentMatch], dict[str, CandidateIntentMatch]]:
    cache_out = dict(cache or {})
    matches: list[CandidateIntentMatch] = []
    semantic_batches: dict[
        str, list[tuple[ResearchCandidate, IntentItem, list[FactAssertion], list[str]]]
    ] = defaultdict(list)

    candidates = catalog.candidate_index()
    source_index = {
        source.source_record_id: source
        for packet in catalog.research_packets
        for source in packet.source_records
    }
    for candidate in candidates.values():
        facts, source_ids, searchable = _candidate_evidence(catalog, candidate)
        for intent in intent_spec.active_items:
            deterministic = _deterministic_match(
                candidate=candidate,
                intent=intent,
                facts=facts,
                source_ids=source_ids,
                searchable=searchable,
            )
            if deterministic is not None:
                matches.append(deterministic)
                continue
            if (
                _not_applicable(candidate, intent)
                or "ranking" not in intent.impact_stages
            ):
                matches.append(
                    CandidateIntentMatch(
                        candidate_id=candidate.candidate_id,
                        intent_id=intent.intent_id,
                        status=IntentMatchStatus.NOT_APPLICABLE,
                        method="deterministic",
                        reason_code="intent_not_ranked_for_candidate",
                    )
                )
                continue
            key = _cache_key(intent, candidate, facts, model_version=model_version)
            if key in cache_out:
                matches.append(cache_out[key])
                continue
            semantic_batches[_candidate_target(candidate).value].append(
                (candidate, intent, facts, source_ids)
            )

    for domain, batch in semantic_batches.items():
        unresolved = {
            (candidate.candidate_id, intent.intent_id): (
                candidate,
                intent,
                facts,
                source_ids,
            )
            for candidate, intent, facts, source_ids in batch
        }
        response_rows: list[dict[str, Any]] = []
        # 本域这一轮的规模。上面那条按对打的 DEBUG 说的是「哪一对移交了」，这条说
        # 的是「这一轮一共有多大」——两条合起来才能把交织的日志归因到某一轮某个域。
        logger.debug(
            "candidate intent semantic batch | %s domain=%s pairs=%d "
            "candidates=%d intents=%d llm=%s",
            _trace_scope(),
            domain,
            len(batch),
            len({item[0].candidate_id for item in batch}),
            len({item[1].intent_id for item in batch}),
            "yes" if llm is not None else "no",
        )
        if llm is not None and batch:
            allowed_fact_ids = sorted(
                {
                    fact.fact_assertion_id
                    for _candidate, _intent, facts, _source_ids in batch
                    for fact in facts
                }
            )
            allowed_source_ids = sorted(
                {
                    source_id
                    for _candidate, _intent, _facts, source_ids in batch
                    for source_id in source_ids
                }
            )
            schema = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "matches": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "candidate_id": {
                                    "type": "string",
                                    "enum": sorted(
                                        {item[0].candidate_id for item in batch}
                                    ),
                                },
                                "intent_id": {
                                    "type": "string",
                                    "enum": sorted(
                                        {item[1].intent_id for item in batch}
                                    ),
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["matched", "not_matched", "unknown"],
                                },
                                "score": {
                                    "type": ["number", "null"],
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "supporting_fact_assertion_ids": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                        "enum": allowed_fact_ids,
                                    },
                                },
                                "supporting_source_record_ids": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                        "enum": allowed_source_ids,
                                    },
                                },
                                "reason_code": {"type": "string"},
                                "public_reason": {"type": ["string", "null"]},
                            },
                            "required": [
                                "candidate_id",
                                "intent_id",
                                "status",
                                "score",
                                "supporting_fact_assertion_ids",
                                "supporting_source_record_ids",
                                "reason_code",
                                "public_reason",
                            ],
                        },
                    }
                },
                "required": ["matches"],
            }
            candidate_payload: dict[str, dict[str, Any]] = {}
            intent_payload: dict[str, dict[str, Any]] = {}
            evaluation_pairs: list[dict[str, str]] = []
            for candidate, intent, facts, source_ids in batch:
                candidate_payload.setdefault(
                    candidate.candidate_id,
                    {
                        "candidate_id": candidate.candidate_id,
                        "candidate": candidate.model_dump(mode="json"),
                        "facts": [fact.model_dump(mode="json") for fact in facts],
                        "sources": [
                            {
                                "source_record_id": source_id,
                                "title": source_index[source_id].title,
                                "public_excerpt": source_index[
                                    source_id
                                ].public_excerpt,
                            }
                            for source_id in source_ids
                            if source_id in source_index
                        ],
                    },
                )
                intent_payload.setdefault(
                    intent.intent_id,
                    {
                        "intent_id": intent.intent_id,
                        "kind": intent.kind.value,
                        "target": intent.target.value,
                        "summary": intent.public_summary,
                        "value": intent.value.model_dump(mode="json"),
                    },
                )
                evaluation_pairs.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "intent_id": intent.intent_id,
                    }
                )
            payload = {
                "domain": domain,
                # Candidate evidence and intent semantics are each serialized
                # once.  The old row-per-pair shape repeated a full candidate,
                # every fact and every source for every intent in the batch.
                "candidates": list(candidate_payload.values()),
                "intents": list(intent_payload.values()),
                "evaluations": evaluation_pairs,
            }
            try:
                response = await _semantic_batch_call(llm,
                    [
                        {
                            "role": "system",
                            "content": (
                                "只根据给定候选事实批量判断结构化意图。"
                                "evaluations 中每一对必须恰好返回一行；"
                                "没有直接证据必须返回 unknown，不得补写属性。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                payload,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        },
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "candidate_intent_batch_evaluation",
                            "strict": True,
                            "schema": schema,
                        },
                    },
                    temperature=0,
                )
                content = response.content if hasattr(response, "content") else response
                parsed = json.loads(
                    content if isinstance(content, str) else json.dumps(content)
                )
                if isinstance(parsed, dict) and isinstance(parsed.get("matches"), list):
                    response_rows = [
                        row for row in parsed["matches"] if isinstance(row, dict)
                    ]
            except Exception as exc:
                # 这一条最该记：整批响应被吞成「没有任何行」，本域下面每个候选都会
                # 落 UNKNOWN，而在结果里这和「模型确实答不出」长得一模一样。异常
                # 类型与摘要必须进日志，否则连「是超时还是 schema 不合」都分不出。
                logger.warning(
                    "candidate intent semantic batch unparsed | %s domain=%s "
                    "pairs=%d candidates=%d intents=%d error=%s: %s",
                    _trace_scope(),
                    domain,
                    len(batch),
                    len({item[0].candidate_id for item in batch}),
                    len({item[1].intent_id for item in batch}),
                    type(exc).__name__,
                    str(exc)[:200],
                )
                response_rows = []

        rows_by_key = {
            (str(row.get("candidate_id") or ""), str(row.get("intent_id") or "")): row
            for row in response_rows
        }
        for pair, (candidate, intent, facts, source_ids) in unresolved.items():
            fact_ids = {fact.fact_assertion_id for fact in facts}
            allowed_sources = set(source_ids)
            row = rows_by_key.get(pair)
            status = str((row or {}).get("status") or "unknown")
            if status not in {"matched", "not_matched", "unknown"}:
                status = "unknown"
            supporting_facts = [
                value
                for value in (row or {}).get("supporting_fact_assertion_ids") or []
                if value in fact_ids
            ]
            supporting_sources = [
                value
                for value in (row or {}).get("supporting_source_record_ids") or []
                if value in allowed_sources
            ]
            if status in {"matched", "not_matched"} and not (
                supporting_facts or supporting_sources
            ):
                status = "unknown"
            if status == "matched" and intent.kind is IntentKind.MUST_EXCLUDE:
                status = "violated"
            score = None
            if row is not None and row.get("score") is not None and status != "unknown":
                try:
                    parsed_score = float(row["score"])
                except (TypeError, ValueError) as exc:
                    # -1.0 是个哨兵：它让下面的 0.0 <= x <= 1.0 不成立，于是 score
                    # 保持 None，模型给的分数被丢掉。状态照旧保留，所以这次降级在
                    # 结果里完全看不出来 —— 只能从这里看出来。
                    logger.warning(
                        "candidate intent score unparsed | %s domain=%s "
                        "pairs=%d candidate=%s intent=%s error=%s: %s",
                        _trace_scope(),
                        domain,
                        len(batch),
                        candidate.candidate_id,
                        intent.intent_id,
                        type(exc).__name__,
                        str(exc)[:200],
                    )
                    parsed_score = -1.0
                if 0.0 <= parsed_score <= 1.0:
                    score = 0.0 if status == "violated" else parsed_score
            match = CandidateIntentMatch(
                candidate_id=candidate.candidate_id,
                intent_id=intent.intent_id,
                status=IntentMatchStatus(status),
                score=score,
                method="semantic_batch_evaluation",
                supporting_fact_assertion_ids=supporting_facts,
                supporting_source_record_ids=supporting_sources,
                reason_code=str(
                    (row or {}).get("reason_code") or "semantic_evidence_unavailable"
                ),
                public_reason=(
                    str(row.get("public_reason"))[:300]
                    if row is not None and row.get("public_reason")
                    else None
                ),
            )
            matches.append(match)
            cache_out[
                _cache_key(intent, candidate, facts, model_version=model_version)
            ] = match

    matches.sort(key=lambda item: (item.candidate_id, item.intent_id))
    return matches, cache_out
