"""交付清单的持久化读回只接受当前结构。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from travel_agent.planning.delivery.bundle import DeliveryRevisionManifest

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
