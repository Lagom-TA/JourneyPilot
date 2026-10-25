"""Planning requirements constraints extraction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from travel_agent.planning.requirements.constraints.items import (
    _HARD_HINTS,
    _normalize_category,
)
from travel_agent.planning.requirements.constraints.parameters import (
    _LOCAL_MODE_AVOID_HINTS,
    _LOCAL_MODE_LOCK_HINTS,
    _LOCAL_MODE_PREFER_HINTS,
    _budget_amount_param,
    _canonical_accommodation_params,
    _canonical_mobility_params,
    _canonical_transport_mode_params,
    _canonical_transport_params,
)
from travel_agent.planning.requirements.constraints.resolution import (
    _merge_constraint_params,
)
from travel_agent.utils.json_helpers import safe_parse_json

_EXTRACT_SYSTEM_PROMPT = (
    "你是个人出行约束抽取器。从给定文本项中识别用户的真实出行约束，"
    "归类为以下类别之一：food_allergy（食物过敏）、budget_cap（预算上限）、"
    "elderly_mobility（老人行动能力）、child_friendly（儿童友好）、"
    "transport_constraint（交通禁忌/偏好）、accommodation_preference（住宿偏好）、"
    "pace_preference（节奏偏好）、destination_preference（目的地偏好）、"
    "dietary_restriction（饮食限制）、health_condition（健康状况）、other（其他）。"
    "只抽取文本中真实存在的约束，不臆造、不推断未表达的约束。"
    "为每项产出简洁的 canonical value（可直接作「已考虑 X」标签）；"
    "对 budget_cap 抽 params {amount, currency, per}，amount 只能是数值或 null；"
    "「经济」「中等」「适中」「奢华」这类档位描述词不是数值，amount 必须写 null，"
    "把档位措辞留在 value 里；"
    "对 food_allergy 抽 params {allergens: []}；"
    "对 transport_constraint 抽 params {avoid_overnight, earliest_departure_local, "
    "latest_arrival_local, preferred_local_modes, excluded_local_modes, locked_local_mode}；"
    "对 accommodation_preference 抽 params {required_facilities: []}；"
    "对 elderly_mobility/health_condition 抽 params {max_continuous_walk_minutes, "
    "avoid_long_stairs, prefer: [], unknown_facility_policy}。"
    "时间使用 HH:MM，设施和偏好使用英文 canonical token；未表达的字段不要补。"
    "只输出 JSON，不要解释。"
)


@dataclass
class ConstraintExtractionResult:
    """自由文本约束抽取结果，显式区分 LLM、fallback 与缺失来源。"""

    llm_items: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    fallback_items: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    items: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    missing_sources: List[str] = field(default_factory=list)
    partial_reasons: List[str] = field(default_factory=list)

    def items_for(self, source_id: str) -> List[Dict[str, Any]]:
        """这一条自由文本进 pack 的那一份 —— 每个类别只有一条。"""
        return list(self.items.get(source_id) or [])

    @property
    def llm_extracted(self) -> int:
        return sum(len(v) for v in self.llm_items.values())

    @property
    def fallback_extracted(self) -> int:
        return sum(len(v) for v in self.fallback_items.values())


async def _llm_extract(
    fast_llm: Any, free_items: List[Dict[str, Any]]
) -> tuple[Dict[str, List[Dict[str, Any]]], Optional[str]]:
    """对自由文本做单次 Fast 模型抽取，仅归类、总结和填写 params。"""
    if fast_llm is None or not free_items:
        return {}, "llm_unavailable" if free_items else None
    payload = [
        {"id": it["id"], "text": it["text"]} for it in free_items if it.get("text")
    ]
    if not payload:
        return {}, None
    user = (
        "请逐项判断下列文本是否表达个人出行约束并归类。\n输入项：\n"
        + json.dumps(payload, ensure_ascii=False)
        + '\n\n输出 JSON：{"constraints":[{"id":<输入id>,"is_constraint":<bool>,'
        '"category":<类别>,"value":<canonical 简洁约束陈述>,"params":<对象或 null>}]}'
    )
    try:
        raw = await fast_llm.ainvoke(
            [
                {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ]
        )
    except Exception:
        return {}, "llm_call_failed"
    text = raw if isinstance(raw, str) else (getattr(raw, "content", "") or "")
    parsed = safe_parse_json(
        text, strip_think_tags=True, enable_repair=True, require_fields=("constraints",)
    )
    out: Dict[str, List[Dict[str, Any]]] = {}
    if parsed and isinstance(parsed.get("constraints"), list):
        for c in parsed["constraints"]:
            if (
                isinstance(c, dict)
                and c.get("id") is not None
                and c.get("is_constraint")
            ):
                value = str(c.get("value") or "").strip()
                if not value:
                    continue
                out.setdefault(str(c["id"]), []).append(
                    {
                        "category": _normalize_category(c.get("category")),
                        "value": value,
                        "params": c.get("params")
                        if isinstance(c.get("params"), dict)
                        else None,
                    }
                )
        return out, None
    return {}, "llm_parse_failed"


def deterministic_budget_constraints(text: str) -> List[Dict[str, Any]]:
    """Extract an explicit numeric budget cap without relying on a model."""

    out: List[Dict[str, Any]] = []

    patterns = [
        (r"(?:总预算|全程|整趟|整程)[^\d]{0,8}(\d+(?:\.\d+)?)", "total"),
        (r"(\d+(?:\.\d+)?)[^\d]{0,6}(?:总预算|全程|整趟|整程)", "total"),
        (r"(?:每晚|一晚|/晚|每夜|一夜)[^\d]{0,8}(\d+(?:\.\d+)?)", "night"),
        (r"(\d+(?:\.\d+)?)[^\d]{0,6}(?:每晚|一晚|/晚|每夜|一夜)", "night"),
        (r"(?:每天|每日|一天)[^\d]{0,8}(\d+(?:\.\d+)?)", "day"),
        (r"(\d+(?:\.\d+)?)[^\d]{0,6}(?:每天|每日|一天)", "day"),
    ]
    for pattern, per in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        if per != "total":
            nearby = text[max(0, m.start() - 8) : m.end() + 8].casefold()
            money_cues = (
                "预算",
                "费用",
                "花费",
                "开销",
                "人民币",
                "cny",
                "元",
                "块",
                "以内",
                "不超过",
                "不高于",
                "至多",
                "上限",
            )
            if not any(cue in nearby for cue in money_cues):
                continue
        amount = _budget_amount_param(m.group(1))
        if amount and any(h in text.lower() for h in _HARD_HINTS):
            label = {"night": "每晚预算", "day": "每日预算", "total": "总预算"}[per]
            out.append(
                {
                    "category": "budget_cap",
                    "value": f"{label}不超过 {amount:.0f} CNY",
                    "params": {"amount": amount, "currency": "CNY", "per": per},
                }
            )
            break
    return out


def _fallback_allergy(text: str) -> List[Dict[str, Any]]:
    allergens: List[str] = []
    for m in re.finditer(
        r"(?:对|不能吃|不吃|忌口|避开)([\u4e00-\u9fa5A-Za-z、/（）()]{1,16}?)(?:过敏|食物|菜|餐|。|，|,|$)",
        text,
    ):
        token = m.group(1).strip(" 、/（）()，,。")
        if token and token not in {"食物", "菜", "餐"}:
            allergens.extend([p for p in re.split(r"[、/,，和及]", token) if p.strip()])
    for token in (
        "花生",
        "虾",
        "蟹",
        "贝类",
        "坚果",
        "牛奶",
        "奶油",
        "小麦",
        "麸质",
        "面筋",
    ):
        if token in text and ("过敏" in text or "不能吃" in text or "避开" in text):
            allergens.append(token)
    allergens = list(dict.fromkeys(a.strip() for a in allergens if a.strip()))
    if not allergens:
        return []
    return [
        {
            "category": "food_allergy",
            "value": f"食物过敏/禁忌：{'、'.join(allergens)}",
            "params": {"allergens": allergens},
        }
    ]


def _rule_fallback_extract(
    free_items: List[Dict[str, Any]],
) -> ConstraintExtractionResult:
    result = ConstraintExtractionResult()
    for it in free_items:
        text = str(it.get("text") or "")
        found: List[Dict[str, Any]] = []
        found.extend(deterministic_budget_constraints(text))
        found.extend(_fallback_allergy(text))
        if any(
            k in text
            for k in (
                "老人",
                "父母",
                "腿脚",
                "少走路",
                "少步行",
                "少爬楼梯",
                "少楼梯",
                "避免爬坡",
                "少爬坡",
                "不要暴走",
                "走不动",
                "行动不便",
                "低步行",
                "膝关节",
                "膝盖",
                "膝伤",
                "腿伤",
                "连续步行",
            )
        ):
            found.append(
                {
                    "category": "health_condition"
                    if any(k in text for k in ("膝", "腿伤"))
                    else "elderly_mobility",
                    "value": text,
                    "params": _canonical_mobility_params(text, None),
                }
            )
        if any(k in text for k in ("孩子", "儿童", "小孩", "亲子")):
            found.append(
                {
                    "category": "child_friendly",
                    "value": "儿童同行，需要儿童友好安排",
                    "params": {"needs": ["child_friendly"]},
                }
            )
        if any(k in text for k in ("不要夜场", "不去夜店", "不去酒吧", "别安排夜场")):
            found.append(
                {
                    "category": "child_friendly",
                    "value": "儿童同行，避免夜场或成人向活动",
                    "params": {"avoid": ["nightlife", "adult_only"]},
                }
            )
        transport_avoid: List[str] = []
        if any(k in text for k in ("不坐夜巴", "不要夜巴", "避免夜巴", "避开夜巴")):
            transport_avoid.append("night_bus")
        if any(k in text for k in ("不要红眼", "不坐红眼", "避免红眼", "避开红眼")):
            transport_avoid.append("red_eye_flight")
        if any(k in text for k in ("少换乘", "不要多次换乘")):
            transport_avoid.append("many_transfers")
        has_transport_window = any(
            re.search(pattern, text)
            for pattern in (
                r"\d{1,2}:\d{2}\s*(?:前|之前)\s*(?:不|不要|不得|禁止).{0,6}(?:出发|发车)",
                r"\d{1,2}:\d{2}\s*(?:后|之后)\s*(?:不|不要|不得|禁止).{0,6}(?:抵达|到达)",
                r"(?:不早于|最早|不晚于|最晚)\s*\d{1,2}:\d{2}",
            )
        )
        avoid_overnight = any(
            token in text
            for token in (
                "禁过夜",
                "禁止过夜",
                "不安排过夜",
                "不要过夜",
                "避免过夜",
                "不过夜交通",
            )
        )
        if transport_avoid or has_transport_window or avoid_overnight:
            found.append(
                {
                    "category": "transport_constraint",
                    "value": text,
                    "params": _canonical_transport_params(
                        text, {"avoid": transport_avoid}
                    ),
                }
            )
        local_mode_params = _canonical_transport_mode_params(
            text,
            None,
            require_intent_hint=True,
        )
        has_explicit_local_mode_intent = any(
            hint in text.casefold()
            for hint in (
                *_LOCAL_MODE_PREFER_HINTS,
                *_LOCAL_MODE_AVOID_HINTS,
                *_LOCAL_MODE_LOCK_HINTS,
            )
        )
        if (
            has_explicit_local_mode_intent
            and local_mode_params
            and any(
                key in local_mode_params
                for key in (
                    "preferred_local_modes",
                    "excluded_local_modes",
                    "locked_local_mode",
                )
            )
        ):
            found.append(
                {
                    "category": "transport_constraint",
                    "value": text,
                    "params": local_mode_params,
                }
            )
        if any(
            k in text
            for k in (
                "必须有电梯",
                "要有电梯",
                "需要电梯",
                "无烟房",
                "禁烟",
                "不要青旅",
                "独立卫浴",
                "独立卫生间",
                "独卫",
            )
        ):
            avoid = ["hostel"] if "青旅" in text else []
            needs = []
            if any(
                k in text
                for k in (
                    "必须有电梯",
                    "要有电梯",
                    "需要电梯",
                    "酒店有电梯",
                    "住宿有电梯",
                )
            ):
                needs.append("elevator")
            if "无烟" in text or "禁烟" in text:
                needs.append("non_smoking")
            if any(k in text for k in ("独立卫浴", "独立卫生间", "独卫")):
                needs.append("private_bath")
            found.append(
                {
                    "category": "accommodation_preference",
                    "value": text,
                    "params": _canonical_accommodation_params(
                        text, {"needs": needs, "avoid": avoid}
                    ),
                }
            )
        if any(
            k in text
            for k in ("节奏慢", "慢一点", "不要太赶", "别太赶", "每天不要太多", "悠闲")
        ):
            found.append(
                {
                    "category": "pace_preference",
                    "value": "行程节奏偏慢，避免高密度安排",
                    "params": {"pace": "slow", "max_daily_poi": 5},
                }
            )
        if found:
            result.fallback_items[it["id"]] = found
    result.fallback_items = {k: v for k, v in result.fallback_items.items() if v}
    return result


def _merge_extracted_constraints(
    llm_entries: List[Dict[str, Any]], rule_entries: List[Dict[str, Any]]
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """同一条自由文本的两次抽取合成一份：**一个类别一条**。"""

    merged: List[Dict[str, Any]] = [dict(entry) for entry in llm_entries]
    by_category: Dict[str, Dict[str, Any]] = {}
    for entry in merged:
        by_category.setdefault(str(entry.get("category") or ""), entry)

    supplemented: List[Dict[str, Any]] = []
    for entry in rule_entries:
        category = str(entry.get("category") or "")
        existing = by_category.get(category)
        if existing is None:
            appended = dict(entry)
            by_category[category] = appended
            merged.append(appended)
            supplemented.append(appended)
            continue

        existing["params"] = _merge_constraint_params(
            category, existing.get("params"), entry.get("params")
        )
    return merged, supplemented


async def _extract_free_text(
    fast_llm: Any, free_items: List[Dict[str, Any]]
) -> ConstraintExtractionResult:
    """一条自由文本，一个类别，一条约束。"""

    llm_items, reason = await _llm_extract(fast_llm, free_items)
    rule_items = _rule_fallback_extract(free_items).fallback_items

    result = ConstraintExtractionResult(llm_items=llm_items)
    for it in free_items:
        source_id = it["id"]
        merged, supplemented = _merge_extracted_constraints(
            list(llm_items.get(source_id) or []), list(rule_items.get(source_id) or [])
        )
        if merged:
            result.items[source_id] = merged
        if supplemented:
            result.fallback_items[source_id] = supplemented
        if not merged:
            result.missing_sources.append(source_id)

    if reason:
        result.partial_reasons.append(reason)
    if result.fallback_extracted:
        result.partial_reasons.append("deterministic_fallback_used")
    return result


def merge_precomputed_constraint_extraction(
    free_items: List[Dict[str, Any]],
    model_items: Dict[str, List[Dict[str, Any]]],
) -> ConstraintExtractionResult:
    """Merge one shared request-normalization result with deterministic safeguards."""
    rule_items = _rule_fallback_extract(free_items).fallback_items
    result = ConstraintExtractionResult(llm_items=model_items)
    for item in free_items:
        source_id = item["id"]
        merged, supplemented = _merge_extracted_constraints(
            list(model_items.get(source_id) or []),
            list(rule_items.get(source_id) or []),
        )
        if merged:
            result.items[source_id] = merged
        if supplemented:
            result.fallback_items[source_id] = supplemented
        if not merged:
            result.missing_sources.append(source_id)
    if result.fallback_extracted:
        result.partial_reasons.append("deterministic_fallback_used")
    return result
