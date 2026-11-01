from tests.fixtures.planning_state import make_planning_state
from travel_agent.planning.itinerary.prompts import _build_composition_prompt


def test_user_requirements_are_injected_as_planning_guidance():
    original = make_planning_state().model_copy(
        update={
            "current_requirements": "必去东京国立博物馆，喜欢建筑摄影，住在东京站附近",
        }
    )
    changed = original.model_copy(
        update={
            "run_id": "another",
            "composition_failure_context": "itinerary composition does not match the required structure",
            "session_anchor": {
                "summary": "prior Tokyo fact",
                "key_constraints": ["不要爬楼"],
            },
        }
    )
    first = _build_composition_prompt(original, "Tokyo museum")
    second = _build_composition_prompt(changed, "Tokyo dining")

    assert first.system == second.system
    assert first.runtime != second.runtime
    assert "Tokyo dining" not in second.system
    assert second.runtime.count("不要爬楼") == 1
    assert second.runtime.count("prior Tokyo fact") == 1
    assert "必去东京国立博物馆" in first.runtime
    assert "<user_requirements>" in first.runtime
    assert "<json_schema>" in second.runtime and "<json_schema>" not in second.system
    assert "does not match the required structure" in second.runtime


def test_composition_prompt_has_no_acceptance_or_gate_wording():
    prompt = _build_composition_prompt(make_planning_state(), "Tokyo museum")
    combined = prompt.system + prompt.runtime
    for phrase in ("验收", "忠实度", "never_violate", "repair_then_deviate", "Composition Rules", "必须覆盖", "整份组合被拒", "回炉"):
        assert phrase not in combined
    assert "按用户需求规划行程" in prompt.system
