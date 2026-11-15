"""约束展示。"""

from __future__ import annotations

from typing import Any, Dict, List

from travel_agent.planning.requirements.constraints.parameters import (
    _allergen_detail_is_unknown,
    _allergy_allergen_key,
)
from travel_agent.planning.requirements.constraints.resolution import _item_is_current

# 本次要求与参考资料各自计数，互不挤占展示空间。
_PROMPT_HARD_LINES = 12
_PROMPT_PREFERENCE_LINES = 45
_PROMPT_REFERENCE_LINES = 6

_SOURCE_LABELS = {
    "current_query": "本次问题",
    "plan_gate_amendment": "本次计划补充",
    "run_supplement": "本次补充",
    "preset": "本次应用的预设",
    "session_anchor": "本次对话摘要（模型整理）",
    "manual_profile": "历史画像",
    "manual_memory": "手写历史记忆",
    "memory_fact": "历史记忆",
    "auto_portrait": "历史自动画像",
    "historical_preset": "历史预设",
}


def partition_constraint_pack(pack: Any) -> Dict[str, List[Dict[str, Any]]]:
    """按条目的全部来源区分本次输入和参考资料，保留原始条目。"""
    groups: Dict[str, List[Dict[str, Any]]] = {"current": [], "reference": []}
    if not isinstance(pack, dict):
        return groups
    for key in ("hard_constraints", "soft_preferences"):
        items = pack.get(key)
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or item.get("status") not in (None, "active"):
                continue
            group = "current" if _item_is_current(item) else "reference"
            groups[group].append(item)
    return groups


def describe_constraint_sources(item: Any) -> str:
    """将条目的来源标识转换为可读名称，未知来源不作推断。"""
    refs = item.get("source_refs") if isinstance(item, dict) else None
    if not isinstance(refs, list) or not refs:
        return "来源未注明"
    labels = [
        (
            "历史预设"
            if ref.get("source") == "preset" and ref.get("scope") == "historical"
            else _SOURCE_LABELS.get(str(ref.get("source") or ""), "来源未注明")
        )
        if isinstance(ref, dict) else "来源未注明"
        for ref in refs
    ]
    return "、".join(dict.fromkeys(labels))


def referenced_context_sections(pack: Any) -> List[Dict[str, Any]]:
    """上下文透镜（「本次参考的信息」）要列出的条目，与 prompt 实际打印的内容一致。"""

    if not isinstance(pack, dict):
        return []
    sections: List[Dict[str, Any]] = []
    for section in _constraint_prompt_sections(pack):
        items: List[str] = []
        for row in section["rows"]:
            value = f"{row['value']}（来源：{row['source_label']}）"
            if value not in items:
                items.append(value)
        if items:
            sections.append({"key": section["key"], "items": items})
    return sections


_UNKNOWN_ALLERGEN_DINING_NOTE = (
    "你提到了食物过敏，但未说明具体过敏原："
    "本行程没有替你排除任何过敏原，请点餐前向店员说明过敏情况并逐一确认食材。"
)


def dining_allergy_reminders(pack: Any) -> List[str]:
    """面向餐饮场景的简短软性食物过敏提醒。"""
    if not isinstance(pack, dict):
        return []
    allergies: dict[frozenset[str], bool] = {}
    detail_unknown = False
    for item in pack.get("soft_preferences") or []:
        if not isinstance(item, dict) or not _item_is_current(item):
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


def _pack_prompt_lines(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将已分类的条目整理为带来源的展示行。"""
    rows: List[Dict[str, Any]] = []
    for item in items:
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        rows.append(
            {
                "label": "硬约束" if item.get("type") == "hard" else "偏好",
                "category": str(item.get("category") or "other"),
                "value": value,
                "params": item.get("params"),
                "source_label": describe_constraint_sources(item),
                "source_refs": item.get("source_refs"),
            }
        )
    return rows


def _render_constraint_line(row: Dict[str, Any], *, reference: bool = False) -> str:
    category, value, label = row["category"], row["value"], row["label"]
    source = row["source_label"]
    if reference:
        return f"- [{category}｜来源：{source}] {value}"
    if category == "food_allergy":
        if _allergen_detail_is_unknown(row):
            return (
                f"- [用餐提醒/{category}｜来源：{source}] {value}。"
                "具体过敏原尚未说明，请在用餐安排旁提醒旅客向店员说明过敏情况、逐一确认食材。"
            )
        return (
            f"- [用餐提醒/{category}｜来源：{source}] {value}。"
            "请在用餐安排旁提醒旅客避开相关食材，并向店员确认。"
        )
    return f"- [{label}/{category}｜来源：{source}] {value}"


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
        f"已按录入顺序取前 {budget} 条，未列出的内容保留原有来源。）"
    )
    return kept, note


def _manual_memory_omitted_note(kept_rows: List[Dict[str, Any]]) -> str:
    """手写记忆撞上**条数上限**时的那一句明说（行数预算那一道见 ``_budgeted_rows``）。"""

    printed = sum(
        1 for row in kept_rows
        if any(
            isinstance(ref, dict) and ref.get("source") == "manual_memory"
            for ref in row.get("source_refs") or []
        )
    )
    return (
        f"（还有更早写下的手写记忆未列出：受 prompt 预算限制，本轮只注入了最近写下的 "
        f"{printed} 条。未列出的不等于用户撤回了它们。）"
    )


def _constraint_prompt_sections(pack: Dict[str, Any]) -> List[Dict[str, Any]]:
    """本轮 pack 会印进 prompt 的三段 —— prompt 与上下文透镜的**同一个产地**。"""

    partitioned = partition_constraint_pack(pack)
    declared = _pack_prompt_lines(partitioned["current"])
    grouped = {
        "hard": [row for row in declared if row["label"] == "硬约束"],
        "preference": [row for row in declared if row["label"] == "偏好"],
        "reference": _pack_prompt_lines(partitioned["reference"]),
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

        if key == "reference" and manual_memory_truncated and any(
            isinstance(ref, dict) and ref.get("source") == "manual_memory"
            for row in kept for ref in row.get("source_refs") or []
        ):
            notes.append(_manual_memory_omitted_note(kept))
        sections.append({"key": key, "rows": kept, "omitted_notes": notes})
    return sections


def format_constraint_pack_for_prompt(pack: Any) -> str:
    """把共享的 Constraint Pack 投影为发送给模型的 Agent 指令。"""
    if not isinstance(pack, dict):
        return ""

    sections = {
        section["key"]: section for section in _constraint_prompt_sections(pack)
    }

    def _render(key: str) -> List[str]:
        section = sections[key]
        lines = [
            _render_constraint_line(row, reference=key == "reference")
            for row in section["rows"]
        ]
        lines.extend(section["omitted_notes"])
        return lines

    parts: List[str] = []
    declared_lines = _render("hard") + _render("preference")
    if declared_lines:
        parts.append("【本次输入的约束与偏好】\n" + "\n".join(declared_lines))

    reference_lines = _render("reference")
    if reference_lines:
        parts.append(
            "【其他来源参考】\n"
            "请结合每条标明的来源参考这些资料。对话摘要是模型整理，可用于保持同一旅行的上下文；"
            "历史画像、记忆和预设仅供参考。请同等重视本次提交的表单（包括默认值和填写值）、"
            "自然语言和同一旅行问答；参考资料与本次输入不一致时，以本次输入为准。\n"
            + "\n".join(reference_lines)
        )

    return "\n\n".join(parts)
