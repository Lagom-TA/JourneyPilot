"""Harness fixture matrix, paid protocol calibration, and JSONL aggregation.

PYTHONPATH=src:. <venv>/bin/python scripts/harness_experiments.py matrix --output ...
PYTHONPATH=src:. <venv>/bin/python scripts/harness_experiments.py live --output ...
PYTHONPATH=src:. <venv>/bin/python scripts/harness_experiments.py analyze --input ...

Live is explicit and billed. It uses configured exact primary/fast models and
prices, never writes business DB, and stores no credentials. Protocol probes
are not end-to-end delivery or production cache/cost benchmarks.
"""
import argparse
import asyncio
import hashlib
from itertools import product
import json
from pathlib import Path
import time
import uuid

from travel_agent.agents.research_packet_prompt import build_research_packet_prompt
from travel_agent.config import ToolExposureConfig, get_settings
from travel_agent.infrastructure.cost_ledger_store import build_ledger_call
from travel_agent.models.experiments import summarize_trials
from travel_agent.models.router import ModelTier, OpenAICompatibleLLM
from travel_agent.models.usage import UsageRecorder
from travel_agent.models.token_counting import estimate_request_tokens
from travel_agent.tools.exposure import apply_tool_exposure, attach_tool_catalog
from travel_agent.workflows.run_control import current_run_id, current_node


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def matrix():
    from tests.test_research_context import make_packet, _query
    from travel_agent.memory.research_context import format_worker_research_context
    packet = make_packet(entities=(("visit_a", "tokyo"), ("visit_b", "tokyo")))
    tools = [{"schema": {"type": "function", "function": {"name": f"read_{i}", "description": "Read observed provider facts", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}} for i in range(8)]
    rows = []
    for cache, run_mode, complexity, tool_mode in product(("cold", "warm"), ("new", "supplement", "resume"), ("simple", "complex"), ("full", "deferred")):
        case = dict(cache=cache, run_mode=run_mode, complexity=complexity, tool_mode=tool_mode)
        trial_id = hashlib.sha256(json.dumps(case, sort_keys=True).encode()).hexdigest()[:16]
        assignment = {"excluded_candidate_ids": ["visit_a"]} if run_mode == "supplement" else {}
        projection = format_worker_research_context({packet.research_packet_id: packet}, worker_kind="accommodation_researcher",
            run_id="run_test", generation_id="generation_test", planned_queries=[_query()], assignment=assignment)
        prompt = build_research_packet_prompt(worker_kind="accommodation_researcher", run_id="run_test", task_id="task",
            current_time="2026-10-08 12:00", constraint_pack_revision=1, fact_data_revision=1,
            candidate_limit=6,
            research_brief_context="预算3000元、不能爬楼、每日一个景点" if complexity == "complex" else "两日旅行",
            upstream_packet_context=projection)
        exposure = apply_tool_exposure(tools, "accommodation_researcher", config=ToolExposureConfig(mode=tool_mode, min_tools_threshold=1))
        messages = attach_tool_catalog([{"role": "system", "content": prompt.system}, {"role": "user", "content": prompt.runtime}], exposure)
        wire = {"messages": messages, "tools": list(exposure.tool_schemas)}
        estimate, schema_estimate = estimate_request_tokens(wire, "deepseek-v4.1-flash")
        rows.append({"call_id": f"offline_{trial_id}", "trial_id": trial_id, "scenario": case,
            "measurement": "offline_fixture", "fixture": "tests/test_research_context.py; synthetic source padding",
            "request_input_tokens_estimate": estimate, "tool_schema_tokens_estimate": schema_estimate,
            "stable_system_sha256": hashlib.sha256(messages[0]["content"].encode()).hexdigest(),
            "input_tokens": None, "cached_input_tokens": None, "usage_complete": False,
            "cost_usd": None, "delivery_succeeded": None, "contract_passed": None,
            "note": "Cold/warm and resume are experiment labels; API cache/recovery are not executed by this matrix."})
    return rows


PROBE_SCHEMA = {"type": "object", "properties": {"budget_cny": {"type": "integer"},
    "days": {"type": "integer"}, "no_stairs": {"type": "boolean"}},
    "required": ["budget_cny", "days", "no_stairs"], "additionalProperties": False}


async def live(output):
    settings = get_settings()
    recorder = UsageRecorder(spool_path=output.with_suffix(".usage.sqlite3"))
    rows = []
    messages = [{"role": "system", "content": "仅提取用户明确旅行约束，返回指定 JSON，不添加或猜测事实。"},
                {"role": "user", "content": "旅行两天，预算总计3000元，不能爬楼。"}]
    for tier, cfg in ((ModelTier.PRIMARY, settings.primary_model), (ModelTier.FAST, settings.fast_model)):
        client = OpenAICompatibleLLM(api_key=cfg.api_key, model_name=cfg.model_name, base_url=cfg.base_url,
            max_tokens=cfg.max_tokens, temperature=cfg.temperature, reasoning_effort=cfg.reasoning_effort,
            timeout=cfg.timeout, max_retries=0, tier=tier, usage_recorder=recorder)
        for repetition in range(2):
            trial_id = f"protocol_{tier.value}_{repetition}_{uuid.uuid4().hex[:8]}"
            run_token = current_run_id.set(trial_id)
            node_token = current_node.set("harness_protocol_probe")
            started = time.perf_counter()
            passed, error_type = False, None
            try:
                response = await client.ainvoke(messages, response_format={"type": "json_schema", "json_schema": {"name": "travel_constraints", "strict": True, "schema": PROBE_SCHEMA}})
                passed = json.loads(response) == {"budget_cny": 3000, "days": 2, "no_stairs": True}
            except Exception as exc:
                error_type = type(exc).__name__  # no credentials or provider error body
            finally:
                current_run_id.reset(run_token)
                current_node.reset(node_token)
            elapsed = (time.perf_counter() - started) * 1000
            batch = recorder.drain(run_id=trial_id)
            for rec in batch:
                call = build_ledger_call(rec, pricing=settings.model_pricing)
                rows.append({"call_id": rec.id, "trial_id": trial_id, "model": rec.model_request,
                    "tier": tier.value, "reasoning_effort": client._reasoning_effort,
                    "scenario": {"cache": "cold_attempt" if repetition == 0 else "warm_attempt", "task": "protocol_calibration"},
                    "measurement": "paid_api", "input_tokens": rec.input_tokens, "output_tokens": rec.output_tokens,
                    "cached_input_tokens": rec.cached_input_tokens, "cache_write_input_tokens": rec.cache_write_input_tokens,
                    "reasoning_output_tokens": rec.reasoning_output_tokens, "usage_complete": rec.usage_complete,
                    "request_input_tokens_estimate": rec.request_input_tokens_estimate,
                    "cost_usd": call.cost_usd, "finish_reason": rec.finish_reason,
                    "run_wall_ms": elapsed, "contract_passed": passed, "error_type": error_type,
                    "delivery_succeeded": None, "note": "Protocol/constraint extraction only; no typed trip delivery."})
            write_rows(output, rows)
            recorder.ack(batch)
            print(json.dumps({"trial_id": trial_id, "model": cfg.model_name, "contract_passed": passed, "error_type": error_type}))
    return rows


async def live_tools(output):
    """Two paid fast requests, with a synthetic observation between them."""
    settings = get_settings()
    cfg = settings.fast_model
    recorder = UsageRecorder(spool_path=output.with_suffix(".usage.sqlite3"))
    client = OpenAICompatibleLLM(api_key=cfg.api_key, model_name=cfg.model_name, base_url=cfg.base_url,
        max_tokens=cfg.max_tokens, temperature=cfg.temperature, reasoning_effort=cfg.reasoning_effort,
        timeout=cfg.timeout, max_retries=0, tier=ModelTier.FAST, usage_recorder=recorder)
    trial = f"tool_protocol_{uuid.uuid4().hex[:12]}"
    run_token = current_run_id.set(trial)
    node_token = current_node.set("harness_tool_protocol")
    messages = [{"role": "system", "content": "这是工具协议测试，先调用 inspect_fixture；然后只引用工具结果，返回 place_id 和 stairs 的 JSON。"},
                {"role": "user", "content": "检查 fixture_museum。"}]
    schema = {"type": "function", "function": {"name": "inspect_fixture", "description": "Return a synthetic fixture observation",
        "parameters": {"type": "object", "properties": {"entity": {"type": "string"}}, "required": ["entity"]}}}
    passed, error_type = False, None
    started = time.perf_counter()
    try:
        initial = await client.ainvoke_with_tools(messages, [schema], tool_choice={"type": "function", "function": {"name": "inspect_fixture"}})
        calls = initial.get("tool_calls", [])
        if not calls or any(call["name"] != "inspect_fixture" for call in calls):
            raise ValueError("unexpected fixture tool call")
        messages.append({"role": "assistant", "content": initial.get("content") or "", "tool_calls": calls,
                         "assistant_replay": initial.get("assistant_replay", {})})
        for call in calls:
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": '{"place_id":"fixture_museum","stairs":false}'})
        response = await client.ainvoke(messages, response_format={"type": "json_object"})
        passed = json.loads(response) == {"place_id": "fixture_museum", "stairs": False}
    except Exception as exc:
        error_type = type(exc).__name__
    finally:
        current_run_id.reset(run_token)
        current_node.reset(node_token)
    batch = recorder.drain(run_id=trial)
    rows = []
    for rec in batch:
        call = build_ledger_call(rec, pricing=settings.model_pricing)
        rows.append({"call_id": rec.id, "trial_id": trial, "model": rec.model_request,
            "reasoning_effort": client._reasoning_effort, "measurement": "paid_api_synthetic_tool",
            "input_tokens": rec.input_tokens, "output_tokens": rec.output_tokens,
            "cached_input_tokens": rec.cached_input_tokens, "reasoning_output_tokens": rec.reasoning_output_tokens,
            "cache_write_input_tokens": rec.cache_write_input_tokens,
            "request_input_tokens_estimate": rec.request_input_tokens_estimate,
            "usage_complete": rec.usage_complete, "cost_usd": call.cost_usd,
            "contract_passed": passed, "delivery_succeeded": None, "error_type": error_type,
            "finish_reason": rec.finish_reason, "run_wall_ms": (time.perf_counter() - started) * 1000})
    write_rows(output, rows)
    recorder.ack(batch)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["matrix", "live", "live-tools", "analyze"])
    parser.add_argument("--output", type=Path, default=Path("temp/harness-experiments/results.jsonl"))
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    if args.mode == "analyze":
        if not args.input:
            parser.error("analyze requires --input")
        rows = [json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
    else:
        rows = matrix() if args.mode == "matrix" else asyncio.run(
            live_tools(args.output) if args.mode == "live-tools" else live(args.output))
        write_rows(args.output, rows)
    print(json.dumps(summarize_trials(rows), ensure_ascii=False, indent=2))
    if args.mode in {"live", "live-tools"} and (not rows or any(
        row.get("contract_passed") is not True or not row.get("usage_complete")
        for row in rows
    )):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
