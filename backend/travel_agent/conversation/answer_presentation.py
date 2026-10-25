"""Conversation answer presentation."""

from __future__ import annotations

from travel_agent.conversation.grounding import ConfidenceLevel
from travel_agent.conversation.grounding import GroundingResult
from travel_agent.conversation.grounding import _build_final_grounding
from typing import Any
from typing import Dict
from typing import List
from typing import Optional


class OutputGuard:
    """
    输出安全校验器。
    评估 LLM 输出的可信度，并追踪来源与局部信息状态。

    本门卫不承担文风审查，不按关键词删除旅行内容。来源和标签都是正向增强：
    只有真实绑定存在时才展示，增强失败时仍交付原始正文。
    """

    def check(
        self,
        output_text: str,
        retrieved_docs: Optional[List[Dict[str, Any]]] = None,
        evidence_records: Optional[List[Dict[str, Any]]] = None,
        tool_audit_events: Optional[List[Dict[str, Any]]] = None,
        risk_records: Optional[List[Dict[str, Any]]] = None,
        verified_claims: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> GroundingResult:
        """
        校验输出文本的可信度。

        Args:
            output_text: fast_answer 的原始输出
            retrieved_docs: RAG 检索结果列表

        Returns:
            GroundingResult，包含置信度评估和处理后的输出文本
        """
        evidence_records = evidence_records or []
        tool_audit_events = tool_audit_events or []
        risk_records = risk_records or []
        verified_claims = verified_claims or {}
        has_rag_data = bool(retrieved_docs)

        confidence, confidence_reasons = self._score_confidence(
            has_rag_data=has_rag_data,
            evidence_records=evidence_records,
            tool_audit_events=tool_audit_events,
            risk_records=risk_records,
        )

        cleaned_output, citations, final_grounding = _build_final_grounding(
            output_text,
            verified_claims=verified_claims,
            evidence_records=evidence_records,
        )

        processed_output = cleaned_output
        final_grounding["answer_markdown"] = processed_output

        return GroundingResult(
            confidence=confidence,
            safety_disclaimer="",
            processed_output=processed_output,
            confidence_reasons=confidence_reasons,
            citations=citations,
            annotations=list(final_grounding.get("annotations") or []),
            final_grounding=final_grounding,
        )

    def _score_confidence(
        self,
        *,
        has_rag_data: bool,
        evidence_records: List[Dict[str, Any]],
        tool_audit_events: List[Dict[str, Any]],
        risk_records: List[Dict[str, Any]],
    ) -> tuple[ConfidenceLevel, List[str]]:
        reasons: List[str] = []

        def _meta(ev: Dict[str, Any]) -> Dict[str, Any]:
            return ev.get("metadata") if isinstance(ev.get("metadata"), dict) else {}

        has_fresh_verified_tool = any(
            isinstance(ev, dict)
            and ev.get("source_type") == "tool"
            and (
                ev.get("freshness_status") in {"fresh", "unknown"}
                or not ev.get("freshness_status")
            )
            and not _meta(ev).get("untrusted_content")
            for ev in evidence_records
        )
        has_any_evidence = bool(evidence_records)
        stale = any(
            isinstance(ev, dict) and ev.get("freshness_status") == "stale"
            for ev in evidence_records
        )
        untrusted = any(
            isinstance(ev, dict) and _meta(ev).get("untrusted_content")
            for ev in evidence_records
        ) or any(
            isinstance(ev, dict) and ev.get("untrusted_content")
            for ev in tool_audit_events
        )
        quarantined = any(
            isinstance(ev, dict)
            and (_meta(ev).get("quarantine_result") or _meta(ev).get("quarantined"))
            for ev in evidence_records
        ) or any(
            isinstance(ev, dict)
            and (
                ev.get("quarantined")
                or ev.get("gateway_decision") == "quarantine_result"
            )
            for ev in tool_audit_events
        )
        unsupported_or_conflict = any(
            isinstance(r, dict)
            and str(r.get("risk_type") or "") in {"evidence", "conflict"}
            and str(r.get("status") or "open") == "open"
            for r in risk_records
        )
        freshness_risk = any(
            isinstance(r, dict) and str(r.get("risk_type") or "") == "freshness"
            for r in risk_records
        )

        if stale or freshness_risk:
            reasons.append("stale_evidence")
        if untrusted:
            reasons.append("untrusted_tool_content")
        if quarantined:
            reasons.append("tool_result_quarantined")
        if unsupported_or_conflict:
            reasons.append("unsupported_or_conflict")

        if has_fresh_verified_tool and not reasons:
            return ConfidenceLevel.HIGH, ["fresh_verified_tool_evidence"]
        if has_any_evidence or has_rag_data:
            if (
                "tool_result_quarantined" in reasons
                or "unsupported_or_conflict" in reasons
            ):
                return ConfidenceLevel.LOW, reasons
            return ConfidenceLevel.MEDIUM, reasons or ["external_grounding"]
        return ConfidenceLevel.LOW, reasons or ["no_external_grounding"]


SOURCE_TRACKING_INSTRUCTION = """

已验证结论会以「事实 1」「事实 2」这类本轮局部编号提供。正文使用某条可核验事实时，
紧跟一个机器标记，例如 [[fact:1]]；同一句使用多个来源支持的同一事实时仍只标一次。
不要输出 [来源: xxx]、URL、evidence id、claim id 或任何 ev_/claim_ 内部标识；系统会把机器标记转换为可点击角标。
对于价格、距离、营业时间、班次、酒店、天气、签证/入境等可能变化的信息，只在上方数据中存在可追溯依据时写入具体值；否则直接省略，不要生成统一的“建议确认”或“来源不足”提醒。

行程的顺序、节奏和区域组合属于规划建议，可以自然表达而无需逐条引用。不得使用自己的训练知识补写可能过时的具体事实。"""
