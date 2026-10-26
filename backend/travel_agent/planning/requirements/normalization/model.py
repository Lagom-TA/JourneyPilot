"""请求合同归一化：一次结构化模型调用，未通过校验的行由确定性 fallback 补齐。"""

from __future__ import annotations

from openai import OpenAIError
from pydantic import ValidationError
from travel_agent.planning.requirements.normalization.clauses import logger
from travel_agent.planning.requirements.normalization.contracts import (
    NormalizedClauseDraft,
)
from travel_agent.planning.requirements.normalization.contracts import (
    RequestContractNormalizationResult,
)
from travel_agent.planning.requirements.normalization.contracts import SourceClause
from travel_agent.planning.requirements.normalization.fallback import (
    _fallback_normalization,
)
from travel_agent.planning.requirements.normalization.prompts import (
    _normalization_prompt,
)
from travel_agent.planning.requirements.normalization.prompts import (
    _normalization_response_format,
)
from travel_agent.utils.json_helpers import safe_parse_json
from typing import Dict
from typing import List
import asyncio


INTENT_NORMALIZATION_PROMPT_VERSION = "request_contract_normalization.v1"


INTENT_NORMALIZATION_CALL_TIMEOUT_SECONDS = 120.0


async def normalize_clauses(
    *,
    clauses: List[SourceClause],
    controlled_identity: Dict[str, object],
    llm: object,
) -> RequestContractNormalizationResult:
    """调用一次结构化模型，逐行做 Pydantic 校验；未通过的行走确定性 fallback。"""
    if not clauses:
        raise ValueError("request normalization requires at least one clause")
    capabilities = getattr(llm, "capabilities", None)
    supports_native_schema = bool(getattr(capabilities, "supports_json_schema", False))
    response_format = _normalization_response_format(
        clauses,
        supports_native_schema=supports_native_schema,
    )

    accepted: Dict[str, NormalizedClauseDraft] = {}
    last_error: Exception | None = None
    try:
        raw = await asyncio.wait_for(
            llm.ainvoke(
                _normalization_prompt(clauses, controlled_identity),
                response_format=response_format,
                temperature=0,
            ),
            timeout=INTENT_NORMALIZATION_CALL_TIMEOUT_SECONDS,
        )
        parsed = safe_parse_json(raw, strip_think_tags=True)
        accepted, validation_errors = _validated_model_clause_rows(parsed, clauses)
        if validation_errors:
            last_error = ValueError("; ".join(validation_errors)[:2400])
    except (
        asyncio.TimeoutError,
        OpenAIError,
        TypeError,
        ValueError,
        RuntimeError,
    ) as exc:
        last_error = exc

    pending = [clause for clause in clauses if clause.clause_id not in accepted]
    if not pending:
        return RequestContractNormalizationResult(
            clauses=[accepted[clause.clause_id] for clause in clauses]
        )

    logger.warning(
        "request contract model normalization incomplete; using clause-scoped "
        "deterministic fallback | accepted=%d pending=%d error_type=%s error=%s",
        len(accepted),
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
    """逐行做 Pydantic 校验，返回通过的草稿与逐行错误说明。"""

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
