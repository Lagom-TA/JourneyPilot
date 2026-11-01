"""生成交付在独立 PostgreSQL 中真实提交和恢复。"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from pypdf import PdfReader
from io import BytesIO

from travel_agent.conversation.chat.delivery import ChatDelivery
from travel_agent.planning.delivery.assembly import assemble_delivery_bundle
from travel_agent.planning.delivery.persistence import _commit_initial_delivery_atomically
from travel_agent.planning.delivery.pdf_export import render_trip_report_pdf
from travel_agent.planning.delivery.public.bundle import public_delivery_bundle
from travel_agent.planning.delivery.projection_builder import build_delivery_projections
from travel_agent.planning.itinerary.models import (
    DayPlanV2,
    StructuredItineraryV2,
    TimelineEntryRef,
    VisitStop,
)
from travel_agent.planning.references import EntityLineage, EntityRef, EntityType
from travel_agent.planning.requirements.inputs import UserInputAnchor
from travel_agent.planning.requirements.place_names import CONTROLLED_DESTINATION_ANCHOR_PREFIX
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.evidence import FactAssertion, FactStoreSnapshot
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.weather.models import WeatherContextSnapshot, WeatherImpact
from travel_agent.planning.workspace import TripWorkspaceV2
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.storage.database import get_db_session
from travel_agent.storage.delivery_bundle_store import DeliveryBundleStore
from travel_agent.storage.trip_run_store import TripRunStore

pytestmark = pytest.mark.postgres


def _delivery_state(run_id: str) -> TravelAgentState:
    trip_date = date(2026, 11, 5)
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    ref = EntityRef(entity_type=EntityType.VISIT_STOP, entity_id="visit-1")
    stop = VisitStop(
        item_id=ref.entity_id,
        day_id="day-1",
        place_id="fixture:park",
        name="测试公园",
        duration_minutes=90,
        planned_start=datetime.fromisoformat("2026-11-05T10:00:00+08:00"),
        planned_end=datetime.fromisoformat("2026-11-05T11:30:00+08:00"),
        selection_reason="适合散步。",
        visit_type="nature",
        lineage=EntityLineage(lineage_kind="authored_entity"),
    )
    itinerary = StructuredItineraryV2(
        itinerary_id="test-itinerary",
        title="城市漫步",
        destination_ids=["city-1"],
        duration_days=1,
        day_plans=[DayPlanV2(
            day_id="day-1", day=1, date=trip_date, destination_id="city-1",
            theme="城市漫步", timeline=[TimelineEntryRef(entry_id="entry-1", **ref.model_dump())],
        )],
        visit_stops=[stop],
        unresolved=["晚间游船未安排"],
    )
    workspace = TripWorkspaceV2(
        run_id=run_id,
        generation_id="generation-test",
        workspace_revision=0,
        itinerary=itinerary,
        recommendation_catalog=RecommendationCatalog(
            generation_id="generation-test", fact_data_revision=0, weather_data_revision=0,
        ),
        user_input_anchors=[UserInputAnchor(
            anchor_id="destination", field_path=f"{CONTROLLED_DESTINATION_ANCHOR_PREFIX}city-1",
            value={"place_id": "city-1", "name": "测试城"}, input_kind="controlled_identity",
        )],
    )
    facts = FactStoreSnapshot(fact_data_revision=0, fact_assertions=[FactAssertion(
        fact_assertion_id="weather-fact", entity_ref=ref, field_path="rain",
        asserted_value=True, criticality="auxiliary", status="verified",
    )])
    weather = WeatherContextSnapshot(
        weather_data_revision=0, trip_start_date=trip_date, trip_end_date=trip_date,
        days=[], retrieved_at=now,
    )
    impact = WeatherImpact(
        weather_impact_id="rain-impact", date=trip_date, target_ref=ref,
        condition_type="rain", severity="medium", action="add_buffer",
        fact_assertion_ids=["weather-fact"], data_kind="forecast", trigger_code="rain",
    )
    report, map_projection, source_index = build_delivery_projections(
        workspace, facts, weather, generated_at=now,
    )
    return TravelAgentState(
        run_id=run_id, trip_workspace_v2=workspace, fact_store_snapshot=facts,
        weather_context=weather, weather_impacts={impact.weather_impact_id: impact},
        report_projection=report, map_projection=map_projection, source_index_projection=source_index,
    )


async def test_initial_delivery_with_weather_and_long_history_is_readable(migrated_async_database):
    runs = TripRunStore()
    bundles = DeliveryBundleStore()
    run = await runs.create_run(session_id="delivery-test", user_id="local", mode="deep")
    await runs.transition_status(run.run_id, TripRunStatus.RUNNING)
    async with get_db_session() as session:
        await session.execute(text("""
            INSERT INTO trip_run_events (run_id, sequence, event_type, payload, created_at)
            SELECT :run_id, n, 'test.progress', '{}'::jsonb, NOW()
            FROM generate_series(3, 505) AS n
        """), {"run_id": run.run_id})
    state = _delivery_state(run.run_id)
    bundle = assemble_delivery_bundle(state)
    assert bundle.weather_snapshot.adjustment_proposals
    assert bundle.weather_snapshot.adjustment_proposals[0].base_weather_data_revision == 0

    committed = await _commit_initial_delivery_atomically(
        bundle_store=bundles, trip_store=runs, state=state, bundle=bundle,
    )
    restored = await DeliveryBundleStore().get_current(run.run_id)
    assert restored == committed == bundle
    document = public_delivery_bundle(restored)["report_projection"]["document"]
    assert document["unresolved"] == ["晚间游船未安排"]
    assert document["cost_coverage_statement"] is None
    assert document["days"][0]["blocks"][0]["summary"] == "适合散步。"
    assert document["days"][0]["blocks"][0]["details"]["price_label"] is None
    assert len(restored.map_projection.content.places) == 1
    assert restored.map_projection.content.places[0].latitude is None
    pdf = render_trip_report_pdf(restored, exported_at=datetime.now(timezone.utc))
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf.content)).pages)
    assert "晚间游船未安排" in pdf_text
    assert pdf_text.count("适合散步。") == 1
    assert "费用按行程逐项列出" not in pdf_text
    assert (await TripRunStore().get_run(run.run_id)).status == TripRunStatus.COMPLETED
    delivery = ChatDelivery(
        run_id=run.run_id, use_deep_research=True, trip_run_store=TripRunStore(),
        bundle_store=DeliveryBundleStore(),
    )
    ready, terminal = await delivery.completion_events(bundle.manifest.bundle_id)
    assert ready.sequence > 500
    assert ready.event_type == "delivery.ready"
    assert terminal.event_type == "run.terminal"
    assert terminal.sequence > ready.sequence
    restored_bundle, recovered_ready, recovered_terminal = await delivery.load_durable_completed_delivery()
    assert restored_bundle == bundle
    assert (recovered_ready.sequence, recovered_terminal.sequence) == (ready.sequence, terminal.sequence)
