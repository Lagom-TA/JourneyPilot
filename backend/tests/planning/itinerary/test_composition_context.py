

from tests.fixtures.planning_state import make_planning_state
from travel_agent.planning.itinerary.prompts import _build_composition_prompt


def test_fixed_composition_contract_does_not_change_with_task_or_schema_scope():
    original = make_planning_state()
    changed = original.model_copy(
        update={
            "run_id": "another",
            "composition_failure_context": "repair gap",
            "session_anchor": {
                "summary": "prior Tokyo fact",
                "key_constraints": ["不要爬楼"],
            },
        }
    )
    first = _build_composition_prompt(
        original, "Tokyo museum", required_candidate_kinds={"visit"}
    )
    second = _build_composition_prompt(
        changed, "Tokyo dining", required_candidate_kinds={"visit", "dining"}
    )
    assert first.system == second.system
    assert first.runtime != second.runtime
    assert "Tokyo dining" not in second.system
    assert second.runtime.count("不要爬楼") == 1
    assert second.runtime.count("prior Tokyo fact") == 1
    assert "<json_schema>" in second.runtime and "<json_schema>" not in second.system
    assert "dining" in second.runtime and "repair gap" in second.runtime
