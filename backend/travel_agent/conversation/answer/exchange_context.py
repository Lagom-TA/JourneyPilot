"""Conversation answer exchange context."""

from __future__ import annotations

import datetime
import json
import re
import uuid
from typing import Any, Dict, List, Optional

_CURRENCY_TOOL_NAME = "latest_exchange_rates"


_CURRENCY_CODES = {
    "AUD",
    "CAD",
    "CHF",
    "CNY",
    "EUR",
    "GBP",
    "HKD",
    "JPY",
    "KRW",
    "SGD",
    "THB",
    "USD",
}


_CURRENCY_ALIASES = {
    "CNY": ("人民币", "rmb", "cny", "cnh"),
    "JPY": ("日元", "日币", "日圓", "日圆", "yen", "jpy"),
    "USD": ("美元", "美金", "美刀", "usd", "dollar", "dollars"),
    "EUR": ("欧元", "eur", "euro", "euros"),
    "GBP": ("英镑", "gbp", "pound", "pounds"),
    "HKD": ("港币", "港元", "hkd"),
    "KRW": ("韩元", "krw"),
    "SGD": ("新币", "新加坡元", "sgd"),
    "THB": ("泰铢", "thb"),
    "AUD": ("澳元", "aud"),
    "CAD": ("加元", "cad"),
    "CHF": ("瑞郎", "瑞士法郎", "chf"),
}


_EXCHANGE_RATE_QUERY_RE = re.compile(
    r"(汇率|兑换|换算|兑|exchange\s*rate|currency|convert|conversion)",
    re.IGNORECASE,
)


_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")


_CN_DATE_RE = re.compile(r"(?<!\d)(\d{4})年(\d{1,2})月(\d{1,2})日")


def _detect_currency_pair(query: str) -> Optional[tuple[str, str]]:
    """Return (base, target) for common exchange-rate wording, or None."""
    if not query or not _EXCHANGE_RATE_QUERY_RE.search(query):
        return None

    hits: List[tuple[int, str]] = []
    upper_query = query.upper()
    for match in re.finditer(r"\b[A-Z]{3}\b", upper_query):
        code = match.group(0)
        if code in _CURRENCY_CODES:
            hits.append((match.start(), code))

    lowered = query.lower()
    for code, aliases in _CURRENCY_ALIASES.items():
        for alias in aliases:
            start = lowered.find(alias.lower())
            if start >= 0:
                hits.append((start, code))
                break

    ordered: List[str] = []
    for _, code in sorted(hits, key=lambda item: item[0]):
        if code not in ordered:
            ordered.append(code)
    if len(ordered) < 2:
        return None
    return ordered[0], ordered[1]


def _extract_requested_currency_date(query: str) -> Optional[str]:
    """Extract an explicit user date so latest FX cannot answer a dated query."""

    match = _ISO_DATE_RE.search(query) or _CN_DATE_RE.search(query)
    if match is None:
        return None
    try:
        return datetime.date(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        ).isoformat()
    except ValueError:
        return None


def _extract_mcp_text_payload(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("content"), list):
            for item in value["content"]:
                text = _extract_mcp_text_payload(item)
                if text:
                    return text
        if "result" in value:
            return _extract_mcp_text_payload(value["result"])
    if isinstance(value, list):
        for item in value:
            text = _extract_mcp_text_payload(item)
            if text:
                return text
    return ""


def _exchange_payload_from_envelope(
    envelope: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    sanitized = envelope.get("sanitized_result") if isinstance(envelope, dict) else None
    text = _extract_mcp_text_payload(sanitized)
    if not text:
        text = _extract_mcp_text_payload(
            envelope.get("result") if isinstance(envelope, dict) else None
        )
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _format_rate(value: float) -> str:
    if value >= 100:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if value >= 10:
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _build_exchange_realtime_context(
    *,
    query: str,
    base: str,
    target: str,
    envelope: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not envelope:
        return {
            "prompt": (
                "实时汇率工具不可用。用户询问当前汇率时，不要编造具体数字；"
                "只能说明暂时无法读取实时汇率，并建议以银行或支付渠道实时牌价为准。"
            ),
            "evidence": None,
        }

    status = str(envelope.get("status") or "")
    if status != "success":
        error = (
            envelope.get("error") or envelope.get("result_summary") or "unknown error"
        )
        if status in {"not_applicable", "reference_only"}:
            return {
                "prompt": (
                    f"该日期不适用于当前 latest 汇率工具（{error}）。"
                    "不要使用工具失败式措辞，也不要用最新汇率冒充指定日期事实；"
                    "直接说明当前工具只支持最新数据。"
                ),
                "evidence": None,
            }
        return {
            "prompt": (
                f"实时汇率工具调用失败（{error}）。用户询问当前汇率时，不要编造具体数字；"
                "只能说明暂时无法读取实时汇率，并建议以银行或支付渠道实时牌价为准。"
            ),
            "evidence": None,
        }

    data = _exchange_payload_from_envelope(envelope)
    rates = data.get("rates") if isinstance(data, dict) else None
    amount = data.get("amount", 1) if isinstance(data, dict) else 1
    rate_value = None
    if isinstance(rates, dict) and target in rates:
        try:
            rate_value = float(rates[target]) / float(amount or 1)
        except (TypeError, ValueError, ZeroDivisionError):
            rate_value = None
    if rate_value is None:
        return {
            "prompt": (
                "实时汇率工具返回了不可解析结果。用户询问当前汇率时，不要编造具体数字；"
                "只能说明暂时无法读取实时汇率，并建议以银行或支付渠道实时牌价为准。"
            ),
            "evidence": None,
        }

    date = str(data.get("date") or "").strip()
    retrieved_at = str(envelope.get("retrieved_at") or "").strip()
    source = "Frankfurter public exchange-rate API"
    rate_text = f"1 {base} = {_format_rate(rate_value)} {target}"
    evidence_id = f"ev_{envelope.get('audit_id') or uuid.uuid4().hex[:12]}"
    evidence = {
        "evidence_id": evidence_id,
        "source_type": "tool",
        "source_name": source,
        "tool_name": _CURRENCY_TOOL_NAME,
        "title": f"{rate_text} ({date or 'latest'})",
        "snippet": f"{rate_text}; date={date or 'latest'}; query={query}",
        "retrieved_at": retrieved_at,
        "freshness_status": "fresh",
        "authority_score": 0.82,
        "metadata": {
            "tool_audit_id": envelope.get("audit_id"),
            "tool_status": status,
            "untrusted_content": False,
            "trust_level": envelope.get("trust_level"),
        },
    }
    prompt = (
        "实时汇率工具结果（优先级高，请基于它回答）：\n"
        f"- 查询：{base} -> {target}\n"
        f"- 汇率：{rate_text}\n"
        f"- 数据日期：{date or 'latest'}\n"
        f"- 检索时间：{retrieved_at or 'unknown'}\n"
        f"- 来源：{source} via `{_CURRENCY_TOOL_NAME}`\n"
        "回答必须说明来源和日期；不要要求用户切换任何内部模式。"
    )
    return {"prompt": prompt, "evidence": evidence}
