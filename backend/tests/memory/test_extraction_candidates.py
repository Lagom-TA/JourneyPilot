from unittest.mock import AsyncMock

from travel_agent.memory.memory_extractor import MemoryExtractor, _parse_extraction_result
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
