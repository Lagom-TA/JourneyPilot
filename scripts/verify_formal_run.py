"""Capture a real API/SSE run; never replace providers, gates, or persistence.

Run inside the project's Docker environment. Paid requests require --live.
Supply the same JSON request a traveller would send to /api/chat-stream.
The output contains public SSE data and read-only API snapshots.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import time

import httpx


async def capture(base_url: str, request: dict, output: Path) -> dict:
    started = time.monotonic()
    counts: Counter = Counter()
    run_id = request.get("run_id")
    session_id = request.get("session_id")
    terminal = None
    output.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(900, connect=10)) as client:
        ready = await client.get("/api/health/ready")
        ready.raise_for_status()
        with output.open("w", encoding="utf-8") as handle:
            async with client.stream("POST", "/api/chat-stream", json=request) as response:
                response.raise_for_status()
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    raise RuntimeError("API did not return SSE")
                data = []

                def record_event() -> None:
                    nonlocal run_id, session_id, terminal
                    if not data:
                        return
                    event = json.loads("\n".join(data))
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                    handle.flush()
                    kind = event.get("type", "unknown")
                    counts[kind] += 1
                    run_id = event.get("run_id") or run_id
                    session_id = event.get("session_id") or session_id
                    if kind in {"chat_start", "interrupt", "delivery_ready", "run_terminal", "chat_complete", "error", "run_cancelled", "run_failed"}:
                        print(json.dumps({"type": kind, "run_id": run_id,
                                          "elapsed_seconds": round(time.monotonic() - started, 2)}, ensure_ascii=False), flush=True)
                    if kind in {"run_terminal", "chat_complete", "run_cancelled", "run_failed"}:
                        terminal = event
                    data.clear()

                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    elif not line:
                        record_event()
                record_event()
        snapshots = {}
        if run_id:
            for name, suffix in (("run", ""), ("events", "/events"), ("bundle", "/bundle/current")):
                response = await client.get(f"/api/trip-runs/{run_id}{suffix}")
                snapshots[name] = {"http_status": response.status_code, "body": response.json()}
        report = {"scope": "real_api_sse", "run_id": run_id, "session_id": session_id,
                  "wall_seconds": round(time.monotonic() - started, 2), "event_counts": dict(counts),
                  "terminal": terminal, "snapshots": snapshots}
        output.with_suffix(".summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required: this calls real paid models and writes a real TripRun")
    report = asyncio.run(capture(args.url, json.loads(args.request.read_text()), args.output))
    print(json.dumps({key: report[key] for key in ("run_id", "wall_seconds", "event_counts")}, ensure_ascii=False))
    if not report["terminal"]:
        raise SystemExit("SSE ended without a terminal event; inspect the captured evidence")


if __name__ == "__main__":
    main()
