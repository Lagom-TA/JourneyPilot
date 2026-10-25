"""Reproducible trial aggregation; unknown bills and delivery stay unknown."""
from collections import defaultdict
import math


def summarize_trials(rows):
    unique = {}
    for row in rows:
        key = row["call_id"]
        if key in unique and unique[key] != row:
            raise ValueError("conflicting experiment call_id")
        unique[key] = row
    calls = list(unique.values())
    trials = defaultdict(list)
    for row in calls:
        trials[row["trial_id"]].append(row)
    input_known = all(row.get("input_tokens") is not None for row in calls)
    cache_known = input_known and all(row.get("cached_input_tokens") is not None for row in calls)
    cost_known = bool(calls) and all(row.get("cost_usd") is not None and row.get("usage_complete") for row in calls)
    inputs = sum(row.get("input_tokens") or 0 for row in calls)
    cached = sum(row.get("cached_input_tokens") or 0 for row in calls)
    total_cost = sum(row.get("cost_usd") or 0 for row in calls)
    successes = sum(any(row.get("delivery_succeeded") is True for row in trial) for trial in trials.values())
    delivery_observed = bool(trials) and all(any(row.get("delivery_succeeded") is not None for row in trial) for trial in trials.values())
    walls = sorted(max(row["run_wall_ms"] for row in trial if row.get("run_wall_ms") is not None)
                   for trial in trials.values() if any(row.get("run_wall_ms") is not None for row in trial))
    return {
        "call_count": len(calls), "trial_count": len(trials),
        "total_input_tokens": inputs if input_known else None,
        "weighted_cache_hit": cached / inputs if cache_known and inputs else None,
        "total_cost_usd": total_cost if cost_known else None,
        "cost_complete": cost_known,
        "successful_deliveries": successes if delivery_observed else None,
        "successful_delivery_cost_usd": total_cost / successes if cost_known and delivery_observed and successes else None,
        "delivery_success_rate": successes / len(trials) if delivery_observed else None,
        "p95_run_wall_ms": walls[math.ceil(len(walls) * .95) - 1] if walls else None,
        "truncated_calls": sum(row.get("finish_reason") == "length" for row in calls),
        "repair_calls": sum(bool(row.get("repair_round")) for row in calls),
        "contract_passed_calls": sum(row.get("contract_passed") is True for row in calls),
        "missing_usage_calls": sum(not row.get("usage_complete") for row in calls),
    }
