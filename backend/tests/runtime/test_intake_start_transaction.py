"""Run start and intake consumption can use the same database transaction."""

from contextlib import asynccontextmanager

from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.storage import trip_run_store


class Result:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def first(self):
        return self.value


class OfflineTransaction:
    def __init__(self):
        self.run = {"run_id": "offline-run", "session_id": "offline-session", "user_id": "local", "mode": "deep", "status": "created"}
        self.state = {"latest_state_summary": {}, "pending_user_choice": None}

    async def execute(self, statement, params):
        sql = str(statement)
        if "SELECT * FROM trip_runs" in sql:
            return Result(dict(self.run))
        if "SELECT latest_state_summary" in sql:
            return Result(dict(self.state))
        if "UPDATE trip_runs" in sql:
            self.run["status"] = params["status"]
            return Result(None)
        if "UPDATE trip_run_states" in sql:
            self.state["status"] = params["status"]
            return Result(None)
        raise AssertionError(f"unexpected offline query: {sql}")


async def test_run_transition_reuses_caller_transaction(monkeypatch):
    transaction = OfflineTransaction()
    store = trip_run_store.TripRunStore()
    events = []

    @asynccontextmanager
    async def forbidden_db():
        raise AssertionError("a borrowed transaction must not open a separate connection")
        yield

    async def append_event(session, run_id, event_type, payload):
        assert session is transaction
        events.append((run_id, event_type, payload))

    monkeypatch.setattr(trip_run_store, "get_db_session", forbidden_db)
    monkeypatch.setattr(store, "_append_event_in_session", append_event)
    run = await store.transition_status(
        "offline-run", TripRunStatus.RUNNING, event_type="run.started", db_session=transaction,
    )
    assert run.status is TripRunStatus.RUNNING
    assert events[0][1] == "run.started"
