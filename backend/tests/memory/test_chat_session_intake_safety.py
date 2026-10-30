"""A late old turn must not erase a newer intake draft."""

from contextlib import asynccontextmanager

import pytest

from travel_agent.conversation.intake import IntakeRevisionStale
from travel_agent.memory import chat_session


class Result:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def first(self):
        return self.value

    def scalar_one(self):
        return self.value


class OfflineSession:
    def __init__(self):
        self.pending = {"raw_input": "新版必须无障碍"}
        self.events = []
        self.statements = []

    async def execute(self, statement, params):
        sql = str(statement)
        self.statements.append(sql)
        if "SELECT * FROM chat_sessions" in sql:
            return Result({"user_id": "local"})
        if "SELECT user_id, pending_clarify" in sql:
            return Result({"user_id": "local", "pending_clarify": self.pending})
        if "MAX(event_order)" in sql:
            return Result(len(self.events))
        if "INSERT INTO chat_session_events" in sql:
            self.events.append(params)
            return Result(None)
        if "UPDATE chat_sessions" in sql:
            if params.get("clear_intake") or "pending_clarify = NULL" in sql:
                self.pending = None
            return Result(None)
        raise AssertionError(f"unexpected offline query: {sql}")


async def test_old_interrupted_turn_does_not_delete_new_intake(monkeypatch):
    session = OfflineSession()

    @asynccontextmanager
    async def offline_db():
        yield session

    memory = chat_session.ChatSessionMemory()

    async def ensure_session(**_kwargs):
        return None

    async def summary(*_args, **_kwargs):
        return {"session_id": "offline-session"}

    monkeypatch.setattr(chat_session, "get_db_session", offline_db)
    monkeypatch.setattr(memory, "ensure_session", ensure_session)
    monkeypatch.setattr(memory, "get_session_summary", summary)
    await memory.save_turn(
        session_id="offline-session", user_id="local", mode="deep",
        user_message="旧旅行", user_message_id="old-user", assistant_message_id="old-assistant",
        assistant_content="中断", assistant_display_content="中断", assistant_type="interrupted",
        run_id="old-run", controlled_trip_identity={"destinations": [{"name": "杭州"}]},
    )
    assert len(session.events) == 2
    assert session.pending == {"raw_input": "新版必须无障碍"}


async def test_intake_read_and_clear_can_share_the_run_transaction(monkeypatch):
    session = OfflineSession()
    session.pending = {
        "intake_revision": 7, "raw_input": "杭州旅行",
        "route_decision": {"route": "trip_planning", "confidence": 1, "requires_trip_draft": True},
    }

    @asynccontextmanager
    async def forbidden_db():
        raise AssertionError("a borrowed transaction must not open a separate connection")
        yield

    monkeypatch.setattr(chat_session, "get_db_session", forbidden_db)
    memory = chat_session.ChatSessionMemory()
    saved = await memory.get_guided_intake(
        session_id="offline-session", user_id="local", db_session=session, for_update=True,
    )
    assert saved.intake_revision == 7
    await memory.clear_guided_intake(session_id="offline-session", user_id="local", db_session=session)
    assert session.pending is None
    assert any("FOR UPDATE" in statement for statement in session.statements)


async def test_storage_compare_and_swap_rejects_cross_process_stale_save(monkeypatch):
    session = OfflineSession()
    session.pending = {
        "intake_revision": 3, "raw_input": "新版必须无障碍",
        "route_decision": {"route": "trip_planning", "confidence": 1, "requires_trip_draft": True},
    }

    @asynccontextmanager
    async def offline_db():
        yield session

    memory = chat_session.ChatSessionMemory()

    async def ensure_session(**_kwargs):
        return None

    monkeypatch.setattr(chat_session, "get_db_session", offline_db)
    monkeypatch.setattr(memory, "ensure_session", ensure_session)
    with pytest.raises(IntakeRevisionStale) as caught:
        await memory.save_guided_intake(
            session_id="offline-session", user_id="local", title_seed="旧版",
            guided_intake=None, expected_revision=2,
        )
    assert caught.value.current_revision == 3
    assert session.pending["intake_revision"] == 3 and session.pending["raw_input"] == "新版必须无障碍"
    with pytest.raises(IntakeRevisionStale):
        await memory.save_guided_intake(
            session_id="offline-session", user_id="local", title_seed="旧版",
            guided_intake=None, expect_absent=True,
        )
    assert session.pending["intake_revision"] == 3 and session.pending["raw_input"] == "新版必须无障碍"
    session.pending["intake_id"] = "it_" + "b" * 32
    with pytest.raises(IntakeRevisionStale):
        await memory.save_guided_intake(
            session_id="offline-session", user_id="local", title_seed="旧版",
            guided_intake=None, expected_revision=3, expected_intake_id="it_" + "a" * 32,
        )
    assert session.pending["intake_id"] == "it_" + "b" * 32
