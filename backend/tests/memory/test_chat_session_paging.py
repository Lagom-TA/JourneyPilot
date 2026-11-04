"""单轮超过分页窗口时，游标仍指向整轮的第一条事件。"""

from contextlib import asynccontextmanager

import pytest

from travel_agent.memory import chat_session


@pytest.mark.parametrize("first_order,has_earlier", [(1, False), (3, True)])
async def test_oversized_turn_uses_its_real_start_for_the_next_cursor(
    monkeypatch, first_order, has_earlier,
):
    count = chat_session.TURN_PAGE_MAX_EVENTS + 2
    rows = [{
        "turn_id": "long-turn", "event_order": first_order + index,
        "event_type": "message.user" if index == 0 else "message.assistant" if index == count - 1 else "thinking.step",
        "payload": {"message_id": "user" if index == 0 else "assistant", "content": "内容"},
    } for index in range(count)]

    class Result:
        def __init__(self, value):
            self.value = value

        def mappings(self):
            return self

        def all(self):
            return self.value

        def scalar_one(self):
            return self.value

    class Session:
        async def execute(self, statement, params):
            sql = str(statement)
            if "WITH windowed" in sql:
                return Result([{
                    "turn_id": "long-turn", "first_order": first_order + 1,
                    "event_count": count - 1, "window_turns": 1,
                }])
            if "SELECT EXISTS" in sql:
                assert params["first_order"] == first_order
                return Result(has_earlier)
            return Result(rows)

    @asynccontextmanager
    async def session():
        yield Session()

    monkeypatch.setattr(chat_session, "get_db_session", session)
    page = await chat_session.ChatSessionMemory().list_turns(
        "local", "session", summary={"session_id": "session"},
    )
    assert len(page["turns"]) == 1
    assert page["turns"][0]["cursor"] == f"o{first_order}"
    assert page["has_more"] is has_earlier
    assert page["next_before"] == (f"o{first_order}" if has_earlier else None)
