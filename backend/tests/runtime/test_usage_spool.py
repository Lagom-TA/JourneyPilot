import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from travel_agent.llm.usage import LLMCallRecord, UsageRecorder
from travel_agent.llm.usage_spool import UsageSpoolConflict
from travel_agent.runtime.usage_flush import UsageFlushService
from travel_agent.storage.cost_ledger_store import InMemoryCostLedgerStore


def record(call_id="a", run="run"):
    return LLMCallRecord(id=call_id, run_id=run, node="worker", agent="worker", tier="fast",
                         provider="test", model_request="test", method="ainvoke", stream=False,
                         start_ts="2026-10-08T00:00:00+00:00", input_tokens=10, output_tokens=5, total_tokens=15)


def test_overflow_never_evicts_and_drain_survives_process_reopen(tmp_path):
    path = tmp_path / "spool.sqlite3"
    recorder = UsageRecorder(maxlen=2, spool_path=path)
    for n in range(7):
        recorder.record(record(str(n)))
    batch = recorder.drain()
    assert len(batch) == 2
    reopened = UsageRecorder(spool_path=path)
    assert len(reopened.snapshot()) == 7  # drain 在数据库提交之前不删除记录
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
    recorder.ack([replace(rec, output_tokens=7)])
    assert recorder.snapshot() == [rec]
    with pytest.raises(UsageSpoolConflict):
        recorder.record(replace(rec, output_tokens=6))
    recorder.ack([rec])
    assert recorder.snapshot() == []
    assert UsageRecorder(spool_path=tmp_path / "spool.sqlite3").snapshot() == [rec]
    assert not recorder.integrity("run")["capture_complete"]


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


def test_usage_spool_survives_process_death_with_unknown_usage(tmp_path):
    path = tmp_path / "spool.sqlite3"
    script = """
import os,sys
from travel_agent.llm.usage import UsageRecorder,LLMCallRecord
r=UsageRecorder(spool_path=sys.argv[1])
r.admit(LLMCallRecord(id='crashed',run_id='run',node=None,agent=None,tier='fast',provider='test',model_request='test',method='ainvoke',stream=False,start_ts='2026-10-08T00:00:00+00:00'))
os._exit(0)
"""
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
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
    for _ in range(3):
        assert recorder.snapshot() == [record()]
        assert not recorder.integrity("run")["capture_complete"]
        assert recorder.integrity("run")["spool_write_failed"] == 1


def test_filtered_drain_persists_only_completed_records_for_selected_run(tmp_path, monkeypatch):
    path = tmp_path / "spool.sqlite3"
    recorder = UsageRecorder(spool_path=path)
    put = recorder._spool.put

    def unavailable(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(recorder._spool, "put", unavailable)
    completed = record()
    other = record("other-call", "other")
    started = record("started")
    recorder.record(completed)
    recorder.record(other)
    recorder.admit(started)
    monkeypatch.setattr(recorder._spool, "put", put)

    assert recorder.drain(run_id="run") == [completed]
    reopened = UsageRecorder(spool_path=path)
    assert reopened.drain() == [completed]
    assert reopened.integrity("run")["spool_write_failed"] == 2
    assert reopened.integrity("other")["pending_call_count"] == 0
    assert recorder.integrity("run")["pending_call_count"] == 2
    assert {rec.id for rec in recorder.drain()} == {completed.id, other.id}
    assert {rec.id for rec in reopened.drain()} == {completed.id, other.id}
    assert reopened.integrity("other")["spool_write_failed"] == 1
    assert recorder.integrity("run")["spool_write_failed"] == 2


async def test_flush_persists_recovered_capture_before_cost_database_recovers(tmp_path, monkeypatch):
    from unittest.mock import Mock

    path = tmp_path / "spool.sqlite3"
    recorder = UsageRecorder(spool_path=path)
    put = recorder._spool.put
    attempts = 0

    def fail_first_write(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("disk full")
        return put(*args, **kwargs)

    monkeypatch.setattr(recorder._spool, "put", fail_first_write)
    ack = Mock(wraps=recorder.ack)
    monkeypatch.setattr(recorder, "ack", ack)
    recorder.record(record())

    class Unavailable:
        async def record_calls(self, records):
            raise ConnectionError("cost database unavailable")

    service = UsageFlushService(recorder, Unavailable())
    await service.flush()
    await service.flush()
    ack.assert_not_called()
    assert attempts == 2
    reopened = UsageRecorder(spool_path=path)
    assert reopened.drain() == [record()]
    assert reopened.integrity("run")["spool_write_failed"] == 1
    store = InMemoryCostLedgerStore()
    service.store = store
    await service.flush()
    ack.assert_called_once_with([record()])
    assert len(store.calls) == 1
    assert reopened.drain() == []


def test_conflicting_capture_does_not_replace_volatile_completion(tmp_path, monkeypatch):
    recorder = UsageRecorder(spool_path=tmp_path / "spool.sqlite3")
    put = recorder._spool.put

    def unavailable(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(recorder._spool, "put", unavailable)
    rec = record()
    recorder.record(rec)
    with pytest.raises(UsageSpoolConflict):
        recorder.record(replace(rec, output_tokens=6))
    recorder.ack([replace(rec, output_tokens=7)])
    monkeypatch.setattr(recorder._spool, "put", put)
    assert recorder.drain() == []
    recorder.ack([rec])
    assert recorder._volatile[rec.id] == ("complete", rec)
    assert not recorder.integrity("run")["capture_complete"]
    assert recorder.integrity("run")["spool_write_failed"] == 1


@pytest.mark.parametrize("write_recovers", [False, True])
def test_drain_never_hides_conflict_between_volatile_and_durable_capture(
    tmp_path, monkeypatch, write_recovers
):
    path = tmp_path / "spool.sqlite3"
    recorder = UsageRecorder(spool_path=path)
    put = recorder._spool.put

    def unavailable(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(recorder._spool, "put", unavailable)
    original = record()
    recorder.record(original)
    other = UsageRecorder(spool_path=path)
    conflicting = replace(original, output_tokens=6)
    other.record(conflicting)
    if write_recovers:
        monkeypatch.setattr(recorder._spool, "put", put)
    assert recorder.drain() == []
    recorder.ack([original, conflicting])
    assert not recorder.integrity("run")["capture_complete"]
    assert other.drain() == [conflicting]
    assert recorder._volatile[original.id] == ("complete", original)
    assert recorder.integrity("run")["spool_write_failed"] == 1


def test_retried_failure_counters_are_not_duplicated_after_partial_persistence(tmp_path, monkeypatch):
    path = tmp_path / "spool.sqlite3"
    recorder = UsageRecorder(spool_path=path)
    put = recorder._spool.put
    failure = recorder._spool.failure

    def unavailable(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(recorder._spool, "put", unavailable)
    recorder.record(record())
    recorder.record(record("other-call", "other"))
    monkeypatch.setattr(recorder._spool, "put", put)
    failed = False

    def fail_second_counter(run_id, count):
        nonlocal failed
        if run_id == "other" and not failed:
            failed = True
            raise OSError("disk full")
        failure(run_id, count)

    monkeypatch.setattr(recorder._spool, "failure", fail_second_counter)
    assert len(recorder.drain()) == 2
    assert len(recorder.drain()) == 2
    reopened = UsageRecorder(spool_path=path)
    assert len(reopened.drain()) == 2
    assert reopened.integrity("run")["spool_write_failed"] == 1
    assert reopened.integrity("other")["spool_write_failed"] == 1


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
    saved = UsageRecorder(spool_path=path).snapshot()
    assert len(saved) == 1 and saved[0].output_tokens in {5, 6}
    conflicted = recorders[outcomes.index("conflict")]
    assert conflicted.snapshot() == []
    assert not conflicted.integrity("run")["capture_complete"]


def test_reused_pid_does_not_hide_abandoned_attempt():
    recorder = UsageRecorder()
    recorder.admit(record())
    with recorder._spool.db:
        recorder._spool.db.execute("UPDATE usage_outbox SET owner_token='old_process'")
    assert recorder.snapshot()[0].status == "interrupted"


async def test_changed_price_does_not_reprice_idempotent_ledger_capture():
    from travel_agent.config.models import ModelPricingItem
    store = InMemoryCostLedgerStore()
    old = ModelPricingItem(pattern="test", input_per_1m=2, output_per_1m=10)
    new = old.model_copy(update={"input_per_1m": 30, "output_per_1m": 100})
    await store.record_calls([record()], pricing=[old])
    price = store.calls[0].cost_usd
    await store.record_calls([record()], pricing=[new])
    assert len(store.calls) == 1 and store.calls[0].cost_usd == price


def test_pending_capture_is_not_a_complete_zero_bill():
    from travel_agent.storage.cost_ledger_store import summarize_calls
    recorder = UsageRecorder()
    recorder.record(record())
    summary = recorder.apply_integrity(summarize_calls("run", []))
    assert summary["total_tokens"] is None and summary["total_input_tokens"] is None
    assert not summary["cost_complete"] and not summary["token_usage_complete"]
    assert summary["record_failed"] == 1


@pytest.mark.parametrize("existing_schema", [False, True])
def test_concurrent_process_startup_opens_current_spool_without_volatile_fallback(
    tmp_path, existing_schema
):
    import json
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "spool.sqlite3"
    if existing_schema:
        initialized = UsageRecorder(spool_path=path)
        initialized._spool.db.close()
    script = """
import json,sys,time
from pathlib import Path
from travel_agent.llm.usage import UsageRecorder,LLMCallRecord
rec = LLMCallRecord(**json.loads(sys.argv[2]))
directory = Path(sys.argv[1]).parent
(directory / f'{rec.id}.ready').touch()
deadline = time.monotonic() + 10
while len(list(directory.glob('*.ready'))) < 8:
    if time.monotonic() >= deadline:
        raise TimeoutError('Concurrent workers did not become ready')
    time.sleep(0.01)
r=UsageRecorder(spool_path=sys.argv[1])
assert r._spool is not None
r.record(rec)
assert r.integrity('run')['spool_write_failed'] == 0
"""
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    def capture(n):
        result = subprocess.run(
            [sys.executable, "-c", script, str(path), json.dumps(record(f"call_{n}").to_dict())],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(capture, range(8)))
    reopened = UsageRecorder(spool_path=path)
    assert {rec.id for rec in reopened.snapshot()} == {f"call_{n}" for n in range(8)}
    assert reopened.integrity("run")["spool_write_failed"] == 0
