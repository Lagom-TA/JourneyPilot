"""生命周期策略，持久化资源用假边界替代。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from travel_agent.bootstrap import registry, shutdown, startup
from travel_agent.config.models import Settings
from travel_agent.config import loader
from travel_agent.knowledge import factory_seed
from travel_agent.storage import database, redis_client


@pytest.fixture
def lifecycle(monkeypatch):
    events = []
    settings = Settings(embedding={"enabled": False})
    monkeypatch.setattr(loader, "_effective", SimpleNamespace(settings=settings))
    monkeypatch.setattr(registry, "_components", None)

    def action(name, *, fail=False, result=None):
        async def run(*args, **kwargs):
            events.append(name)
            if fail:
                raise RuntimeError(name)
            return result

        return run

    components = SimpleNamespace(
        schema_report=SimpleNamespace(compatible=True, problems=[], next_action=""),
        preset_store=SimpleNamespace(ensure_presets=action("preset.ensure")),
        product_configuration_store=SimpleNamespace(
            ensure_seed=action("product.ensure")
        ),
        checkpointer_available=True,
        checkpointer_init_error=None,
        tool_registry=SimpleNamespace(count=0),
        usage_flush_service=SimpleNamespace(stop=action("usage.stop")),
        background_job_worker=SimpleNamespace(
            cleanup=action("jobs.cleanup"),
            start=lambda: events.append("jobs.start"),
            stop=action("jobs.stop"),
        ),
        run_recovery_service=SimpleNamespace(
            sweep=action(
                "recovery.sweep",
                result=SimpleNamespace(
                    log_summary=lambda: events.append("recovery.summary")
                ),
            ),
            start=lambda: events.append("recovery.start"),
            stop=action("recovery.stop"),
        ),
        _checkpointer_pool=SimpleNamespace(close=action("pool.close")),
    )

    async def construct(received):
        assert received is settings
        events.append("construct")
        return components

    monkeypatch.setattr(startup, "build_components", construct)
    monkeypatch.setattr(startup, "probe_pdf_font", action("pdf.probe"))
    monkeypatch.setattr(
        shutdown, "release_all_leases", action("leases.release", result=0)
    )
    monkeypatch.setattr(database, "close_db", action("db.close"))
    monkeypatch.setattr(redis_client, "close_redis", action("redis.close"))
    corpus = AsyncMock(side_effect=AssertionError("disabled corpus must not bootstrap"))
    monkeypatch.setattr(factory_seed, "ensure_factory_corpus", corpus)
    return SimpleNamespace(
        events=events,
        settings=settings,
        components=components,
        action=action,
        corpus=corpus,
    )


@pytest.mark.parametrize("missing", [False, True])
async def test_incompatible_schema_blocks_writes_but_not_pdf(lifecycle, missing):
    f = lifecycle
    f.settings.embedding.enabled = True
    f.settings.embedding.provider = "openai"
    f.components.schema_report = (
        None
        if missing
        else SimpleNamespace(
            compatible=False,
            problems=["unmigrated"],
            next_action="journeypilot migrate",
        )
    )
    async with startup.application_lifespan():
        assert registry.get_components() is f.components
        assert f.events == ["construct", "pdf.probe"]
    assert f.events[2:] == [
        "usage.stop",
        "jobs.stop",
        "recovery.stop",
        "leases.release",
        "pool.close",
        "db.close",
        "redis.close",
    ]
    f.corpus.assert_not_called()


async def test_sweep_and_cleanup_failures_do_not_disable_periodic_work(lifecycle):
    f = lifecycle
    f.components.run_recovery_service.sweep = f.action("recovery.sweep", fail=True)
    f.components.background_job_worker.cleanup = f.action("jobs.cleanup", fail=True)
    async with startup.application_lifespan():
        assert f.events == [
            "construct",
            "preset.ensure",
            "product.ensure",
            "recovery.sweep",
            "recovery.start",
            "jobs.cleanup",
            "jobs.start",
            "pdf.probe",
        ]
    f.corpus.assert_not_called()


async def test_startup_ensures_product_then_corpus_before_recovery(lifecycle):
    f = lifecycle
    f.settings.embedding.enabled = True
    f.settings.embedding.provider = "openai"
    f.corpus.side_effect = f.action(
        "corpus.bootstrap", result=SimpleNamespace(loaded={}, problems=[], present={})
    )
    async with startup.application_lifespan():
        f.corpus.assert_awaited_once()
        assert f.events == [
            "construct",
            "preset.ensure",
            "product.ensure",
            "corpus.bootstrap",
            "recovery.sweep",
            "recovery.summary",
            "recovery.start",
            "jobs.cleanup",
            "jobs.start",
            "pdf.probe",
        ]


async def test_preset_failure_preserves_original_exception_boundary(lifecycle):
    f = lifecycle
    f.components.preset_store.ensure_presets = f.action("preset.ensure", fail=True)
    async with startup.application_lifespan():
        assert "product.ensure" not in f.events
        assert "recovery.start" in f.events and "jobs.start" in f.events
        assert "pdf.probe" in f.events


async def test_capability_failure_happens_before_construction_or_shutdown(
    lifecycle, monkeypatch
):
    monkeypatch.setattr(
        startup,
        "capability_gaps",
        lambda settings: [
            SimpleNamespace(message=lambda: "missing optional dependency")
        ],
    )
    with pytest.raises(RuntimeError, match="missing optional dependency"):
        async with startup.application_lifespan():
            pytest.fail("unavailable capability must not yield")
    assert lifecycle.events == []
    assert registry.registered_components() is None


async def test_shutdown_reads_latest_registry_value(lifecycle):
    f = lifecycle
    obsolete = SimpleNamespace(usage_flush_service=SimpleNamespace(stop=AsyncMock()))
    registry.set_components(obsolete)
    registry.set_components(f.components)
    await shutdown.shutdown_components()
    obsolete.usage_flush_service.stop.assert_not_called()
    assert f.events == [
        "usage.stop",
        "jobs.stop",
        "recovery.stop",
        "leases.release",
        "pool.close",
        "db.close",
        "redis.close",
    ]


async def test_uninitialized_shutdown_still_releases_and_closes(lifecycle):
    with pytest.raises(RuntimeError, match="尚未初始化"):
        registry.get_components()
    await shutdown.shutdown_components()
    assert lifecycle.events == ["leases.release", "db.close", "redis.close"]


@pytest.mark.parametrize(
    "failing", ["leases.release", "pool.close", "db.close", "redis.close"]
)
async def test_close_failures_do_not_skip_later_resources(
    lifecycle, monkeypatch, failing
):
    f = lifecycle
    registry.set_components(f.components)
    if failing == "leases.release":
        monkeypatch.setattr(
            shutdown, "release_all_leases", f.action(failing, fail=True)
        )
    elif failing == "pool.close":
        f.components._checkpointer_pool.close = f.action(failing, fail=True)
    elif failing == "db.close":
        monkeypatch.setattr(database, "close_db", f.action(failing, fail=True))
    else:
        monkeypatch.setattr(redis_client, "close_redis", f.action(failing, fail=True))
    await shutdown.shutdown_components()
    assert f.events == [
        "usage.stop",
        "jobs.stop",
        "recovery.stop",
        "leases.release",
        "pool.close",
        "db.close",
        "redis.close",
    ]


@pytest.mark.parametrize(
    "producer", ["usage_flush_service", "background_job_worker", "run_recovery_service"]
)
async def test_producer_stop_exception_is_not_swallowed(lifecycle, producer):
    f = lifecycle
    registry.set_components(f.components)
    getattr(f.components, producer).stop = f.action("producer.failed", fail=True)
    with pytest.raises(RuntimeError, match="producer.failed"):
        await shutdown.shutdown_components()
    assert "leases.release" not in f.events
    assert "pool.close" not in f.events


async def test_pdf_startup_records_failed_probe_without_real_render(monkeypatch):
    from travel_agent.integrations import pdf_readiness
    from travel_agent.runtime import blocking_work

    monkeypatch.setattr(pdf_readiness, "_last_probe", None)
    render = Mock(side_effect=pdf_readiness.PdfFontUnavailable("no font"))
    monkeypatch.setattr(pdf_readiness, "probe_pdf_renderer", render)

    async def fake_blocking(channel, fn):
        assert channel == "pdf_export"
        return fn()

    monkeypatch.setattr(blocking_work, "run_blocking", fake_blocking)
    assert await pdf_readiness.probe_pdf_font() == "no font"
    assert pdf_readiness.last_pdf_probe().available is False
    assert pdf_readiness.last_pdf_probe().problem == "no font"
    render.assert_called_once()
