"""HTTP resource behavior using the real app and fake I/O boundaries."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from travel_agent.api.app import create_app
from travel_agent.bootstrap import registry
from travel_agent.config import Settings, loader, publication, runtime_models
from travel_agent.knowledge.documents import (
    SourceDocumentUnavailable,
    require_source_document,
)
from travel_agent.memory.manual_facts import ManualFactSaveFailed, save_manual_fact
from travel_agent.memory.memory_store import (
    USER_MANUAL_IMPORTANCE,
    USER_MANUAL_SESSION_ID,
    MemoryStore,
)
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from travel_agent.storage import preset_store, product_configuration_store


@pytest.fixture
def configured(monkeypatch):
    settings = Settings(embedding={"enabled": False})
    monkeypatch.setattr(loader, "_effective", SimpleNamespace(settings=settings))
    monkeypatch.setattr(registry, "_components", None)
    return settings


@pytest.fixture
def client(configured):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://offline.test"
    )


def model_payload(**changes):
    return {
        "tier": "primary",
        "api_key": "",
        "model_name": "fixture-model",
        "base_url": "https://fixture.invalid/v1",
        "max_tokens": 1024,
        "temperature": 0.2,
        **changes,
    }


async def test_runtime_config_disabled_has_no_side_effects(
    client, configured, monkeypatch
):
    before = configured.model_dump()
    router = Mock()
    persist = Mock()
    monkeypatch.setattr(runtime_models, "get_model_router", router)
    monkeypatch.setattr(runtime_models, "persist_model_config", persist)
    async with client:
        response = await client.post("/api/configure", json=model_payload())
    assert response.status_code == 403
    assert "运行时模型配置接口未启用" in response.json()["detail"]
    assert configured.model_dump() == before
    router.assert_not_called()
    persist.assert_not_called()


@pytest.mark.parametrize("tier", ["primary", "fast", "unknown"])
async def test_runtime_config_reuses_key_falls_back_and_updates_router_before_persist(
    client, configured, monkeypatch, tier
):
    configured.server.allow_runtime_model_config = True
    configured.primary_model.api_key = "fixture-primary"
    configured.fast_model.api_key = "fixture-fast"
    events = []
    router = SimpleNamespace(update_model=lambda **kw: events.append(("router", kw)))
    monkeypatch.setattr(runtime_models, "get_model_router", lambda: router)
    monkeypatch.setattr(
        runtime_models,
        "persist_model_config",
        lambda t, data: events.append(("persist", t, data)),
    )
    async with client:
        response = await client.post("/api/configure", json=model_payload(tier=tier))
    assert response.status_code == 200
    assert [row[0] for row in events] == ["router", "persist"]
    assert events[0][1]["tier"].value == ("fast" if tier == "fast" else "primary")
    assert events[0][1]["api_key"] == (
        "fixture-fast" if tier == "fast" else "fixture-primary"
    )
    assert events[1][1] == tier


@pytest.mark.parametrize(
    "failure,status",
    [
        (FileNotFoundError("fixture missing config"), 500),
        (ValueError("fixture invalid"), 400),
    ],
)
async def test_runtime_config_error_mapping_preserves_update_before_failure(
    client, configured, monkeypatch, failure, status
):
    configured.server.allow_runtime_model_config = True
    router = Mock()
    monkeypatch.setattr(runtime_models, "get_model_router", lambda: router)
    monkeypatch.setattr(
        runtime_models, "persist_model_config", Mock(side_effect=failure)
    )
    async with client:
        response = await client.post("/api/configure", json=model_payload())
    assert response.status_code == status
    assert response.json()["detail"] == str(failure)
    router.update_model.assert_called_once()
    assert configured.primary_model.model_name == "fixture-model"


async def test_public_config_never_exposes_model_keys(client, configured):
    configured.primary_model.api_key = "fixture-primary"
    async with client:
        response = await client.get("/api/config")
    assert response.status_code == 200
    assert response.json()["primary_model"]["api_key_set"] is True
    assert response.json()["fast_model"]["api_key_set"] is False
    assert "fixture-primary" not in response.text
    assert '"api_key"' not in response.text


@pytest.mark.parametrize(
    "document,chunks,code",
    [(None, 0, "unknown_source"), (None, 4, "document_text_unavailable")],
)
async def test_original_text_domain_distinguishes_missing_from_legacy_chunks(
    document, chunks, code
):
    indexer = SimpleNamespace(
        get_document=AsyncMock(return_value=document),
        count_source_chunks=AsyncMock(return_value=chunks),
    )
    with pytest.raises(SourceDocumentUnavailable) as caught:
        await require_source_document(indexer, "u_local__default", "notes.md")
    assert caught.value.code == code
    indexer.count_source_chunks.assert_awaited_once_with("u_local__default", "notes.md")


@pytest.mark.parametrize(
    "chunks,status,code",
    [(0, 404, "unknown_source"), (3, 409, "document_text_unavailable")],
)
async def test_original_text_http_errors(client, monkeypatch, chunks, status, code):
    indexer = SimpleNamespace(
        get_document=AsyncMock(return_value=None),
        count_source_chunks=AsyncMock(return_value=chunks),
    )
    registry.set_components(SimpleNamespace(knowledge_indexer=indexer))
    async with client:
        response = await client.get(
            "/api/knowledge/collections/default/source", params={"source": "notes.md"}
        )
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


async def test_original_document_is_returned_even_when_body_is_empty(client):
    document = {
        "source": "notes.md",
        "content": "",
        "metadata": {},
        "chunk_count": 0,
        "updated_at": "2026-10-25T00:00:00Z",
    }
    count = AsyncMock(side_effect=AssertionError("must not reconstruct chunks"))
    indexer = SimpleNamespace(
        get_document=AsyncMock(return_value=document), count_source_chunks=count
    )
    registry.set_components(SimpleNamespace(knowledge_indexer=indexer))
    async with client:
        response = await client.get(
            "/api/knowledge/collections/default/source", params={"source": "notes.md"}
        )
    assert response.status_code == 200
    assert response.json()["content"] == ""
    count.assert_not_called()


@pytest.mark.parametrize("collection", [" ", "u_foreign__default"])
async def test_collection_http_rejects_physical_or_blank_addresses(client, collection):
    async with client:
        response = await client.get(
            f"/api/knowledge/collections/{collection}/source",
            params={"source": "notes.md"},
        )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "collection_address_invalid"


async def test_update_reuses_indexer_with_original_text_and_local_scope(
    client, configured
):
    configured.embedding.enabled = True
    indexer = SimpleNamespace(
        get_document=AsyncMock(return_value={"content": "old"}),
        index_text=AsyncMock(return_value=2),
    )
    registry.set_components(SimpleNamespace(knowledge_indexer=indexer))
    async with client:
        response = await client.put(
            "/api/knowledge/collections/default/source",
            params={"source": "notes.md"},
            json={"content": "新的原始正文，保留给之后编辑，不从分块拼接。"},
        )
    assert response.status_code == 200
    indexer.get_document.assert_awaited_once_with("u_local__default", "notes.md")
    indexer.index_text.assert_awaited_once_with(
        text="新的原始正文，保留给之后编辑，不从分块拼接。",
        source="notes.md",
        collection="u_local__default",
        metadata={"owner_user_id": LOCAL_USER_ID},
    )


async def test_manual_fact_dedupe_does_not_write_or_create_profile():
    row = {"fact_id": "same-id", "content": "no seafood"}
    store = SimpleNamespace(
        find_manual_fact=AsyncMock(return_value=row),
        save_fact=AsyncMock(),
        get_fact=AsyncMock(),
    )
    profile = Mock(side_effect=AssertionError("dedupe must not resolve profile"))
    result = await save_manual_fact(
        store=store,
        user_id="local",
        content="no seafood",
        category="diet",
        profile_for_write=profile,
    )
    assert result.status == "existing" and result.fact is row
    store.save_fact.assert_not_called()
    store.get_fact.assert_not_called()
    profile.assert_not_called()


async def test_manual_fact_write_profile_then_identity_readback():
    events = []
    row = {"fact_id": "new-id", "content": "no seafood", "source": "user_manual"}

    async def save(**kwargs):
        events.append(("save", kwargs))
        return "new-id"

    async def ensure(user_id):
        events.append(("profile", user_id))

    async def read(user_id, fact_id):
        events.append(("read", user_id, fact_id))
        return row

    store = SimpleNamespace(
        find_manual_fact=AsyncMock(return_value=None), save_fact=save, get_fact=read
    )
    result = await save_manual_fact(
        store=store,
        user_id="local",
        content="no seafood",
        category="diet",
        profile_for_write=lambda: SimpleNamespace(ensure_profile_for_write=ensure),
    )
    assert result.status == "created" and result.fact is row
    assert events == [
        (
            "save",
            {
                "user_id": "local",
                "session_id": USER_MANUAL_SESSION_ID,
                "content": "no seafood",
                "category": "diet",
                "importance": USER_MANUAL_IMPORTANCE,
            },
        ),
        ("profile", "local"),
        ("read", "local", "new-id"),
    ]


@pytest.mark.parametrize("save_id,created", [(None, None), ("new-id", None)])
async def test_manual_fact_write_and_readback_failures(save_id, created):
    store = SimpleNamespace(
        find_manual_fact=AsyncMock(return_value=None),
        save_fact=AsyncMock(return_value=save_id),
        get_fact=AsyncMock(return_value=created),
    )
    profile = SimpleNamespace(ensure_profile_for_write=AsyncMock())
    with pytest.raises(ManualFactSaveFailed, match="memory fact save failed"):
        await save_manual_fact(
            store=store,
            user_id="local",
            content="no seafood",
            category="diet",
            profile_for_write=lambda: profile,
        )
    assert profile.ensure_profile_for_write.await_count == int(save_id is not None)
    assert store.get_fact.await_count == int(save_id is not None)


async def test_manual_fact_http_defaults_and_identity(client, monkeypatch):
    monkeypatch.setattr(MemoryStore, "find_manual_fact", AsyncMock(return_value=None))
    saved = AsyncMock(return_value="id-from-save")
    read = AsyncMock(
        return_value={
            "fact_id": "id-from-save",
            "content": "不吃海鲜",
            "source": "user_manual",
            "category": "preference",
            "importance": 10,
        }
    )
    monkeypatch.setattr(MemoryStore, "save_fact", saved)
    monkeypatch.setattr(MemoryStore, "get_fact", read)
    ensure = AsyncMock()
    registry.set_components(
        SimpleNamespace(
            user_profile_memory=SimpleNamespace(ensure_profile_for_write=ensure)
        )
    )
    async with client:
        response = await client.post(
            "/api/user/memory/facts", json={"content": " 不吃海鲜 ", "category": " "}
        )
    assert response.status_code == 200
    assert response.json()["status"] == "created"
    assert response.json()["fact"]["fact_id"] == "id-from-save"
    assert response.json()["fact"]["source"] == "user_manual"
    saved.assert_awaited_once_with(
        user_id=LOCAL_USER_ID,
        session_id=USER_MANUAL_SESSION_ID,
        content="不吃海鲜",
        category="preference",
        importance=USER_MANUAL_IMPORTANCE,
    )
    read.assert_awaited_once_with(LOCAL_USER_ID, "id-from-save")
    ensure.assert_awaited_once_with(LOCAL_USER_ID)


async def test_preferences_unknown_fields_do_not_write(client):
    update = AsyncMock()
    registry.set_components(
        SimpleNamespace(user_profile_memory=SimpleNamespace(update_preferences=update))
    )
    async with client:
        response = await client.patch(
            "/api/user/preferences", json={"preferences": {"zzz": [], "aaa": []}}
        )
    assert response.status_code == 422
    assert response.json()["detail"] == "不认识这几组偏好：aaa、zzz"
    update.assert_not_called()


async def test_preferences_validator_rejection_stays_a_client_error(client):
    from pydantic import ValidationError

    from travel_agent.memory.preference_contracts import TravelPreference

    try:
        TravelPreference(pace="not-a-choice")
    except ValidationError as exc:
        failure = exc
    update = AsyncMock(side_effect=failure)
    registry.set_components(
        SimpleNamespace(user_profile_memory=SimpleNamespace(update_preferences=update))
    )
    async with client:
        response = await client.patch(
            "/api/user/preferences", json={"preferences": {"pace": "not-a-choice"}}
        )
    assert response.status_code == 422
    assert "errors.pydantic.dev" not in response.text
    assert "Value error" not in response.text


class RecordingSession:
    def __init__(self, events):
        self.events = events

    async def execute(self, sql, params):
        self.events.append((str(sql), params))


def recording_sessions(events):
    @asynccontextmanager
    async def session():
        events.append("begin")
        yield RecordingSession(events)
        events.append("commit")

    return session


async def test_missing_seed_ensure_is_insert_only(monkeypatch):
    events = []
    session = recording_sessions(events)
    monkeypatch.setattr(product_configuration_store, "get_db_session", session)
    monkeypatch.setattr(preset_store, "get_db_session", session)
    await product_configuration_store.ProductConfigurationStore().ensure_seed()
    await preset_store.PresetStore().ensure_presets()
    rows = [row for row in events if isinstance(row, tuple)]
    assert len(rows) == 10
    assert all("DO NOTHING" in row[0] and "DO UPDATE" not in row[0] for row in rows)
    assert events.count("begin") == events.count("commit") == 2
    assert json.loads(rows[0][1]["config"])["primary_styles"]
    assert all(row[1]["uid"] == "__system__" for row in rows[1:])


async def test_publication_checks_contract_before_real_store_sql(monkeypatch):
    events = []

    async def require_contract():
        events.append("contract")

    monkeypatch.setattr(publication, "require_database_contract", require_contract)
    session = recording_sessions(events)
    monkeypatch.setattr(product_configuration_store, "get_db_session", session)
    monkeypatch.setattr(preset_store, "get_db_session", session)
    result = await publication.publish_seed()
    assert events[0] == "contract"
    rows = [row for row in events if isinstance(row, tuple)]
    assert len(rows) == 10 and all("DO UPDATE" in row[0] for row in rows)
    assert "product_configurations" in rows[0][0]
    assert all("travel_presets" in row[0] for row in rows[1:])
    assert all("CREATE" not in row[0] and "ALTER" not in row[0] for row in rows)
    assert result["system_presets"]["count"] == 9
    assert events.count("begin") == events.count("commit") == 2


async def test_failed_contract_prevents_any_publication_sql(monkeypatch):
    check = AsyncMock(side_effect=RuntimeError("contract incompatible"))
    monkeypatch.setattr(publication, "require_database_contract", check)
    sessions = Mock(side_effect=AssertionError("must not write before contract"))
    monkeypatch.setattr(product_configuration_store, "get_db_session", sessions)
    monkeypatch.setattr(preset_store, "get_db_session", sessions)
    with pytest.raises(RuntimeError, match="contract incompatible"):
        await publication.publish_seed()
    sessions.assert_not_called()
