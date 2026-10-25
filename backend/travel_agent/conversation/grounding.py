"""Conversation grounding."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from travel_agent.conversation.information_annotations import (
    _best_effort_information_annotations,
)
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
import logging
import re


logger = logging.getLogger(__name__)


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class GroundingResult:
    """来源追踪与置信度评估结果"""

    confidence: ConfidenceLevel
    safety_disclaimer: str = ""
    processed_output: str = ""
    confidence_reasons: List[str] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    annotations: List[Dict[str, Any]] = field(default_factory=list)
    final_grounding: Dict[str, Any] = field(default_factory=dict)


_SOURCE_ANNOTATION_RE = re.compile(
    r"\[(?:来源|source|数据来源|ref|引用)\s*[:：]\s*([^\]]+)\]",
    re.IGNORECASE | re.UNICODE,
)


_RETIRED_FACT_MARKER_RE = re.compile(
    r"\[\[\s*fact\s*[:：]\s*(\d+)\s*\]\]", re.IGNORECASE
)


_MACHINE_ANNOTATION_RE = re.compile(
    r"\[\[\s*annotation\s*[:：]\s*([a-z0-9_-]+)\s*\]\]",
    re.IGNORECASE,
)


_RETIRED_INTERNAL_REFERENCE_RE = re.compile(
    r"\b(?:ev|claim)_[a-z0-9][a-z0-9_-]*\b", re.IGNORECASE
)


_USER_PLACEHOLDER_SENTENCE_RE = re.compile(
    r"[^。！？\n]*(?:"
    r"待确认|待核实|"
    r"(?:具体)?(?:价格|费用|时间|时长|日期|地点)(?:未知|不详|待定)"
    r")[。！？]?",
    re.IGNORECASE,
)


_USER_QUERY_HANDOFF_RE = re.compile(
    r"建议[^。！？\n]{0,160}(?:自行|通过[^。！？\n]{0,60})?查询[^。！？\n]*[。！？]?",
    re.IGNORECASE,
)


def _public_source(ev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """将已验证外部来源投影为可展示来源；裸内部 id 不构成用户来源。"""
    title = str(ev.get("title") or "").strip()
    source_name = str(ev.get("source_name") or ev.get("tool_name") or "").strip()
    url = str(ev.get("url") or "").strip()
    snippet = str(ev.get("snippet") or "").strip()
    if not (title or source_name or url or snippet):
        return None
    if title and _RETIRED_INTERNAL_REFERENCE_RE.fullmatch(title):
        title = ""
    if source_name and _RETIRED_INTERNAL_REFERENCE_RE.fullmatch(source_name):
        source_name = ""
    if not (title or source_name or url):
        return None
    return {
        "title": title,
        "url": url,
        "source_name": source_name,
        "snippet": snippet[:900],
        "authority_label": str(
            ev.get("source_authority_label") or ev.get("authority_label") or ""
        ).strip(),
        "retrieved_at": ev.get("retrieved_at"),
    }


def _clean_user_markdown(text: str) -> str:
    """最终防线：移除未解析机器标记和内部 id，并收紧清洗后的空白。"""
    cleaned = _SOURCE_ANNOTATION_RE.sub("", text)
    cleaned = _RETIRED_FACT_MARKER_RE.sub("", cleaned)
    cleaned = _MACHINE_ANNOTATION_RE.sub("", cleaned)
    cleaned = _RETIRED_INTERNAL_REFERENCE_RE.sub("", cleaned)
    cleaned = _USER_PLACEHOLDER_SENTENCE_RE.sub("", cleaned)
    cleaned = _USER_QUERY_HANDOFF_RE.sub("", cleaned)
    cleaned = cleaned.replace("据了解", "")
    cleaned = re.sub(r"[ \t]+([，。；：、,.!?])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _build_final_grounding(
    output_text: str,
    *,
    verified_claims: Dict[str, Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
) -> tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    """将当前 fact marker 转换为 cite contract，并拒绝旧引用形状。"""
    evidence_by_id = {
        str(ev.get("evidence_id")): ev
        for ev in evidence_records
        if isinstance(ev, dict) and ev.get("evidence_id")
    }
    ordered_claims = [
        (str(claim_id), claim)
        for claim_id, claim in sorted((verified_claims or {}).items())
        if isinstance(claim, dict)
    ]
    citations: List[Dict[str, Any]] = []
    citation_by_key: Dict[str, str] = {}
    contract_errors: List[str] = []
    if _SOURCE_ANNOTATION_RE.search(output_text):
        contract_errors.append("legacy_source_marker")
    if _RETIRED_INTERNAL_REFERENCE_RE.search(output_text):
        contract_errors.append("internal_evidence_or_claim_id")

    def ensure_citation(
        claim_id: str,
        claim: Optional[Dict[str, Any]],
        evidence_ids: List[str],
    ) -> str:
        public_sources = []
        usable_ids = []
        for evidence_id in evidence_ids:
            ev = evidence_by_id.get(str(evidence_id))
            if not ev:
                continue
            public = _public_source(ev)
            if public:
                usable_ids.append(str(evidence_id))
                public_sources.append(public)
        if not public_sources:
            return ""

        dedupe_key = claim_id or "|".join(usable_ids)
        existing = citation_by_key.get(dedupe_key)
        if existing:
            return f"[[cite:{existing}]]"

        citation_id = f"cite_{len(citations) + 1}"
        citation_by_key[dedupe_key] = citation_id
        citations.append(
            {
                "citation_id": citation_id,
                "claim_id": claim_id,
                "claim_text": str((claim or {}).get("claim_text") or "").strip(),
                "evidence_ids": usable_ids,
                "sources": public_sources,
            }
        )
        return f"[[cite:{citation_id}]]"

    def replace_fact(match: re.Match[str]) -> str:
        fact_index = int(match.group(1)) - 1
        if fact_index < 0 or fact_index >= len(ordered_claims):
            if "unknown_fact_marker" not in contract_errors:
                contract_errors.append("unknown_fact_marker")
            return ""
        claim_id, claim = ordered_claims[fact_index]
        evidence_ids = [
            str(item) for item in (claim.get("evidence_ids") or []) if str(item)
        ]
        return ensure_citation(claim_id, claim, evidence_ids)

    cleaned = _RETIRED_FACT_MARKER_RE.sub(replace_fact, output_text)

    cleaned = _clean_user_markdown(cleaned)
    cleaned, annotations = _best_effort_information_annotations(cleaned)

    claim_refs_used = [
        citation["claim_id"] for citation in citations if citation.get("claim_id")
    ]
    citation_map = {
        citation["citation_id"]: {
            "citation_status": "grounded",
            "claim_ref": citation.get("claim_id") or None,
            "evidence_refs": citation.get("evidence_ids") or [],
            "risk_refs": [],
        }
        for citation in citations
    }
    final_grounding = {
        "answer_markdown": cleaned,
        "citations": citations,
        "claim_refs_used": claim_refs_used,
        "citation_map": citation_map,
        "risk_refs_shown": [],
        "contract_errors": contract_errors,
        "annotations": annotations,
    }
    if contract_errors:
        logger.warning(
            "OutputGuard rejected output contract violations: %s", contract_errors
        )
    return cleaned, citations, final_grounding
