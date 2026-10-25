"""Delivery HTTP boundaries without providers, report rendering or app startup."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tests.fixtures.chat_execution import request, resources as resources
from travel_agent.integrations.pdf_readiness import PdfFontUnavailable
from travel_agent.planning.delivery import export
from travel_agent.planning.delivery.pdf_export import ReportOutOfDateError
from travel_agent.planning.run_errors import DeliveryBundleMissing
from travel_agent.planning.weather import bundle_refresh
from travel_agent.runtime.blocking_work import BlockingWorkBusy
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.storage.delivery_bundle_store import BundleRevisionConflict


@pytest.fixture
def revision_bundle(resources):
    manifest = SimpleNamespace(
        bundle_id="immutable-bundle",
        workspace_revision=2,
        fact_data_revision=3,
        weather_data_revision=4,
        model_dump=lambda **_: {"bundle_id": "immutable-bundle"},
    )
    bundle = SimpleNamespace(manifest=manifest)

    class Bundles:
        async def get_current(self, run_id):
            return bundle

    resources.delivery_bundle_store = Bundles()
    return bundle


def pdf_body(**updates):
    body = {
        "bundle_id": "immutable-bundle",
        "workspace_revision": 2,
        "fact_data_revision": 3,
        "weather_data_revision": 4,
    }
    body.update(updates)
    return body


@pytest.mark.parametrize(
    "field",
    ["bundle_id", "workspace_revision", "fact_data_revision", "weather_data_revision"],
)
async def test_pdf_checks_every_revision_before_scheduling_work(
    resources, revision_bundle, monkeypatch, field
):
    run = await resources.trip_run_store.create_run(
        session_id="pdf", user_id="local", mode="fast"
    )

    async def forbidden(*args, **kwargs):
        pytest.fail("stale report must not enter the blocking lane")

    monkeypatch.setattr(export, "run_blocking", forbidden)
    response = await request(
        "POST",
        f"/api/trip-runs/{run.run_id}/bundle/current/pdf",
        pdf_body(**{field: "older" if field == "bundle_id" else 0}),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "report_out_of_date",
        "current_bundle_id": "immutable-bundle",
    }
    assert run.status is TripRunStatus.CREATED


async def test_pdf_uses_immutable_snapshot_utc_time_and_api_headers(
    resources, revision_bundle, monkeypatch
):
    run = await resources.trip_run_store.create_run(
        session_id="pdf", user_id="local", mode="fast"
    )
    marker = object()
    monkeypatch.setattr(export, "render_trip_report_pdf", marker)
    before = datetime.now(timezone.utc)

    async def schedule(lane, renderer, bundle, *, exported_at):
        assert lane == "pdf_export" and renderer is marker and bundle is revision_bundle
        assert exported_at.tzinfo is timezone.utc and exported_at >= before
        await asyncio.sleep(0)
        return SimpleNamespace(
            content=b"offline-pdf-fixture",
            filename="trip-report.pdf",
            bundle_id="immutable-bundle",
            build_context=SimpleNamespace(
                source_workspace_revision=2,
                source_fact_data_revision=3,
                source_weather_data_revision=4,
            ),
        )

    monkeypatch.setattr(export, "run_blocking", schedule)
    response = await request(
        "POST", f"/api/trip-runs/{run.run_id}/bundle/current/pdf", pdf_body()
    )
    assert response.status_code == 200 and response.content == b"offline-pdf-fixture"
    assert response.headers["content-type"] == "application/pdf"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="trip-report.pdf"'
    )
    assert response.headers["x-journeypilot-bundle-id"] == "immutable-bundle"
    assert response.headers["x-journeypilot-workspace-revision"] == "2"
    assert response.headers["x-journeypilot-fact-revision"] == "3"
    assert response.headers["x-journeypilot-weather-revision"] == "4"


@pytest.mark.parametrize(
    "exception,status,detail",
    [
        (ReportOutOfDateError("report"), 409, {"code": "report_out_of_date"}),
        (
            PdfFontUnavailable("unavailable"),
            503,
            {
                "code": "pdf_temporarily_unavailable",
                "message": "PDF 暂时无法生成，请稍后重试。",
            },
        ),
        (
            BlockingWorkBusy("pdf_export", 0.1),
            503,
            {"code": "pdf_export_busy", "message": "正在导出的报告太多，稍后再试。"},
        ),
    ],
)
async def test_pdf_resource_errors_keep_http_contract(
    resources, revision_bundle, monkeypatch, exception, status, detail
):
    run = await resources.trip_run_store.create_run(
        session_id="pdf", user_id="local", mode="fast"
    )

    async def schedule(*args, **kwargs):
        raise exception

    monkeypatch.setattr(export, "run_blocking", schedule)
    response = await request(
        "POST", f"/api/trip-runs/{run.run_id}/bundle/current/pdf", pdf_body()
    )
    assert response.status_code == status and response.json()["detail"] == detail


async def test_weather_precheck_reads_head_only_and_does_not_construct_service(
    monkeypatch,
):
    observed = []

    class Bundles:
        async def get_current_bundle_id(self, run_id):
            observed.append("head")
            return None

        async def get_current(self, run_id):
            pytest.fail("weather precheck must not parse a Bundle")

    def service(*args, **kwargs):
        pytest.fail("missing head must fail before service construction")

    monkeypatch.setattr(bundle_refresh, "WeatherBundleRefreshService", service)
    with pytest.raises(DeliveryBundleMissing):
        await bundle_refresh.refresh_delivery_weather(
            "weather",
            expected=None,
            refresh_id="refresh",
            bundle_store=Bundles(),
            trip_run_store=None,
        )
    assert observed == ["head"]


@pytest.mark.parametrize("committed", [False, True])
async def test_weather_event_is_appended_only_after_commit(
    resources, revision_bundle, monkeypatch, committed
):
    observed = []
    run = await resources.trip_run_store.create_run(
        session_id="weather", user_id="local", mode="fast"
    )

    async def head(run_id):
        observed.append("head")
        return "immutable-bundle"

    resources.delivery_bundle_store.get_current_bundle_id = head
    marker = object()

    class RefreshService:
        def __init__(self, store, builder, *, clock):
            assert (
                store is resources.delivery_bundle_store
                and builder is marker
                and clock() == 123
            )
            observed.append("service")

        async def refresh_if_needed(self, **kwargs):
            assert kwargs == {
                "run_id": run.run_id,
                "expected": "expected-vector",
                "idempotency_key": "refresh",
                "operation": "weather_refresh_on_open",
            }
            observed.append("commit" if committed else "no_change")
            return SimpleNamespace(committed=committed, bundle=revision_bundle)

    monkeypatch.setattr(bundle_refresh, "WeatherBundleRefreshService", RefreshService)
    result = await bundle_refresh.refresh_delivery_weather(
        run.run_id,
        expected="expected-vector",
        refresh_id="refresh",
        bundle_store=resources.delivery_bundle_store,
        trip_run_store=resources.trip_run_store,
        weather_context_builder=marker,
        clock=lambda: 123,
    )
    assert result.bundle is revision_bundle
    events = [
        event
        for event in resources.trip_run_store.events[run.run_id]
        if event.event_type == "bundle.current_changed"
    ]
    assert len(events) == int(committed)
    if committed:
        assert events[0].payload == {
            "reason": "weather_refresh_on_open",
            "bundle_id": "immutable-bundle",
            "manifest": {"bundle_id": "immutable-bundle"},
            "idempotency_key": f"{run.run_id}:bundle_current_changed:immutable-bundle",
        }
    assert observed == ["head", "service", "commit" if committed else "no_change"]


async def test_weather_cas_conflict_maps_from_head_without_reading_bundle(
    resources, monkeypatch
):
    run = await resources.trip_run_store.create_run(
        session_id="weather", user_id="local", mode="fast"
    )
    heads = []

    class Bundles:
        async def get_current_bundle_id(self, run_id):
            heads.append(run_id)
            return "latest-head"

        async def get_current(self, run_id):
            pytest.fail("revision conflict may read head identity only")

    resources.delivery_bundle_store = Bundles()
    resources.weather_context_builder = object()

    class RefreshService:
        def __init__(self, *args, **kwargs):
            pass

        async def refresh_if_needed(self, **kwargs):
            raise BundleRevisionConflict("stale vector")

    monkeypatch.setattr(bundle_refresh, "WeatherBundleRefreshService", RefreshService)
    response = await request(
        "POST",
        f"/api/trip-runs/{run.run_id}/bundle/current/weather/refresh",
        {
            "refresh_id": "refresh",
            "base_bundle_id": "older",
            "base_workspace_revision": 0,
            "base_fact_data_revision": 0,
            "base_weather_data_revision": 0,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "bundle_revision_conflict",
        "current_bundle_id": "latest-head",
    }
    assert heads == [run.run_id, run.run_id]
