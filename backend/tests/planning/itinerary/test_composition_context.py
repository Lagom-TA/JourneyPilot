from tests.fixtures.planning_state import make_planning_state
from tests.fixtures.research_catalog import make_intent_spec, make_research_intent
from travel_agent.planning.itinerary.prompts import _build_composition_prompt
from travel_agent.planning.requirements.intent_contracts import IntentStrength


def _planning_state_with_requirements():
    spec = make_intent_spec(
        make_research_intent(
            "intent_hard", "必去东京国立博物馆", strength=IntentStrength.HARD
        ),
        make_research_intent(
            "intent_soft", "喜欢建筑摄影", strength=IntentStrength.SOFT
        ),
        make_research_intent(
            "intent_info", "住在东京站附近", strength=IntentStrength.INFORMATIONAL
        ),
    )
    return make_planning_state().model_copy(
        update={"intent_spec": spec, "intent_spec_revision": spec.revision}
    )


def test_user_requirements_are_injected_as_planning_guidance():
    original = _planning_state_with_requirements()
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

    for summary in ("必去东京国立博物馆", "喜欢建筑摄影", "住在东京站附近"):
        assert summary in first.runtime
    assert "<user_requirements>" in first.runtime
    assert "<json_schema>" in second.runtime and "<json_schema>" not in second.system
    assert "does not match the required structure" in second.runtime


def test_composition_prompt_has_no_acceptance_or_gate_wording():
    prompt = _build_composition_prompt(
        _planning_state_with_requirements(), "Tokyo museum"
    )
    combined = prompt.system + prompt.runtime
    for phrase in (
        "验收",
        "忠实度",
        "never_violate",
        "repair_then_deviate",
        "Composition Rules",
        "必须覆盖",
        "整份组合被拒",
        "回炉",
    ):
        assert phrase not in combined
    assert "请按用户的这些要求规划行程" in prompt.system
