from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys

import pytest

from travel_agent.infrastructure.cost_ledger_store import InMemoryCostLedgerStore
from travel_agent.models.usage import LLMCallRecord, UsageRecorder
from travel_agent.models.usage_spool import UsageSpoolConflict
from travel_agent.services.usage_flush import UsageFlushService


def record(call_id="a", run="run"):
    return LLMCallRecord(id=call_id, run_id=run, node="worker", agent="worker", tier="fast",
                         provider="test", model_request="test", method="ainvoke", stream=False,
                         start_ts="2026-10-08T00:00:00+00:00", input_tokens=10, output_tokens=5, total_tokens=15)


def test_overflow_never_evicts_and_drain_survives_process_reopen(tmp_path):
    path = tmp_path / "spool.sqlite3"
    recorder = UsageRecorder(maxlen=2, spool_path=path)
    for n in range(7):
        recorder.record(record(str(n)))
    assert recorder.dropped == 0
    batch = recorder.drain()
    assert len(batch) == 2
    reopened = UsageRecorder(spool_path=path)
    assert len(reopened.snapshot()) == 7  # drain never removes before DB commit
    reopened.ack(batch)
    assert len(reopened.snapshot()) == 5
    assert path.stat().st_mode & 0o777 == 0o600


async def test_commit_before_ack_replay_is_idempotent(tmp_path):
    path = tmp_path / "spool.sqlite3"
    recorder = UsageRecorder(spool_path=path)
    recorder.record(record())
    store = InMemoryCostLedgerStore()
    await store.record_calls(recorder.drain(), pricing=[])
    reopened = UsageRecorder(spool_path=path)
    await UsageFlushService(reopened, store).flush()
    assert len(store.calls) == 1 and not reopened.snapshot()
    assert reopened.integrity("run")["capture_complete"]


def test_same_id_payload_conflict_and_stale_ack_are_rejected(tmp_path):
    recorder = UsageRecorder(spool_path=tmp_path / "spool.sqlite3")
    rec = record()
    recorder.record(rec)
    with pytest.raises(UsageSpoolConflict):
        recorder.record(replace(rec, output_tokens=6))
    recorder.ack([replace(rec, output_tokens=7)])
    assert len(recorder.snapshot()) == 1


async def test_partial_commit_then_conflict_does_not_block_other_runs():
    recorder = UsageRecorder()
    recorder.record(record("poison"))
    recorder.record(record("good", "other"))
    store = InMemoryCostLedgerStore()
    await store.record_calls([replace(record("poison"), input_tokens=50)], pricing=[])
    await UsageFlushService(recorder, store).flush()
    assert {rec.id for rec in recorder.snapshot()} == {"poison"}
    assert {call.id for call in store.calls} == {"poison", "good"}
    assert recorder.integrity("run")["capture_complete"] is False
    assert recorder.integrity("other")["capture_complete"] is True


def test_admission_survives_process_death_with_unknown_usage(tmp_path):
    path = tmp_path / "spool.sqlite3"
    script = """
import os,sys
from travel_agent.models.usage import UsageRecorder,LLMCallRecord
r=UsageRecorder(spool_path=sys.argv[1])
r.admit(LLMCallRecord(id='crashed',run_id='run',node=None,agent=None,tier='fast',provider='test',model_request='test',method='ainvoke',stream=False,start_ts='2026-10-08T00:00:00+00:00'))
os._exit(0)
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    subprocess.run([sys.executable, "-c", script, str(path)], check=True, env=env)
    recovered = UsageRecorder(spool_path=path).snapshot()[0]
    assert recovered.id == "crashed" and recovered.status == "interrupted"
    assert recovered.input_tokens is None and recovered.output_tokens is None
    assert recovered.usage_source == "missing" and not recovered.usage_complete


async def test_database_outage_retains_records_for_later_flush():
    recorder = UsageRecorder()
    recorder.record(record())
    class Unavailable:
        async def record_calls(self, records):
            raise ConnectionError()
    await UsageFlushService(recorder, Unavailable()).flush()
    assert len(recorder.snapshot()) == 1
    store = InMemoryCostLedgerStore()
    await UsageFlushService(recorder, store).flush()
    assert len(store.calls) == 1 and len(recorder.snapshot()) == 0


def test_write_failure_keeps_record_and_explicit_incomplete_state(monkeypatch):
    recorder = UsageRecorder()
    monkeypatch.setattr(recorder._spool, "put", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    recorder.record(record())
    assert len(recorder.snapshot()) == 1
    assert not recorder.integrity("run")["capture_complete"]
    assert recorder.integrity("run")["spool_write_failed"] == 1


def test_concurrent_capture_conflict_is_not_last_writer_wins(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    path = tmp_path / "spool.sqlite3"
    recorders = [UsageRecorder(spool_path=path), UsageRecorder(spool_path=path)]
    barrier = Barrier(2)
    def capture(n):
        barrier.wait()
        try:
            recorders[n].record(replace(record(), output_tokens=5 + n))
            return "ok"
        except UsageSpoolConflict:
            return "conflict"
    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(capture, range(2)))
    assert sorted(outcomes) == ["conflict", "ok"]
    assert len(recorders[0].snapshot()) == 1


def test_reused_pid_does_not_hide_abandoned_attempt():
    recorder = UsageRecorder()
    recorder.admit(record())
    with recorder._spool.db:
        recorder._spool.db.execute("UPDATE usage_outbox SET owner_token='old_process'")
    assert recorder.snapshot()[0].status == "interrupted"


async def test_changed_price_does_not_reprice_idempotent_ledger_capture():
    from travel_agent.config import ModelPricingItem
    store = InMemoryCostLedgerStore()
    old = ModelPricingItem(pattern="test", input_per_1m=2, output_per_1m=10)
    new = old.model_copy(update={"input_per_1m": 30, "output_per_1m": 100})
    await store.record_calls([record()], pricing=[old])
    price = store.calls[0].cost_usd
    await store.record_calls([record()], pricing=[new])
    assert len(store.calls) == 1 and store.calls[0].cost_usd == price


def test_pending_capture_is_not_a_complete_zero_bill():
    from travel_agent.infrastructure.cost_ledger_store import summarize_calls
    recorder = UsageRecorder()
    recorder.record(record())
    summary = recorder.apply_integrity(summarize_calls("run", []))
    assert summary["total_tokens"] is None and summary["total_input_tokens"] is None
    assert not summary["cost_complete"] and not summary["token_usage_complete"]
    assert summary["record_failed"] == 1


def test_concurrent_startup_upgrades_old_spool_without_volatile_fallback(tmp_path):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as database:
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("CREATE TABLE usage_outbox (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, phase TEXT NOT NULL, pid INTEGER NOT NULL, payload TEXT NOT NULL)")
    barrier = Barrier(4)
    def open_recorder(n):
        barrier.wait()
        recorder = UsageRecorder(spool_path=path)
        recorder.record(replace(record(), id=f"call_{n}"))
        return recorder
    with ThreadPoolExecutor(4) as pool:
        recorders = list(pool.map(open_recorder, range(4)))
    assert all(recorder._spool is not None for recorder in recorders)
    assert len(recorders[0].snapshot()) == 4
    assert all(recorder.integrity("run")["spool_write_failed"] == 0 for recorder in recorders)
