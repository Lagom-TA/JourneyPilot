"""约束参数解析。"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

_LOCAL_TRANSPORT_MODE_ALIASES = {
    "walk": ("步行", "徒步", "walk", "walking"),
    "bike": ("骑行", "自行车", "单车", "bike", "bicycle", "cycling"),
    "drive": ("自驾", "驾车", "开车", "drive", "driving"),
    "taxi": ("出租车", "打车", "taxi", "cab"),
    "ride_hailing": ("网约车", "ride_hailing", "ride hailing", "rideshare"),
}


_LOCAL_MODE_LOCK_HINTS = (
    "必须",
    "坚持",
    "只坐",
    "只用",
    "只能",
    "务必",
    "must",
    "only",
)


_LOCAL_MODE_AVOID_HINTS = (
    "不要",
    "不想",
    "不坐",
    "不走",
    "不能",
    "禁止",
    "避免",
    "避开",
    "少坐",
    "少走",
    "avoid",
    "never",
    "no ",
)


_LOCAL_MODE_PREFER_HINTS = (
    "优先",
    "偏好",
    "喜欢",
    "尽量",
    "坚持",
    "选择",
    "希望",
    "我要",
    "prefer",
    "preferred",
    "must",
    "only",
)


def _canonical_local_time(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _canonical_transport_params(
    value: str, params: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    normalized = dict(_canonical_transport_mode_params(value, params) or {})
    avoid = list(normalized.get("avoid") or [])
    if any(
        token in value
        for token in (
            "禁过夜",
            "禁止过夜",
            "不安排过夜",
            "不要过夜",
            "避免过夜",
            "不过夜交通",
        )
    ):
        normalized["avoid_overnight"] = True
    if normalized.get("avoid_overnight") is not True:
        normalized.pop("avoid_overnight", None)

    earliest_patterns = (
        r"(\d{1,2}:\d{2})\s*(?:前|之前)\s*(?:不|不要|不得|禁止).{0,6}(?:出发|发车)",
        r"(?:不早于|最早)\s*(\d{1,2}:\d{2}).{0,6}(?:出发|发车)?",
    )
    latest_patterns = (
        r"(\d{1,2}:\d{2})\s*(?:后|之后)\s*(?:不|不要|不得|禁止).{0,6}(?:抵达|到达)",
        r"(?:不晚于|最晚)\s*(\d{1,2}:\d{2}).{0,6}(?:抵达|到达)?",
    )
    for key, patterns in (
        ("earliest_departure_local", earliest_patterns),
        ("latest_arrival_local", latest_patterns),
    ):
        current = _canonical_local_time(normalized.get(key))
        if current is None:
            for pattern in patterns:
                match = re.search(pattern, value)
                if match:
                    current = _canonical_local_time(match.group(1))
                    if current:
                        break
        if current:
            normalized[key] = current
        else:
            normalized.pop(key, None)
    if avoid:
        normalized["avoid"] = list(
            dict.fromkeys(str(item) for item in avoid if str(item))
        )
    else:
        normalized.pop("avoid", None)
    return normalized or None


def _canonical_accommodation_params(
    value: str, params: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    normalized = dict(params or {})
    facilities = list(normalized.pop("required_facilities", []) or [])
    facilities.extend(normalized.pop("needs", []) or [])
    if any(token in value for token in ("禁烟", "无烟")):
        facilities.append("non_smoking")
    if any(token in value for token in ("独立卫浴", "独立卫生间", "独卫")):
        facilities.append("private_bath")
    if any(
        token in value
        for token in ("必须有电梯", "要有电梯", "需要电梯", "酒店有电梯", "住宿有电梯")
    ):
        facilities.append("elevator")
    facility_aliases = {
        "non-smoking": "non_smoking",
        "nonsmoking": "non_smoking",
        "无烟": "non_smoking",
        "禁烟": "non_smoking",
        "private_bathroom": "private_bath",
        "private-bathroom": "private_bath",
        "独立卫浴": "private_bath",
        "独立卫生间": "private_bath",
        "独卫": "private_bath",
        "电梯": "elevator",
    }
    facilities = list(
        dict.fromkeys(
            facility_aliases.get(str(item).strip().lower(), str(item).strip())
            for item in facilities
            if str(item).strip()
        )
    )
    if facilities:
        normalized["required_facilities"] = facilities
        normalized["unknown_facility_policy"] = "needs_confirmation"
    avoid = list(
        dict.fromkeys(str(item) for item in normalized.get("avoid") or [] if str(item))
    )
    if avoid:
        normalized["avoid"] = avoid
    else:
        normalized.pop("avoid", None)
    return normalized or None


def _canonical_mobility_params(
    value: str, params: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    normalized = dict(params or {})
    walk = _positive_int_param(normalized.pop("max_continuous_walk_minutes", None))
    if walk is None:
        match = re.search(
            r"(?:连续)?步行.{0,6}(?:不超过|最多|超过)\s*(\d{1,3})\s*分钟", value
        )
        if match:
            walk = _positive_int_param(int(match.group(1)))
    if walk is not None:
        normalized["max_continuous_walk_minutes"] = walk
    if any(
        token in value
        for token in (
            "少楼梯",
            "少爬楼梯",
            "避免楼梯",
            "避免爬楼",
            "不要爬楼",
            "长楼梯",
            "长距离爬楼梯",
        )
    ):
        normalized["avoid_long_stairs"] = True
    prefer = list(normalized.get("prefer") or [])
    if any(
        token in value
        for token in ("电梯", "无障碍", "休息", "慢节奏", "膝", "腿脚", "行动不便")
    ):
        prefer.extend(["elevator", "accessible_route", "rest_break"])
    normalized.pop("needs", None)
    normalized["prefer"] = list(
        dict.fromkeys(str(item) for item in prefer if str(item))
    )
    normalized["unknown_facility_policy"] = "needs_confirmation"
    return normalized


def _positive_int_param(value: Any) -> Optional[int]:
    """只接受规范的正整数，不做类型转换，也不给默认值。"""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


_BUDGET_AMOUNT_PATTERN = re.compile(
    r"[¥￥]?\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:元|块|人民币|rmb|cny)?",
    re.IGNORECASE,
)


def _budget_amount_param(value: Any) -> Optional[float]:
    """接受数字预算上限；纯文本金额描述不会被强制转成数字。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        amount = float(value)
    elif isinstance(value, str):
        match = _BUDGET_AMOUNT_PATTERN.fullmatch(value.strip())
        if match is None:
            return None
        amount = float(match.group(1).replace(",", ""))
    else:
        return None
    return amount if amount > 0 else None


def _canonical_constraint_params(
    category: str, value: str, params: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    if category == "transport_constraint":
        return _canonical_transport_params(value, params)
    if category == "accommodation_preference":
        return _canonical_accommodation_params(value, params)
    if category in {"elderly_mobility", "health_condition"}:
        return _canonical_mobility_params(value, params)
    if category == "food_allergy":
        return _canonical_allergy_params(value, params)
    if category == "budget_cap":
        normalized = dict(params or {})
        amount = _budget_amount_param(normalized.get("amount"))
        if amount is not None:
            normalized["amount"] = amount
        else:
            normalized.pop("amount", None)
        normalized["currency"] = str(normalized.get("currency") or "CNY").upper()
        normalized["per"] = str(normalized.get("per") or "total")
        return normalized
    return dict(params) if params else None


def _contains_mode_alias(text: str, alias: str) -> bool:
    if alias.isascii() and alias.replace("_", "").replace(" ", "").isalpha():
        return bool(
            re.search(
                rf"(?<![a-z]){re.escape(alias.casefold())}(?![a-z])", text.casefold()
            )
        )
    return alias in text


def _mode_text_intent(value: str, aliases: tuple[str, ...]) -> Optional[str]:
    """返回管束被提及本地交通方式的最近一处明确意图。"""
    normalized = value.casefold()
    strong_boundary = re.compile(r"[。；;.!?！？\n]")
    intent_groups = (
        ("excluded", _LOCAL_MODE_AVOID_HINTS),
        ("locked", _LOCAL_MODE_LOCK_HINTS),
        ("preferred", _LOCAL_MODE_PREFER_HINTS),
    )
    decisions: list[tuple[int, int, str]] = []
    for alias in aliases:
        alias_value = alias.casefold()
        for alias_match in re.finditer(re.escape(alias_value), normalized):
            prefix = normalized[: alias_match.start()]
            boundaries = list(strong_boundary.finditer(prefix))
            scope_start = boundaries[-1].end() if boundaries else 0
            scoped_prefix = normalized[scope_start : alias_match.start()]
            for decision_priority, (decision, hints) in enumerate(intent_groups):
                for hint in hints:
                    hint_index = scoped_prefix.rfind(hint)
                    if hint_index >= 0:
                        distance = len(scoped_prefix) - hint_index - len(hint)
                        decisions.append((distance, decision_priority, decision))
    if not decisions:
        return None
    return min(decisions)[2]


def _canonical_transport_mode_params(
    value: str,
    params: Optional[Dict[str, Any]],
    *,
    require_intent_hint: bool = False,
) -> Optional[Dict[str, Any]]:
    """把明确的本地交通方式意图绑定为类型化参数，不凭空生成路线。"""
    normalized = dict(params or {})
    raw_preferred = normalized.get("preferred_local_modes")
    preferred = list(raw_preferred) if isinstance(raw_preferred, list) else []
    raw_excluded = normalized.get("excluded_local_modes")
    excluded = list(raw_excluded) if isinstance(raw_excluded, list) else []
    locked = str(normalized.get("locked_local_mode") or "").strip() or None
    for mode, aliases in _LOCAL_TRANSPORT_MODE_ALIASES.items():
        matching_aliases = [
            alias for alias in aliases if _contains_mode_alias(value, alias)
        ]
        if not matching_aliases:
            continue
        text_intent = _mode_text_intent(value, tuple(matching_aliases))
        if text_intent == "excluded":
            preferred = [candidate for candidate in preferred if candidate != mode]
            excluded.append(mode)
            if locked == mode:
                locked = None
            continue
        if require_intent_hint and text_intent is None:
            continue
        if text_intent in {"preferred", "locked"}:
            excluded = [candidate for candidate in excluded if candidate != mode]
        preferred.append(mode)
        if text_intent == "locked":
            locked = mode
    preferred = [
        mode
        for mode in dict.fromkeys(preferred)
        if mode in _LOCAL_TRANSPORT_MODE_ALIASES and mode not in set(excluded)
    ]
    excluded = [
        mode
        for mode in dict.fromkeys(excluded)
        if mode in _LOCAL_TRANSPORT_MODE_ALIASES
    ]
    if preferred:
        normalized["preferred_local_modes"] = preferred
    else:
        normalized.pop("preferred_local_modes", None)
    if excluded:
        normalized["excluded_local_modes"] = excluded
    else:
        normalized.pop("excluded_local_modes", None)
    if locked in preferred:
        normalized["locked_local_mode"] = locked
    else:
        normalized.pop("locked_local_mode", None)
    return normalized or None


_KNOWN_ALLERGEN_TOKENS = (
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
    "海鲜",
    "芒果",
    "鸡蛋",
)


_ALLERGEN_DETAIL_UNKNOWN = "unknown"


_UNKNOWN_ALLERGEN_KEY = "allergen_detail_unknown"


def _known_allergen_tokens(text: str) -> set[str]:
    return {token for token in _KNOWN_ALLERGEN_TOKENS if token in str(text or "")}


def _allergy_declares_unknown_detail(value: Any, params: Any) -> bool:
    """这条过敏 item 是不是「有过敏、过敏原未知」那一种。**这条判断只在这里写一次。**"""

    typed = params if isinstance(params, dict) else {}
    if str(typed.get("allergen_detail") or "") != _ALLERGEN_DETAIL_UNKNOWN:
        return False
    if any(str(token).strip() for token in typed.get("allergens") or []):
        return False
    return not _known_allergen_tokens(str(value or ""))


def _canonical_allergy_params(
    value: str, params: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """``food_allergy`` 的 typed params 归一：过敏原清单与「细节未知」标记**互斥**。"""

    normalized = dict(params or {})
    allergens = [
        token
        for token in dict.fromkeys(
            str(raw).strip() for raw in normalized.get("allergens") or []
        )
        if token
    ]
    if allergens:
        normalized["allergens"] = allergens
    else:
        normalized.pop("allergens", None)
    if not _allergy_declares_unknown_detail(value, normalized):
        normalized.pop("allergen_detail", None)
    return normalized or None


def _allergy_allergen_key(item: Dict[str, Any]) -> frozenset[str]:
    """归一化过敏原标记，用于 food_allergy 语义去重。"""
    if _allergy_declares_unknown_detail(item.get("value"), item.get("params")):
        return frozenset({_UNKNOWN_ALLERGEN_KEY})
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    raw = params.get("allergens") if isinstance(params, dict) else None
    blobs: list[str] = []
    if isinstance(raw, list):
        blobs.extend(str(t) for t in raw if str(t).strip())
    blobs.append(str(item.get("value") or ""))
    found: set[str] = set()
    for blob in blobs:
        found |= _known_allergen_tokens(blob)
    if found:
        return frozenset(found)

    named = frozenset(
        token
        for token in (str(t).strip() for t in (raw if isinstance(raw, list) else []))
        if token
    )
    if named:
        return named

    scrubbed = re.sub(
        r"[\s：:，,。；;、/\\\-_]", "", str(item.get("value") or "").lower()
    )

    return frozenset({scrubbed}) if scrubbed else frozenset({_UNKNOWN_ALLERGEN_KEY})


def _allergen_detail_is_unknown(item: Dict[str, Any]) -> bool:
    """交付面与 prompt 两处共用的那一问：这条过敏**点得出过敏原的名字吗**。"""

    return _allergy_allergen_key(item) == frozenset({_UNKNOWN_ALLERGEN_KEY})
