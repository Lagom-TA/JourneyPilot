import logging
from types import SimpleNamespace

import pytest

from travel_agent.config.models import Settings
from travel_agent.knowledge import factory_seed
from travel_agent.knowledge.bootstrap import bootstrap_factory_corpus
from travel_agent.knowledge.factory_seed import LoadReport


@pytest.fixture
def embedding_enabled(monkeypatch):
    from travel_agent.config import loader

    settings = Settings(embedding={"enabled": True})
    monkeypatch.setattr(loader, "_effective", SimpleNamespace(settings=settings))


async def test_missing_optional_seed_is_reported_as_absent_not_as_a_failure(tmp_path, monkeypatch):
    async def empty_report(seed_dir, *, force):
        return LoadReport()

    monkeypatch.setattr(factory_seed, "load_seed", empty_report)

    report = await factory_seed.ensure_factory_corpus(tmp_path / "no-seed")

    assert report.seed_absent is True


async def test_bootstrap_treats_a_missing_optional_seed_as_expected(embedding_enabled, monkeypatch, caplog):
    async def absent(seed_dir=None):
        return LoadReport(problems=["未提供本地出厂语料种子"], seed_absent=True)

    monkeypatch.setattr(factory_seed, "ensure_factory_corpus", absent)

    with caplog.at_level(logging.INFO, logger="travel_agent.knowledge.bootstrap"):
        problems = await bootstrap_factory_corpus()

    assert problems == []
    assert all(record.levelno < logging.WARNING for record in caplog.records)


async def test_bootstrap_still_reports_a_declared_collection_that_stayed_empty(embedding_enabled, monkeypatch):
    async def degraded(seed_dir=None):
        return LoadReport(problems=["出厂集合 travel_tips 仍然是空的"])

    monkeypatch.setattr(factory_seed, "ensure_factory_corpus", degraded)

    assert await bootstrap_factory_corpus() == ["出厂集合 travel_tips 仍然是空的"]
