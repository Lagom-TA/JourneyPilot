"""Planning requirements constraints presentation."""

from __future__ import annotations

from typing import Any, Dict, List

from travel_agent.planning.requirements.constraints.parameters import (
    _allergen_detail_is_unknown,
    _allergy_allergen_key,
)
from travel_agent.planning.requirements.constraints.resolution import _item_source

# Independent budgets keep manual preferences from competing with hard constraints.
_PROMPT_HARD_LINES = 12


_PROMPT_PREFERENCE_LINES = 45


_PROMPT_REFERENCE_LINES = 6


def referenced_context_sections(pack: Any) -> List[Dict[str, Any]]:
    """上下文透镜（「本次参考的信息」）要列的条目 —— 逐条等于 prompt 真印出去的那些。"""

    if not isinstance(pack, dict):
        return []
    sections: List[Dict[str, Any]] = []
    for section in _constraint_prompt_sections(pack):
        items: List[str] = []
        for row in section["rows"]:
            if row["value"] not in items:
                items.append(row["value"])
        if items:
            sections.append({"key": section["key"], "items": items})
    return sections


_UNKNOWN_ALLERGEN_DINING_NOTE = (
    "有食物过敏，而系统没有拿到过敏原是什么："
    "本行程没有替你排除任何过敏原，请点餐前向店员说明过敏情况并逐一确认食材。"
)


def dining_allergy_reminders(pack: Any) -> List[str]:
    """Concise dining-local reminders for soft food allergies."""
    if not isinstance(pack, dict):
        return []
    allergies: dict[frozenset[str], bool] = {}
    detail_unknown = False
    for item in pack.get("soft_preferences") or []:
        if not isinstance(item, dict):
            continue
        if item.get("status") not in (None, "active"):
            continue
        if str(item.get("category") or "") != "food_allergy":
            continue
        if item.get("visibility") not in (None, "user_visible"):
            continue
        if _allergen_detail_is_unknown(item):
            detail_unknown = True
            continue
        allergens = _allergy_allergen_key(item)
        is_severe = "严重" in str(item.get("value") or "")
        allergies[allergens] = allergies.get(allergens, False) or is_severe

    notes: List[str] = []

    if detail_unknown:
        notes.append(_UNKNOWN_ALLERGEN_DINING_NOTE)
    for allergens, is_severe in allergies.items():
        allergen_text = "、".join(sorted(allergens))
        severity = "严重" if is_severe else ""
        notes.append(
            f"{allergen_text}{severity}过敏，请点餐时避开含{allergen_text}的菜品，"
            "并向店员说明过敏情况。"
        )
    return notes


def _pack_prompt_lines(
    pack: Dict[str, Any], *, user_visible: bool
) -> List[Dict[str, Any]]:
    """把 pack 里符合可见性的 active item 摊平成 (标签, 正文) 待印行。"""
    rows: List[Dict[str, Any]] = []
    for label, key in (("硬约束", "hard_constraints"), ("偏好", "soft_preferences")):
        for item in pack.get(key) or []:
            if not isinstance(item, dict):
                continue
            if (item.get("visibility") == "user_visible") is not user_visible:
                continue
            value = str(item.get("value") or "").strip()
            if not value:
                continue

            rows.append(
                {
                    "label": label,
                    "category": str(item.get("category") or "other"),
                    "value": value,
                    "params": item.get("params"),
                    "source": _item_source(item),
                }
            )
    return rows


def _render_constraint_line(row: Dict[str, Any]) -> str:
    category, value, label = row["category"], row["value"], row["label"]
    if category == "food_allergy":
        if _allergen_detail_is_unknown(row):
            return (
                f"- [用餐提醒/{category}] {value}。"
                f"这一条只说明「有食物过敏」，没有附带过敏原清单："
                f"不许猜过敏原，也不许把任何菜品、餐厅或整份行程说成「已避开过敏原」"
                f"「已确认无过敏原」。正常推荐具体餐厅即可，"
                f"并在用餐安排旁提醒旅客自己向店员说明过敏情况、逐一确认食材。"
            )
        return (
            f"- [用餐提醒/{category}] {value}。"
            f"正常推荐具体餐厅即可；在对应餐馆或用餐安排旁提醒点菜时避开相关食材。"
            f"禁止因过敏拒绝全部餐厅，禁止要求或宣称「全店已确认无过敏原」。"
        )
    return f"- [{label}/{category}] {value}"


def _budgeted_rows(
    rows: List[Dict[str, Any]], budget: int, *, what: str
) -> tuple[List[Dict[str, Any]], str]:
    """一类待印行按自己的预算取前 N 条，被截时给出一句明说。"""

    if not rows:
        return [], ""
    kept = rows[:budget]
    if len(rows) <= budget:
        return kept, ""
    note = (
        f"（本类还有 {len(rows) - budget} 条{what}未列出：受 prompt 预算限制，"
        f"已按录入顺序取前 {budget} 条。未列出的不等于用户撤回了它们。）"
    )
    return kept, note


def _manual_memory_omitted_note(kept_rows: List[Dict[str, Any]]) -> str:
    """手写记忆撞上**条数上限**时的那一句明说（行数预算那一道见 ``_budgeted_rows``）。"""

    printed = sum(1 for row in kept_rows if row.get("source") == "manual_memory")
    return (
        f"（还有更早写下的手写记忆未列出：受 prompt 预算限制，本轮只注入了最近写下的 "
        f"{printed} 条。未列出的不等于用户撤回了它们。）"
    )


def _constraint_prompt_sections(pack: Dict[str, Any]) -> List[Dict[str, Any]]:
    """本轮 pack 会印进 prompt 的三段 —— prompt 与上下文透镜的**同一个产地**。"""

    declared = _pack_prompt_lines(pack, user_visible=True)
    grouped = {
        "hard": [row for row in declared if row["label"] == "硬约束"],
        "preference": [row for row in declared if row["label"] == "偏好"],
        "reference": _pack_prompt_lines(pack, user_visible=False),
    }
    budgets = (
        ("hard", _PROMPT_HARD_LINES, "硬约束"),
        ("preference", _PROMPT_PREFERENCE_LINES, "偏好"),
        ("reference", _PROMPT_REFERENCE_LINES, "参考级背景"),
    )
    meta = pack.get("pack_meta")
    manual_memory_truncated = bool(
        isinstance(meta, dict) and meta.get("manual_memory_truncated")
    )
    sections: List[Dict[str, Any]] = []
    for key, budget, what in budgets:
        kept, note = _budgeted_rows(grouped[key], budget, what=what)
        notes = [note] if note else []

        if key == "preference" and manual_memory_truncated:
            notes.append(_manual_memory_omitted_note(kept))
        sections.append({"key": key, "rows": kept, "omitted_notes": notes})
    return sections


def format_constraint_pack_for_prompt(pack: Any) -> str:
    """Project the shared pack into the Agent instructions that reach the model."""
    if not isinstance(pack, dict):
        return ""

    sections = {
        section["key"]: section for section in _constraint_prompt_sections(pack)
    }

    def _render(key: str) -> List[str]:
        section = sections[key]
        lines = [_render_constraint_line(row) for row in section["rows"]]
        lines.extend(section["omitted_notes"])
        return lines

    parts: List[str] = []
    declared_lines = _render("hard") + _render("preference")
    if declared_lines:
        parts.append("【本轮统一约束】\n" + "\n".join(declared_lines))

    reference_lines = _render("reference")
    if reference_lines:
        parts.append(
            "【参考级背景 — 不是约束】\n"
            "以下是系统根据历史对话推理出的用户特征、以及重要度未达高档的历史记忆，"
            "用户并未在本轮声明它们。可以用来在几个都合规的选项之间排序与取舍；"
            "不得当成硬性要求，不得据此拒绝任何候选或缩小调研范围，"
            "与上面【本轮统一约束】冲突时一律以上面为准。\n"
            + "\n".join(reference_lines)
        )

    return "\n\n".join(parts)
