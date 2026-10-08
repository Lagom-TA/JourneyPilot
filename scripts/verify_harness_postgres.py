"""Verify worker journal migration in a disposable PostgreSQL 14 cluster.

PYTHONPATH=src <test-venv>/bin/python scripts/verify_harness_postgres.py
No project database or model calls. Fingerprint is checked, never rewritten.
"""

import asyncio
import json
import runpy
import subprocess
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager
from unittest.mock import patch
import psycopg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.engine import URL
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg.conninfo import make_conninfo
from travel_agent.entities.state import TravelAgentState
from travel_agent.db.fingerprint import fingerprint_sync
from travel_agent.infrastructure.worker_journal_store import (
    WorkerJournalStore,
    JournalConflict,
)
from travel_agent.workflows.run_control import with_run_control
from travel_agent.workflows.worker_recovery import current_execution_lease, with_worker_recovery

ROOT = Path.cwd()
BIN = Path("/usr/lib/postgresql/14/bin")


async def check_graph(store, saver, boundary):
    """Real Postgres pending writes + journal, without application admission."""
    from tests.test_research_context import make_packet

    calls, admitted, crash = [], [], [True]
    sibling_committed = asyncio.Event()
    save_writes = saver.aput_writes
    async def observe_writes(config, writes, task_id, task_path=""):
        await save_writes(config, writes, task_id, task_path)
        if any(channel == "agent_status" and value.get("lodging") == "completed"
               for channel, value in writes):
            sibling_committed.set()

    def worker_for(name):
        async def worker(state: TravelAgentState, config: RunnableConfig):
            calls.append(name)
            return {"messages": [AIMessage(content=name)],
                    "agent_status": {name: "completed"},
                    "research_packets": {name: make_packet(packet_id=name, run_id="run")}}
        return with_run_control(name, with_worker_recovery(name, worker))

    recovered = worker_for("visit")
    async def visit(state: TravelAgentState, config: RunnableConfig):
        result = await recovered(state, config)
        if crash[0] and boundary == "before_pending_write":
            await asyncio.wait_for(sibling_committed.wait(), timeout=5)
            crash[0] = False
            raise RuntimeError("fixture executor crash before pending write")
        return result

    async def gate(state: TravelAgentState):
        if crash[0] and boundary == "after_pending_write":
            crash[0] = False
            raise RuntimeError("fixture executor crash before fan-in")
        admitted.append(state)
        assert set(state.research_packets) == {"visit", "lodging"}
        assert all(packet.source_records for packet in state.research_packets.values())
        return {}

    def compile_graph():
        builder = StateGraph(TravelAgentState)
        builder.add_node("visit", visit)
        builder.add_node("lodging", worker_for("lodging"))
        builder.add_node("gate", gate)
        builder.add_edge(START, "visit")
        builder.add_edge(START, "lodging")
        builder.add_edge(["visit", "lodging"], "gate")
        builder.add_edge("gate", END)
        return builder.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": f"pg_resume_{boundary}", "worker_journal_store": store}}
    state = TravelAgentState(run_id="run", agent_assignments={
        name: {"objective": f"research {name}"} for name in ("visit", "lodging")})
    lease = current_execution_lease.set("live")
    try:
        with patch.object(saver, "aput_writes", observe_writes):
            try:
                await compile_graph().ainvoke(state, config)
            except RuntimeError as exc:
                assert "fixture executor crash" in str(exc)
            else:
                raise AssertionError("fault injection was not reached")
            result = await compile_graph().ainvoke(None, config)
        assert sorted(calls) == ["lodging", "visit"] and len(admitted) == 1
        assert len(result["messages"]) == len({message.id for message in result["messages"]}) == 2
    finally:
        current_execution_lease.reset(lease)


async def check(sock):
    engine = create_async_engine(
        URL.create(
            "postgresql+asyncpg",
            username="probe",
            database="postgres",
            query={"host": str(sock), "port": "65484"},
        )
    )
    maker = async_sessionmaker(engine)

    @asynccontextmanager
    async def session():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except BaseException:
                await s.rollback()
                raise

    try:
        with patch(
            "travel_agent.infrastructure.worker_journal_store.get_db_session", session
        ):
            store = WorkerJournalStore()
            version = await store.save(
                "run",
                "scope",
                0,
                {"messages": [AIMessage(content="typed", id="stable")]},
                lease_token="live",
            )
            v, payload = await store.load("run", "scope")
            assert v == version == 1 and isinstance(payload["messages"][0], AIMessage)
            for expected, lease in [(0, "live"), (1, "stale")]:
                try:
                    await store.save("run", "scope", expected, {}, lease_token=lease)
                except JournalConflict:
                    pass
                else:
                    raise AssertionError("stale version or lease accepted")
            assert (await store.load("run", "scope"))[0] == 1
            conninfo = make_conninfo(host=str(sock), port="65484", user="probe", dbname="postgres")
            async with AsyncPostgresSaver.from_conn_string(conninfo) as saver:
                await saver.setup()  # disposable cluster only
                for boundary in ("before_pending_write", "after_pending_write"):
                    await check_graph(store, saver, boundary)
    finally:
        await engine.dispose()


with tempfile.TemporaryDirectory(prefix="jp-journal-pg-") as d:
    base = Path(d)
    data = base / "data"
    sock = base / "socket"
    sock.mkdir()
    subprocess.run(
        [
            str(BIN / "initdb"),
            "-D",
            str(data),
            "--auth=trust",
            "--username=probe",
            "--no-locale",
            "--encoding=UTF8",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            str(BIN / "pg_ctl"),
            "-D",
            str(data),
            "-l",
            str(base / "log"),
            "-o",
            f"-F -k {sock} -p 65484 -c listen_addresses=''",
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    try:
        with psycopg.connect(
            host=str(sock), port=65484, user="probe", dbname="postgres", autocommit=True
        ) as conn:
            conn.execute("CREATE TABLE trip_runs(run_id TEXT PRIMARY KEY)")
            conn.execute("INSERT INTO trip_runs VALUES('run')")
            conn.execute(
                "CREATE TABLE trip_run_executions(run_id TEXT PRIMARY KEY,lease_token TEXT,lease_expires_at TIMESTAMPTZ)"
            )
            conn.execute(
                "INSERT INTO trip_run_executions VALUES('run','live',NOW()+interval '5 minutes')"
            )
            migration = runpy.run_path(
                str(ROOT / "migrations/versions/0009_worker_journal.py")
            )
            with patch("alembic.op.execute", conn.execute):
                migration["upgrade"]()
            archived = json.loads(
                (ROOT / "migrations/fingerprints/0009_worker_journal.json").read_text()
            )
            actual = fingerprint_sync(conn, embedding_dimensions=1024)["tables"][
                "run_worker_journals"
            ]
            assert actual == archived["tables"]["run_worker_journals"], (
                "PostgreSQL journal fingerprint drift"
            )
            asyncio.run(check(sock))
            with patch("alembic.op.execute", conn.execute):
                migration["downgrade"]()
            assert (
                conn.execute("SELECT to_regclass('run_worker_journals')").fetchone()[0]
                is None
            )
            print(
                "PASS: upgrade/downgrade, typed replay, version CAS, lease fence, rollback, PostgreSQL fingerprint; "
                "real LangGraph/Postgres fan-in recovery before/after pending writes"
            )
    finally:
        subprocess.run(
            [str(BIN / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"],
            check=True,
            capture_output=True,
        )
