import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from travel_agent.memory.memory_extractor import (
    MemoryExtractionContext, MemoryExtractor, _parse_extraction_result, _parse_removals,
)
from travel_agent.runtime.job_contracts import BackgroundJob, BackgroundJobType


def test_portrait_requires_a_valid_fact_reference():
    facts, portraits = _parse_extraction_result({
        "facts": [
            {"content": "  ", "category": "preference", "importance": 5},
            {"content": "吃素", "category": "preference", "importance": 5},
        ],
        "portrait": [
            {"trait": "无依据", "dimension": "lifestyle", "supporting_fact_indexes": [0]},
            {"trait": "素食", "dimension": "lifestyle", "supporting_fact_indexes": [1]},
        ],
    })
    assert [fact.content for fact in facts] == ["吃素"]
    assert [item["trait"] for item in portraits] == ["素食"]


async def test_reclaimed_job_with_committed_marker_skips_model_call():
    extractor = MemoryExtractor()
    extractor._call_llm = AsyncMock(side_effect=AssertionError("已提交的任务不应重调模型"))
    job = BackgroundJob(
        job_id="job", job_type=BackgroundJobType.MEMORY_EXTRACTION,
        dedupe_key="turn", lease_owner="new-owner",
        result={"memory_extraction_committed": {"facts": 1, "portraits": 1}},
    )
    outcome = await extractor.extract_from_turn("local", "session", "吃素", job=job)
    assert (outcome.facts_written, outcome.portraits_written) == (1, 1)
    extractor._call_llm.assert_not_awaited()


def test_changes_require_a_current_target_and_user_evidence():
    facts = {"1": {"content": "吃素", "memory_revision": 5}}
    history = [{"operation": "delete_fact", "revision": 7, "items": [{"content": "喜欢海鲜"}]}]
    result = {
        "facts": [
            {"action": "update", "fact_id": "1", "content": "不吃素", "category": "preference",
             "importance": 6, "user_evidence": "以后不吃素了"},
            {"action": "update", "fact_id": "99", "content": "不存在", "category": "preference",
             "importance": 6, "user_evidence": "以后不吃素了"},
        ],
        "delete_facts": [
            {"fact_id": "1", "user_evidence": "没有说过的话"},
            {"fact_id": "1", "management_revision": 7},
        ],
    }
    old_turn, _ = _parse_extraction_result(
        result, user_message="以后不吃素了", known_facts=facts, management_history=history, turn_revision=4,
    )
    assert old_turn == []
    new_turn, _ = _parse_extraction_result(
        result, user_message="以后不吃素了", known_facts=facts, management_history=history, turn_revision=5,
    )
    assert [item.fact_id for item in new_turn] == ["1"]
    removals = _parse_removals(
        result, "delete_facts", "fact_id", facts, user_message="其他内容",
        management_history=history, turn_revision=4,
    )
    assert removals == [1]
    result["delete_facts"][1]["management_revision"] = 5
    history[0]["revision"] = 5
    assert _parse_removals(
        result, "delete_facts", "fact_id", facts, user_message="其他内容",
        management_history=history, turn_revision=4,
    ) == []
    result["delete_facts"][1]["management_revision"] = 7
    history[0]["revision"] = 3
    assert _parse_removals(
        result, "delete_facts", "fact_id", facts, user_message="其他内容",
        management_history=history, turn_revision=4,
    ) == []


async def test_summary_prompt_separates_rules_current_memory_and_manual_actions(monkeypatch):
    from travel_agent.llm import router

    model = SimpleNamespace(ainvoke=AsyncMock(return_value='{"facts": [], "portrait": []}'))
    monkeypatch.setattr(router, "get_model_router", lambda: SimpleNamespace(get_fast=lambda: model))
    context = MemoryExtractionContext(
        facts=[{"fact_id": "3", "content": "吃素", "memory_revision": 4}],
        relations=[{"relation_id": "2", "trait": "素食", "memory_revision": 4}],
        management_history=[{"operation": "delete_fact", "revision": 5, "items": [{"content": "不吃辣"}]}],
        portrait="素食", revision=5, preferences={"pace": "轻松悠闲"},
    )
    user_message = "补充说明。" * 200 + "请重新记住我不吃辣"
    await MemoryExtractor()._call_llm(user_message, context, 5)
    messages = model.ainvoke.await_args.args[0]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert "手动删除" in messages[0]["content"]
    data = json.loads(messages[1]["content"])
    assert data["user_message"] == user_message
    assert data["current_facts"] == context.facts
    assert data["current_preferences"] == context.preferences
    assert data["manual_management_history"] == context.management_history
    assert data["turn_revision"] == 5
