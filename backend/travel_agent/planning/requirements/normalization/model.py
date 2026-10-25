"""Planning requirements normalization model."""

from __future__ import annotations

from openai import OpenAIError
from pydantic import ValidationError
from travel_agent.llm.task_routing import QualityFeedback
from travel_agent.llm.task_routing import with_quality_feedback
from travel_agent.planning.requirements.normalization.clauses import logger
from travel_agent.planning.requirements.normalization.contracts import (
    NormalizedClauseDraft,
)
from travel_agent.planning.requirements.normalization.contracts import (
    RequestContractNormalizationResult,
)
from travel_agent.planning.requirements.normalization.contracts import SourceClause
from travel_agent.planning.requirements.normalization.deterministic import (
    _validate_model_contract,
)
from travel_agent.planning.requirements.normalization.fallback import (
    _fallback_normalization,
)
from travel_agent.planning.requirements.normalization.prompts import (
    _normalization_prompt,
)
from travel_agent.planning.requirements.normalization.prompts import (
    _normalization_response_format,
)
from travel_agent.planning.requirements.normalization.prompts import (
    _normalization_targeted_retry_prompt,
)
from travel_agent.utils.json_helpers import safe_parse_json
from typing import Dict
from typing import List
import asyncio


INTENT_NORMALIZATION_PROMPT_VERSION = "request_contract_normalization.v1"


INTENT_NORMALIZATION_CALL_TIMEOUT_SECONDS = 120.0


INTENT_NORMALIZATION_OPERATION_TIMEOUT_SECONDS = 240.0


async def normalize_clauses(
    *,
    clauses: List[SourceClause],
    controlled_identity: Dict[str, object],
    llm: object,
) -> RequestContractNormalizationResult:
    if not clauses:
        raise ValueError("request normalization requires at least one clause")
    capabilities = getattr(llm, "capabilities", None)
    supports_native_schema = bool(getattr(capabilities, "supports_json_schema", False))
    accepted: Dict[str, NormalizedClauseDraft] = {}
    pending = list(clauses)
    messages = _normalization_prompt(pending, controlled_identity)
    last_error: Exception | None = None
    loop = asyncio.get_running_loop()
    operation_deadline = loop.time() + INTENT_NORMALIZATION_OPERATION_TIMEOUT_SECONDS
    for attempt in range(3):
        if attempt:
            llm = with_quality_feedback(llm, QualityFeedback(schema_failures=attempt))
            supports_native_schema = bool(
                getattr(
                    getattr(llm, "capabilities", None), "supports_json_schema", False
                )
            )
        remaining_seconds = operation_deadline - loop.time()
        if remaining_seconds <= 0:
            last_error = TimeoutError(
                "request contract normalization operation budget exhausted"
            )
            break
        response_format = _normalization_response_format(
            pending,
            supports_native_schema=supports_native_schema,
        )
        try:
            raw = await asyncio.wait_for(
                llm.ainvoke(
                    messages,
                    response_format=response_format,
                    temperature=0,
                ),
                timeout=min(
                    INTENT_NORMALIZATION_CALL_TIMEOUT_SECONDS,
                    remaining_seconds,
                ),
            )
            parsed = safe_parse_json(raw, strip_think_tags=True)
            newly_accepted, validation_errors = _validated_model_clause_rows(
                parsed,
                pending,
            )
            accepted.update(newly_accepted)
            pending = [clause for clause in pending if clause.clause_id not in accepted]
            if not pending:
                result = RequestContractNormalizationResult(
                    clauses=[accepted[clause.clause_id] for clause in clauses]
                )
                _validate_clause_coverage(result, clauses)
                return result
            last_error = ValueError("; ".join(validation_errors)[:2400])
            if attempt < 2:
                logger.info(
                    "request contract model normalization partially rejected; "
                    "requesting targeted semantic repair | accepted=%d pending=%d "
                    "error=%s",
                    len(newly_accepted),
                    len(pending),
                    str(last_error)[:800],
                )
                messages = _normalization_targeted_retry_prompt(
                    clauses=pending,
                    controlled_identity=controlled_identity,
                    error=last_error,
                )
                continue
        except asyncio.TimeoutError as exc:
            last_error = exc
            remaining_seconds = operation_deadline - loop.time()
            if attempt < 2 and remaining_seconds > 0:
                logger.info(
                    "request contract model normalization timed out; requesting "
                    "fresh semantic regeneration | remaining_seconds=%.1f",
                    remaining_seconds,
                )
                messages = _normalization_targeted_retry_prompt(
                    clauses=pending,
                    controlled_identity=controlled_identity,
                    error=TimeoutError(
                        "the previous semantic normalization exceeded its call budget"
                    ),
                )
                continue
            break
        except (
            OpenAIError,
            TypeError,
            ValueError,
            RuntimeError,
        ) as exc:
            last_error = exc
            if attempt < 2:
                logger.info(
                    "request contract model normalization unavailable; requesting "
                    "targeted semantic retry | pending=%d error_type=%s error=%s",
                    len(pending),
                    type(exc).__name__,
                    str(exc)[:800],
                )
                messages = _normalization_targeted_retry_prompt(
                    clauses=pending,
                    controlled_identity=controlled_identity,
                    error=exc,
                )
                continue
    logger.warning(
        "request contract model normalization failed for %d clause(s) after "
        "semantic repair; using clause-scoped deterministic fallback | "
        "error_type=%s error=%s",
        len(pending),
        type(last_error).__name__ if last_error is not None else "unknown",
        str(last_error)[:800] if last_error is not None else "",
    )
    fallback = _fallback_normalization(pending, controlled_identity)
    fallback_by_id = {draft.clause_id: draft for draft in fallback.clauses}
    return RequestContractNormalizationResult(
        clauses=[
            accepted.get(clause.clause_id) or fallback_by_id[clause.clause_id]
            for clause in clauses
        ]
    )


def _validated_model_clause_rows(
    parsed: object,
    clauses: List[SourceClause],
) -> tuple[Dict[str, NormalizedClauseDraft], List[str]]:
    """Salvage independently valid LLM rows without authoring any semantics."""

    if isinstance(parsed, dict):
        rows = parsed.get("clauses")
    elif isinstance(parsed, list):
        rows = parsed
    else:
        rows = None
    if not isinstance(rows, list):
        root_shape = (
            f"object keys {sorted(str(key) for key in parsed)}"
            if isinstance(parsed, dict)
            else type(parsed).__name__
        )
        raise ValueError(
            "normalizer root must be a clause array or contain a clauses array; "
            f"received {root_shape}"
        )
    rows_by_id: Dict[str, List[object]] = {}
    for row in rows:
        clause_id = str(row.get("clause_id") or "") if isinstance(row, dict) else ""
        rows_by_id.setdefault(clause_id, []).append(row)

    accepted: Dict[str, NormalizedClauseDraft] = {}
    errors: List[str] = []
    for source in clauses:
        matches = rows_by_id.get(source.clause_id, [])
        if len(matches) != 1:
            errors.append(
                f"{source.clause_id}: expected one row, received {len(matches)}"
            )
            continue
        try:
            draft = NormalizedClauseDraft.model_validate(matches[0])
            one = RequestContractNormalizationResult(clauses=[draft])
            _validate_clause_coverage(one, [source])
            _validate_model_contract(one, [source])
        except (ValidationError, TypeError, ValueError) as exc:
            errors.append(f"{source.clause_id}: {type(exc).__name__}: {str(exc)[:500]}")
            continue
        accepted[source.clause_id] = draft
    unknown_ids = sorted(
        clause_id
        for clause_id in rows_by_id
        if clause_id and clause_id not in {clause.clause_id for clause in clauses}
    )
    if unknown_ids:
        errors.append(f"unknown clause ids: {unknown_ids}")
    return accepted, errors


def _validate_clause_coverage(
    result: RequestContractNormalizationResult, clauses: List[SourceClause]
) -> None:
    expected = [item.clause_id for item in clauses]
    actual = [item.clause_id for item in result.clauses]
    if actual != expected:
        raise ValueError("normalizer must return every clause once and in source order")
