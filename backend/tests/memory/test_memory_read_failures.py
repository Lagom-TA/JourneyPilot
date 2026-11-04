from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from travel_agent.memory import memory_store


@pytest.mark.parametrize("method", ["list_facts", "list_manual_facts", "search_facts"])
async def test_memory_read_failure_is_not_an_empty_result(monkeypatch, method):
    @asynccontextmanager
    async def failed_session():
        raise RuntimeError("database unavailable")
        yield

    store = memory_store.MemoryStore()
    monkeypatch.setattr(memory_store, "get_db_session", failed_session)
    monkeypatch.setattr(memory_store, "get_settings", lambda: SimpleNamespace(
        embedding=SimpleNamespace(enabled=True)
    ))

    async def embedding(_):
        return [1.0]

    monkeypatch.setattr(store, "_compute_embedding", embedding)
    arguments = {
        "list_facts": ("local",),
        "list_manual_facts": ("local",),
        "search_facts": ("local", "query"),
    }
    kwargs = {"limit": 10} if method == "list_manual_facts" else {}
    with pytest.raises(RuntimeError, match="database unavailable"):
        await getattr(store, method)(*arguments[method], **kwargs)
