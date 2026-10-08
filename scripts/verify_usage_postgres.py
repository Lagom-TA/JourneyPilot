"""Verify only the changed ledger table in a disposable PostgreSQL cluster.

No connection to JourneyPilot's configured database; no model API calls.
"""
from __future__ import annotations

import ast
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
from unittest.mock import patch

import psycopg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.engine import URL

from travel_agent.config import ModelPricingItem
from travel_agent.db.fingerprint import fingerprint_sync
from travel_agent.infrastructure.cost_ledger_store import CostLedgerConflict, CostLedgerStore
from travel_agent.models.usage import LLMCallRecord, UsageRecorder

ROOT = Path(__file__).resolve().parents[1]
BIN = Path('/usr/lib/postgresql/14/bin')
RESULT = {}


def baseline_ledger_sql():
    tree = ast.parse((ROOT / 'migrations/versions/0001_baseline_current_schema.py').read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'execute':
            if node.args and isinstance(node.args[0], ast.Constant):
                sql = node.args[0].value
                if isinstance(sql, str) and 'run_llm_calls' in sql and ('CREATE TABLE' in sql or 'CREATE INDEX' in sql):
                    yield sql


async def check_store(sock_dir):
    url = URL.create('postgresql+asyncpg', username='harness_review', database='postgres',
                     query={'host': str(sock_dir), 'port': '65483'})
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session():
        async with sessions() as current:
            try:
                yield current
                await current.commit()
            except BaseException:
                await current.rollback()
                raise

    recorder = UsageRecorder()
    record = LLMCallRecord(id='call_exact', run_id='run_probe', node='worker', agent='worker',
        tier='fast', provider='', model_request='test', method='ainvoke', stream=False,
        start_ts='2026-10-05T00:00:00+00:00', input_tokens=100000, output_tokens=20000,
        total_tokens=120000, cached_input_tokens=40000, cache_write_input_tokens=30000,
        reasoning_output_tokens=15000, logical_call_id='logical', attempt_number=2,
        request_input_tokens_estimate=105000, tool_schema_tokens_estimate=5000, finish_reason='stop')
    price = ModelPricingItem(pattern='test', input_per_1m=2, cached_input_per_1m=0.1,
                             cache_write_per_1m=2.5, output_per_1m=10)
    try:
        with patch('travel_agent.infrastructure.cost_ledger_store.get_db_session', session), patch('travel_agent.models.usage.get_usage_recorder', lambda: recorder):
            store = CostLedgerStore()
            await store.record_calls([record], pricing=[price])
            await store.record_calls([record], pricing=[price])
            calls = await store.list_calls('run_probe')
            assert len(calls) == 2  # one preserved legacy row and one exact row
            exact = next(call for call in calls if call.id == 'call_exact')
            assert exact.cache_write_input_tokens == 30000
            assert exact.attempt_number == 2 and exact.logical_call_id == 'logical'
            assert exact.tool_schema_tokens_estimate == 5000
            assert exact.cost_usd == 0.339
            assert exact.finish_reason == 'stop' and exact.usage_complete
            try:
                await store.record_calls([replace(record, cache_write_input_tokens=30001)], pricing=[price])
            except CostLedgerConflict:
                pass
            else:
                raise AssertionError('Conflicting replay was accepted')
            summary = await store.run_summary('run_probe')
            assert summary['total_cache_write_input_tokens'] == 30000
            assert summary['cost_complete'] is False  # legacy row remains incomplete
            RESULT['sql_store_roundtrip'] = {
                'row_count': len(calls), 'cache_write_tokens': exact.cache_write_input_tokens,
                'attempt_number': exact.attempt_number, 'mixed_bucket_cost_usd': exact.cost_usd,
                'duplicate_replay': 'idempotent', 'conflicting_replay': 'rejected',
            }
    finally:
        await engine.dispose()


with tempfile.TemporaryDirectory(prefix='journeypilot-usage-pg-') as root:
    base = Path(root)
    data, sock = base / 'data', base / 'socket'
    sock.mkdir()
    subprocess.run([str(BIN / 'initdb'), '-D', str(data), '--auth=trust', '--username=harness_review', '--no-locale', '--encoding=UTF8'],
                   check=True, capture_output=True)
    started = False
    try:
        subprocess.run([str(BIN / 'pg_ctl'), '-D', str(data), '-l', str(base / 'postgres.log'),
                        '-o', f"-F -k {sock} -p 65483 -c listen_addresses=''", '-w', 'start'],
                       check=True, capture_output=True)
        started = True
        with psycopg.connect(host=str(sock), port=65483, user='harness_review', dbname='postgres', autocommit=True) as conn:
            conn.execute('CREATE TABLE trip_runs (run_id TEXT PRIMARY KEY)')
            conn.execute("INSERT INTO trip_runs VALUES ('run_probe')")
            for sql in baseline_ledger_sql():
                conn.execute(sql)
            conn.execute("""INSERT INTO run_llm_calls
                (id,run_id,model_request,input_tokens,output_tokens,cached_input_tokens,cost_usd)
                VALUES ('legacy','run_probe','test',100,20,40,0.2)""")
            migration = runpy.run_path(str(ROOT / 'migrations/versions/0008_llm_usage_details.py'))
            with patch('alembic.op.execute', conn.execute):
                migration['upgrade']()
            legacy = conn.execute('SELECT total_tokens,cache_write_input_tokens,usage_complete,usage_source,cost_usd FROM run_llm_calls WHERE id=\'legacy\'').fetchone()
            assert legacy == (120, None, False, 'legacy', 0.2)
            actual = fingerprint_sync(conn, embedding_dimensions=1024)['tables']['run_llm_calls']
            archived = json.loads((ROOT / 'migrations/fingerprints/0008_llm_usage_details.json').read_text())['tables']['run_llm_calls']
            assert actual == archived, 'Ledger-table fingerprint differs from PostgreSQL'
            RESULT['ledger_table_fingerprint'] = 'matches PostgreSQL 14'
            RESULT['legacy_cost_snapshot'] = 'preserved; missing cache-write usage remains null'
            asyncio.run(check_store(sock))
            with patch('alembic.op.execute', conn.execute):
                migration['downgrade']()
            columns = {row[0] for row in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name='run_llm_calls'")}
            assert 'cache_write_input_tokens' not in columns and 'input_tokens' in columns
            assert conn.execute('SELECT count(*) FROM run_llm_calls').fetchone()[0] == 2
            RESULT['migration_upgrade_downgrade'] = 'passed, original rows preserved'
    finally:
        if started:
            subprocess.run([str(BIN / 'pg_ctl'), '-D', str(data), '-m', 'fast', '-w', 'stop'],
                           check=True, capture_output=True)

result_path = ROOT / 'temp/harness-review-2026-10-05/postgres-verification.json'
result_path.parent.mkdir(parents=True, exist_ok=True)
result_path.write_text(
    json.dumps(RESULT, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(RESULT, ensure_ascii=False, indent=2))
