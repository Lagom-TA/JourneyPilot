"""约束包区分本次输入、对话摘要和历史参考。"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from travel_agent.planning.requirements.constraints.assembly import build_constraint_pack
from travel_agent.planning.requirements.constraints.items import _make_item
from travel_agent.planning.requirements.constraints.loading import LoadedConstraintSources
from travel_agent.planning.requirements.constraints.planning import build_planning_constraint_pack
from travel_agent.planning.requirements.constraints.presentation import (
    describe_constraint_sources,
    dining_allergy_reminders,
    format_constraint_pack_for_prompt,
    partition_constraint_pack,
    referenced_context_sections,
)
from travel_agent.planning.requirements.constraints.resolution import normalize_constraint_pack


def item(source, value, *, category="other", origin=None):
    return _make_item(
        category=category,
        value=value,
        params=None,
        source=source,
        confidence="high",
        visibility="user_visible",
        updated_at="2026-01-01T00:00:00+00:00",
        origin_ref=origin or source,
    )


def pack_of(*items):
    return {
        "constraints": list(items),
        "hard_constraints": [entry for entry in items if entry["type"] == "hard"],
        "soft_preferences": [entry for entry in items if entry["type"] == "soft"],
    }


def test_prompt_and_context_report_preserve_sources_and_separate_history():
    current = item("current_query", "本次节奏宽松")
    preset = item("preset", "本次住宿要安静")
    profile = item("manual_profile", "画像中的住宿偏好")
    manual = item("manual_memory", "手写的历史偏好")
    memory = item("memory_fact", "重要的历史记录")
    portrait = item("auto_portrait", "自动画像内容")
    anchor = item("session_anchor", "对话中整理出的内容")
    mixed = item("current_query", "混合来源内容")
    mixed["source_refs"].append({"source": "manual_memory"})
    unknown = item("unrecognized", "来源不明的内容")
    pack = pack_of(current, preset, profile, manual, memory, portrait, anchor, mixed, unknown)

    groups = partition_constraint_pack(pack)
    assert groups["current"] == [current, preset]
    assert groups["reference"] == [profile, manual, memory, portrait, anchor, mixed, unknown]
    assert describe_constraint_sources(mixed) == "本次问题、手写历史记忆"
    assert describe_constraint_sources({}) == "来源未注明"

    prompt = format_constraint_pack_for_prompt(pack)
    current_text, reference_text = prompt.split("【其他来源参考】", 1)
    assert "本次节奏宽松" in current_text and "来源：本次问题" in current_text
    assert "本次住宿要安静" in current_text and "来源：本次应用的预设" in current_text
    assert "画像中的住宿偏好" not in current_text
    for label in ("历史画像", "手写历史记忆", "历史记忆", "历史自动画像", "本次对话摘要（模型整理）"):
        assert label in reference_text
    assert "未列出" in reference_text
    assert "本次提交的表单（包括默认值和填写值）" in reference_text
    assert "自然语言和同一旅行问答" in reference_text

    sections = {section["key"]: section["items"] for section in referenced_context_sections(pack)}
    assert "本次住宿要安静（来源：本次应用的预设）" in sections["preference"]
    assert "画像中的住宿偏好（来源：历史画像）" in sections["reference"]
    assert "混合来源内容（来源：本次问题、手写历史记忆）" in sections["reference"]


def test_reference_budget_keeps_current_input_visible():
    current = item("current_query", "本次希望慢游")
    history = [item("manual_memory", f"历史偏好#{index}") for index in range(10)]

    prompt = format_constraint_pack_for_prompt(pack_of(current, *history))
    current_text, reference_text = prompt.split("【其他来源参考】", 1)
    assert "本次希望慢游" in current_text
    assert all(f"历史偏好#{index}" in reference_text for index in range(6))
    assert all(f"历史偏好#{index}" not in reference_text for index in range(6, 10))
    assert "未列出" in reference_text


@pytest.mark.parametrize("pack", [None, {}, {"pack_meta": {"manual_memory_truncated": True}}])
def test_empty_pack_does_not_invent_history(pack):
    assert partition_constraint_pack(pack) == {"current": [], "reference": []}
    assert format_constraint_pack_for_prompt(pack) == ""
    assert referenced_context_sections(pack) == []


async def test_planning_pack_preserves_real_sources_with_applied_preset(monkeypatch):
    prefs = SimpleNamespace(
        travel_styles=["历史风格"], dietary_restrictions=[], typical_budget_level="历史预算",
        accommodation_type="", pace="", preferred_transport=[],
    )
    loaded = LoadedConstraintSources(
        user_profile=SimpleNamespace(preferences=prefs, auto_portrait="画像摘要"),
        manual_memory_facts=[{"fact_id": "test", "content": "手写历史要求"}],
        manual_memory_truncated=False,
        memory_facts=[{"category": "constraint", "importance": 10, "content": "高重要度历史要求"}],
        missing_layers=[], partial_reasons=[],
    )
    monkeypatch.setattr("travel_agent.bootstrap.registry.get_components", lambda: object())
    loader = AsyncMock(return_value=loaded)
    monkeypatch.setattr("travel_agent.planning.requirements.constraints.planning.load_constraint_sources", loader)
    result = await build_planning_constraint_pack({
        "run_id": "test-run", "preset_pack_constraints": {"budget_cap": "预算最多 5000 元"},
    })

    current = partition_constraint_pack(result)["current"]
    reference = partition_constraint_pack(result)["reference"]
    assert len(current) == 1 and current[0]["value"] == "预算最多 5000 元"
    assert current[0]["type"] == "soft"
    assert {entry["value"] for entry in reference} >= {
        "旅行风格：历史风格", "预算档位：历史预算", "手写历史要求", "高重要度历史要求", "画像摘要",
    }
    assert all(entry["type"] == "soft" and entry["enforcement_scope"] == ["advisory"] for entry in reference)
    assert "历史预算" not in format_constraint_pack_for_prompt(result).split("【其他来源参考】", 1)[0]
    loader.assert_awaited_once()


async def test_applied_preset_survives_unavailable_components_without_fabricating_history(monkeypatch):
    def unavailable():
        raise RuntimeError("unavailable")

    monkeypatch.setattr("travel_agent.bootstrap.registry.get_components", unavailable)
    pack = await build_planning_constraint_pack({"preset_pack_constraints": {"pace_preference": "悠闲"}})
    assert [entry["value"] for entry in partition_constraint_pack(pack)["current"]] == ["悠闲"]
    assert partition_constraint_pack(pack)["reference"] == []
    assert "【其他来源参考】" not in format_constraint_pack_for_prompt(pack)


async def test_replayed_historical_hard_item_stays_reference_and_does_not_defeat_current():
    old = item("manual_profile", "最多 1000 元", category="budget_cap")
    old.update(type="hard", priority="hard", enforcement_scope=["composition"])
    old["updated_at"] = "2099-01-01T00:00:00+00:00"
    current = item("preset", "最多 5000 元", category="budget_cap")
    state = {"run_id": "test-run", "constraint_pack": pack_of(old), "preset_pack_constraints": {"budget_cap": current["value"]}}
    result = await build_constraint_pack(state, None)
    groups = partition_constraint_pack(result)
    assert [entry["value"] for entry in groups["current"]] == [current["value"]]
    assert [entry["value"] for entry in groups["reference"]] == [old["value"]]
    assert groups["reference"][0]["type"] == "soft"
    assert groups["reference"][0]["enforcement_scope"] == ["advisory"]
    assert all(entry["source_refs"][0]["source"] != "manual_profile" for entry in result["hard_constraints"])


async def test_dedup_does_not_merge_historical_and_current_mobility():
    old = item("manual_profile", "历史上希望少走路", category="elderly_mobility")
    old["type"] = "hard"
    state = {"constraint_pack": pack_of(old), "preset_pack_constraints": {"elderly_mobility": "本次希望避免长楼梯"}}
    result = await build_constraint_pack(state, None)
    groups = partition_constraint_pack(result)
    assert [entry["value"] for entry in groups["current"]] == ["本次希望避免长楼梯"]
    assert [entry["value"] for entry in groups["reference"]] == ["历史上希望少走路"]
    assert {ref["source"] for ref in groups["current"][0]["source_refs"]} == {"preset"}
    assert {ref["source"] for ref in groups["reference"][0]["source_refs"]} == {"manual_profile"}


def test_historical_allergy_is_not_presented_as_current_user_statement():
    historical = item("manual_profile", "食物过敏", category="food_allergy")
    current = item("current_query", "食物过敏", category="food_allergy")
    assert dining_allergy_reminders(pack_of(historical)) == []
    prompt = format_constraint_pack_for_prompt(pack_of(historical))
    assert "历史画像" in prompt and "食物过敏" in prompt
    assert "用餐提醒" not in prompt and "请确认" not in prompt
    assert dining_allergy_reminders(pack_of(current))


def test_normalize_old_mixed_pack_without_mutation_and_keep_applied_preset():
    mixed = item("manual_profile", "住宿特别安静", category="accommodation_preference")
    mixed.update(type="hard", priority="hard", enforcement_scope=["candidate"])
    mixed["source_refs"].append({"source": "preset", "origin_ref": "preset.constraints.accommodation_preference"})
    old = {**pack_of(mixed), "pack_meta": {"run_id": "old", "custom": "preserve"}}
    snapshot = deepcopy(old)

    result = normalize_constraint_pack(old, preset_pack_constraints={"accommodation_preference": "住宿特别安静"})
    groups = partition_constraint_pack(result)
    assert old == snapshot
    assert result["pack_meta"] == snapshot["pack_meta"]
    assert len(groups["reference"]) == 1 and groups["reference"][0]["source_refs"] == mixed["source_refs"]
    assert groups["reference"][0]["type"] == "soft"
    assert [entry["value"] for entry in groups["current"]] == ["住宿特别安静"]
    assert groups["current"][0]["type"] == "soft"
    assert result["hard_constraints"] == []


def test_changed_preset_keeps_old_source_as_reference_and_new_as_current():
    previous = item("preset", "此前希望慢游", category="pace_preference")
    original_refs = deepcopy(previous["source_refs"])
    result = normalize_constraint_pack(pack_of(previous), preset_pack_constraints={"pace_preference": "本次必须早出发"})
    groups = partition_constraint_pack(result)
    assert [entry["value"] for entry in groups["current"]] == ["本次必须早出发"]
    assert [entry["value"] for entry in groups["reference"]] == ["此前希望慢游"]
    assert groups["reference"][0]["source_refs"][0] == {**original_refs[0], "scope": "historical"}
    assert describe_constraint_sources(groups["reference"][0]) == "历史预设"
    assert groups["current"][0]["type"] == "soft"
    assert "本次必须早出发" in format_constraint_pack_for_prompt(result).split("【其他来源参考】", 1)[0]


@pytest.mark.parametrize("supplied", [None, {}])
async def test_resume_without_a_new_preset_keeps_prior_applied_preset(supplied):
    previous = item("preset", "行程特别悠闲", category="pace_preference")
    state = {"constraint_pack": pack_of(previous), "preset_pack_constraints": supplied}
    result = await build_constraint_pack(state, None)
    groups = partition_constraint_pack(result)
    assert [entry["value"] for entry in groups["current"]] == ["行程特别悠闲"]
    assert groups["reference"] == []
    assert groups["current"][0]["type"] == "soft"
