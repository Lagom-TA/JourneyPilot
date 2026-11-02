"""当前交付合同不含版本字段：读回与公开投影只按当前结构。"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from travel_agent.api.schemas.delivery import (
    PublicBundleManifestResponse,
    PublicBundleWorkspaceResponse,
)
from travel_agent.memory.research_context import ResearchContextView
from travel_agent.planning.delivery.bundle import (
    DeliveryBundle,
    DeliveryRevisionManifest,
)
from travel_agent.planning.delivery.public.bundle import (
    public_event_manifest,
    public_manifest,
)
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.evidence import FactStoreSnapshot
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.planning.workspace import TripWorkspace

CONTRACT_MODELS = (
    ResearchPacket,
    RecommendationCatalog,
    FactStoreSnapshot,
    TripWorkspace,
    WeatherContextSnapshot,
    ResearchContextView,
)

MANIFEST_FIELDS = {
    "run_id",
    "generation_id",
    "bundle_id",
    "workspace_revision",
    "fact_data_revision",
    "weather_data_revision",
    "content_hashes",
    "created_at",
}


def _manifest() -> DeliveryRevisionManifest:
    return DeliveryRevisionManifest(
        run_id="run-A",
        generation_id="generation-A",
        bundle_id="bundle-A",
        workspace_revision=1,
        fact_data_revision=2,
        weather_data_revision=3,
        content_hashes={},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_domain_contract_models_declare_no_version_fields():
    for model in CONTRACT_MODELS:
        assert "contract_version" not in model.model_fields, model.__name__
    assert "contract_version" not in DeliveryBundle.model_fields
    assert "contract_version" not in DeliveryRevisionManifest.model_fields
    assert "contract_versions" not in DeliveryRevisionManifest.model_fields


def test_public_responses_declare_no_version_fields():
    assert "contract_version" not in PublicBundleManifestResponse.model_fields
    assert "contract_version" not in PublicBundleWorkspaceResponse.model_fields


def test_manifest_round_trips_without_a_version_field():
    """持久化读回不依赖版本号：落盘再读回只剩当前字段。"""

    manifest = _manifest()
    dumped = manifest.model_dump(mode="json")
    assert set(dumped) == MANIFEST_FIELDS
    assert DeliveryRevisionManifest.model_validate(dumped) == manifest


def test_a_persisted_payload_with_a_removed_version_field_is_rejected():
    """读回只接受当前结构，多出的 contract_version 不会被静默忽略。"""

    payload = _manifest().model_dump(mode="json")
    payload["contract_version"] = "stale"
    with pytest.raises(ValidationError):
        DeliveryRevisionManifest.model_validate(payload)


def test_public_manifest_and_event_payload_drop_removed_version_fields():
    manifest = _manifest()
    public = public_manifest(SimpleNamespace(manifest=manifest))
    assert "contract_version" not in public
    assert set(public) == MANIFEST_FIELDS - {"content_hashes"}

    legacy_event = {**public, "contract_version": "stale"}
    filtered = public_event_manifest(legacy_event)
    assert filtered == public
    assert "contract_version" not in filtered
