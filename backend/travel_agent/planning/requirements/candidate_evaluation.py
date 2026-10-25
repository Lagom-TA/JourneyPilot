"""Planning requirements candidate evaluation."""

from __future__ import annotations

from collections import defaultdict
from travel_agent.llm.task_routing import QualityFeedback
from travel_agent.llm.task_routing import TaskLLM
from travel_agent.llm.task_routing import with_quality_feedback
from travel_agent.planning.requirements.candidate_match_contracts import (
    CandidateIntentMatch,
)
from travel_agent.planning.requirements.candidate_match_contracts import (
    IntentMatchStatus,
)
from travel_agent.planning.requirements.intent_contracts import CategoryIntentValue
from travel_agent.planning.requirements.intent_contracts import IntentItem
from travel_agent.planning.requirements.intent_contracts import IntentKind
from travel_agent.planning.requirements.intent_contracts import IntentSpec
from travel_agent.planning.requirements.intent_contracts import IntentTarget
from travel_agent.planning.requirements.intent_contracts import ScalarIntentValue
from travel_agent.planning.requirements.intent_contracts import VerificationMode
from travel_agent.planning.requirements.intent_contracts import canonical_json_hash
from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.runtime.context import current_node
from travel_agent.runtime.context import current_run_id
from typing import Any
from typing import Mapping
from typing import Sequence
import json
import logging
import re


logger = logging.getLogger(__name__)



_ATTRIBUTE_FIELDS = (
    "provider_place_type",
    "visit_type",
    "cuisine_types",
    "recommended_dishes",
    "meal_type",
    "selected_mode",
    "transport_class",
    "room_type",
    "reservation_required",
    "opening_window",
    "address",
)


def check_attributes(entity) -> dict:
    return {
        field: getattr(entity, field)
        for field in _ATTRIBUTE_FIELDS
        if getattr(entity, field, None) is not None
    }


def explicit_category_match(name: str, attributes: dict, intent) -> bool | None:
    if isinstance(intent.value, CategoryIntentValue):
        categories = intent.value.categories
    elif isinstance(intent.value, ScalarIntentValue):
        categories = [intent.value.value]
    else:
        return None
    if name.casefold().strip() in {
        category.casefold().strip() for category in categories
    }:
        return True
    aliases = {
        "博物馆": "museum",
        "博物院": "museum",
        "museums": "museum",
        "公园": "park",
        "parks": "park",
        "海鲜": "seafood",
    }
    categories = [
        re.sub(
            r"^(?:不要|不去|避开|禁止|排除|avoid\s+|no\s+)",
            "",
            category.casefold().strip(),
        ).strip()
        for category in categories
    ]
    terms = {aliases.get(term, term) for term in categories}
    values = {
        str(value).casefold().strip()
        for key, raw in attributes.items()
        if key
        in {"provider_place_type", "visit_type", "cuisine_types", "selected_mode"}
        for value in (raw if isinstance(raw, list) else [raw])
    }
    values = {aliases.get(value, value) for value in values}
    if terms & values:
        return True

    if not re.search(r"不|无|非|not\b|without\b|no\b", name, re.I):
        name_class = None
        if re.search(r"(?:博物馆|博物院|\bmuseum)\s*$", name, re.I):
            name_class = "museum"
        elif re.search(r"(?:公园|\bpark)\s*$", name, re.I):
            name_class = "park"
        if name_class in terms:
            return True
        if name_class is not None and terms <= {"museum", "park"}:
            return False
    if values & {"museum", "park"} and terms <= {"museum", "park"}:
        return False
    return None


def _trace_scope() -> str:
    """当前执行上下文的归因串：交织的日志里靠它认出是谁打的。"""
    return f"run={current_run_id.get() or '-'} node={current_node.get() or '-'}"


INTENT_EVALUATION_POLICY_VERSION = "candidate_intent_evaluation.v2"


INTENT_EVALUATION_PROMPT_VERSION = "candidate_intent_evaluation.prompt.v1"


_KIND_TARGET = {
    "visit": IntentTarget.VISIT,
    "dining": IntentTarget.DINING,
    "lodging": IntentTarget.LODGING,
    "transport": None,
}


def _candidate_target(candidate: ResearchCandidate) -> IntentTarget:
    if candidate.candidate_kind != "transport":
        return _KIND_TARGET[candidate.candidate_kind]
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
) -> tuple[list[FactAssertion], list[str]]:
    facts = [
        fact
        for packet in catalog.research_packets
        for fact in packet.fact_assertions
        if fact.fact_assertion_id in candidate.fact_assertion_ids
        and fact.status == "verified"
    ]
    source_ids = list(candidate.source_record_ids)
    return facts, source_ids


def _not_applicable(candidate: ResearchCandidate, intent: IntentItem) -> bool:
    return intent.target not in {_candidate_target(candidate), IntentTarget.TRIP}


def _deterministic_match(
    *,
    candidate: ResearchCandidate,
    intent: IntentItem,
    facts: Sequence[FactAssertion],
    source_ids: Sequence[str],
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
    name = (
        getattr(candidate, "name", None)
        or getattr(candidate, "branch_name", None)
        or getattr(candidate, "property_name", "")
    )
    present = explicit_category_match(name, check_attributes(candidate), intent)
    matched_terms = _terms(intent) if present is True else []
    if not matched_terms:
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
        reason_code="candidate_category_classification",
        public_reason=f"依据地点名称或明确类别判断：{matched_terms[0]}",
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
        logger.info(
            "candidate batch quality repair model=%s", repair_llm.route.model_name
        )
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
        facts, source_ids = _candidate_evidence(catalog, candidate)
        for intent in intent_spec.active_items:
            deterministic = _deterministic_match(
                candidate=candidate,
                intent=intent,
                facts=facts,
                source_ids=source_ids,
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
                "candidates": list(candidate_payload.values()),
                "intents": list(intent_payload.values()),
                "evaluations": evaluation_pairs,
            }
            try:
                response = await _semantic_batch_call(
                    llm,
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
