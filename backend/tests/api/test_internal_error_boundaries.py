"""未知异常在 HTTP 边界只返回固定文案，不把异常原文交给客户端。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from travel_agent.api.routes import knowledge, sessions, user
from travel_agent.api.schemas.knowledge import KnowledgeUploadRequest
from travel_agent.memory.compaction import CompactionBusy


def _settings():
    return SimpleNamespace(embedding=SimpleNamespace(enabled=True))


def _assert_hidden(exc: HTTPException) -> None:
    assert exc.status_code == 500
    assert isinstance(exc.detail, dict)
    assert exc.detail["code"] == "internal_error"
    assert "secret" not in str(exc.detail).lower()


async def test_knowledge_index_hides_internal_exception(monkeypatch):
    class Indexer:
        async def index_text(self, **kwargs):
            raise RuntimeError("dsn=postgres://secret")

    components = SimpleNamespace(knowledge_indexer=Indexer())
    monkeypatch.setattr("travel_agent.api.routes.knowledge.get_components", lambda: components)
    monkeypatch.setattr("travel_agent.api.routes.knowledge.get_settings", _settings)
    request = KnowledgeUploadRequest(
        content="这是足够长的有效正文，用来通过正文下界校验。" * 2,
        source="manual",
        collection="travel_knowledge",
    )
    with pytest.raises(HTTPException) as caught:
        await knowledge.index_text(request)
    _assert_hidden(caught.value)


async def test_user_sessions_hide_internal_exception(monkeypatch):
    class Memory:
        async def list_sessions(self, *args, **kwargs):
            raise RuntimeError("db password=secret")

    monkeypatch.setattr(
        "travel_agent.api.routes.user.get_components",
        lambda: SimpleNamespace(chat_session_memory=Memory()),
    )
    with pytest.raises(HTTPException) as caught:
        await user.list_user_sessions()
    _assert_hidden(caught.value)


async def test_compaction_busy_maps_to_409(monkeypatch):
    class Service:
        async def compact(self, **kwargs):
            raise CompactionBusy("already compacting")

    monkeypatch.setattr(sessions, "get_compaction_service", lambda: Service())
    with pytest.raises(HTTPException) as caught:
        await sessions.compact_session("session-1")
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "compaction_busy"
