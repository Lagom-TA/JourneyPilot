import pytest

from travel_agent.models.experiments import summarize_trials


def test_unknown_usage_or_no_delivery_never_claims_success_cost():
    row = {"call_id": "a", "trial_id": "trial", "input_tokens": None,
           "cached_input_tokens": None, "cost_usd": None, "delivery_succeeded": None}
    result = summarize_trials([row, row])
    assert result["call_count"] == 1
    assert result["total_cost_usd"] is None
    assert result["successful_deliveries"] is None
    assert result["successful_delivery_cost_usd"] is None


def test_weighted_cache_and_failed_run_cost_enter_success_delivery_metric():
    rows = [
        {"call_id": "a", "trial_id": "ok", "input_tokens": 100, "cached_input_tokens": 50,
         "cost_usd": 1, "usage_complete": True, "delivery_succeeded": True, "run_wall_ms": 100},
        {"call_id": "b", "trial_id": "failed", "input_tokens": 300, "cached_input_tokens": 0,
         "cost_usd": 2, "usage_complete": True, "delivery_succeeded": False, "run_wall_ms": 300, "finish_reason": "length"},
    ]
    result = summarize_trials(rows)
    assert result["weighted_cache_hit"] == 50 / 400
    assert result["successful_delivery_cost_usd"] == 3
    assert result["delivery_success_rate"] == .5
    assert result["p95_run_wall_ms"] == 300 and result["truncated_calls"] == 1
    with pytest.raises(ValueError, match="conflicting"):
        summarize_trials([rows[0], {**rows[0], "cost_usd": 3}])


def test_matrix_labels_do_not_fabricate_live_metrics():
    from scripts.harness_experiments import matrix
    rows = matrix()
    assert len(rows) == 24
    assert all(row["measurement"] == "offline_fixture" for row in rows)
    assert all(row["input_tokens"] is None and row["cost_usd"] is None for row in rows)
    assert len({row["stable_system_sha256"] for row in rows}) == 2  # full/deferred catalogs
