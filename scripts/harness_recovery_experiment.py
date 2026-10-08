"""Execute full/deferred ReAct recovery against real Gateway and memory stores.

The model and provider fixtures are deterministic, with no paid calls or
business database access. Cold/warm here means invocation-local fixture reads;
it never asserts a provider API prefix cache hit or successful trip delivery.
"""
import asyncio
from copy import deepcopy
from itertools import product
import json
from pathlib import Path
from unittest.mock import patch

from travel_agent.agents import utils
from travel_agent.config import ToolExposureConfig
from travel_agent.infrastructure.tool_audit_store import InMemoryToolAuditStore
from travel_agent.infrastructure.worker_journal_store import InMemoryWorkerJournalStore
from travel_agent.tools.exposure import apply_tool_exposure
from travel_agent.tools.gateway import ToolGateway
from travel_agent.tools.registry import ToolRegistry
from travel_agent.workflows.worker_recovery import WorkerJournal, current_worker_journal


class FixtureLLM:
    def __init__(self, deferred, raw):
        self.deferred, self.raw = deferred, raw
        self.requests = []

    async def astream_with_tools(self, messages, schemas):
        self.requests.append(deepcopy(messages))
        call_names = [tc["name"] for m in messages for tc in m.get("tool_calls", [])]
        if self.deferred and "search_tools" not in call_names:
            calls = [{"id": "search", "name": "search_tools", "arguments": {"query": "fixture"}}]
            content = ""
        elif "fixture_read" not in call_names:
            calls = [{"id": f"read_{n}", "name": "fixture_read", "arguments": {"n": n}} for n in (1, 2)]
            content = ""
        else:
            calls, content = [], self.raw
        yield {"type": "finish", "tool_calls": calls, "content": content,
               "assistant_replay": {"reasoning_content": "opaque fixture reasoning"}}


async def scenario(cache, mode, complexity, tool_mode):
    run_id = f"fixture_{cache}_{mode}_{complexity}_{tool_mode}"
    registry, audit, store = ToolRegistry(), InMemoryToolAuditStore(), InMemoryWorkerJournalStore()
    provider_calls = []
    async def lookup(n):
        provider_calls.append(n)
        return {"success": True, "results": [{"name": "Museum", "place_id": f"fixture_{n}"}]}
    registry.register("fixture_read", "fixture fact lookup", {"type": "object", "properties": {"n": {"type": "integer"}}}, lookup)
    tools = registry.get_tools_as_schemas()
    config = ToolExposureConfig(mode=tool_mode, min_tools_threshold=1)
    worker = "destination_researcher"
    from tests.test_research_context import make_packet
    packet = make_packet()
    raw = packet.model_dump_json()
    llm = FixtureLLM(tool_mode == "deferred", raw)
    messages = [{"role": "system", "content": "Only return typed packet grounded in fixture observations."},
                {"role": "user", "content": "补研目标 fixture_1" if mode == "supplement" else "research",
                 "scenario_constraints": ["不爬楼", "预算3000"] if complexity == "complex" else []}]
    journal = WorkerJournal(store, run_id, "scope", 0, {}, None)
    context = {"run_id": run_id, "tool_audit_store": audit, "tool_gateway": ToolGateway()}
    def stop(node):
        if mode == "resume" and provider_calls == [1]:
            raise asyncio.CancelledError()
    with patch.object(utils, "get_tool_registry", lambda: registry), patch.object(utils, "apply_tool_exposure", lambda items, node: apply_tool_exposure(items, node, config=config)):
        token = current_worker_journal.set(journal)
        try:
            with patch.object(utils, "check_cancel_requested", stop):
                try:
                    result = await utils.streaming_react_loop(llm, messages, tools, None, worker, tool_context=context)
                except asyncio.CancelledError:
                    version, payload = await store.load(run_id, "scope")
                    journal = WorkerJournal(store, run_id, "scope", version, payload, None)
                    current_worker_journal.set(journal)
                    with patch.object(utils, "check_cancel_requested", lambda *a: None):
                        result = await utils.streaming_react_loop(llm, messages, tools, None, worker, tool_context=context)
            if cache == "warm":
                # Replay final round with a reopened invocation journal.
                version, payload = await store.load(run_id, "scope")
                current_worker_journal.set(WorkerJournal(store, run_id, "scope", version, payload, None))
                replay = await utils.streaming_react_loop(llm, messages, tools, None, worker, tool_context=context)
                assert replay == result
        finally:
            current_worker_journal.reset(token)
    assert provider_calls == [1, 2]
    assert len(audit.records) == 2
    assert result[0] == raw and len(result[3]) == 2
    paired = {m["tool_call_id"] for m in messages if m["role"] == "tool"}
    expected = {tc["id"] for m in messages for tc in m.get("tool_calls", [])}
    assert paired == expected
    return {"scenario": {"cache": cache, "run_mode": mode, "complexity": complexity, "tool_mode": tool_mode},
            "measurement": "fake_model_real_gateway", "contract_passed": True, "provider_calls": len(provider_calls),
            "audit_records": len(audit.records), "model_requests": len(llm.requests),
            "typed_fixture_transcript_preserved": True, "delivery_succeeded": None,
            "api_cache_hit": None, "cost_usd": None}


async def main():
    rows = []
    for case in product(("cold", "warm"), ("new", "supplement", "resume"), ("simple", "complex"), ("full", "deferred")):
        rows.append(await scenario(*case))
    path = Path("temp/harness-review-2026-10-05/recovery-matrix.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"scenarios": len(rows), "passed": sum(r["contract_passed"] for r in rows), "measurement": "fake model / real Gateway / memory audits and journal"}))


if __name__ == "__main__":
    asyncio.run(main())
