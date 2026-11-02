"""离线模型规划与 PostgreSQL 交付的贯通测试。"""

from types import SimpleNamespace

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from tests.fixtures.chat_execution import request
from tests.planning.research import test_model_research_plan_flow as scenario
from tests.support import memory_stores
from travel_agent.bootstrap import registry
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.storage.database import get_db_session
from travel_agent.storage.delivery_bundle_store import DeliveryBundleStore
from travel_agent.storage.trip_run_store import TripRunStore

pytestmark = pytest.mark.postgres


async def test_offline_model_flow_persists_delivery_and_checkpoints(migrated_async_database, monkeypatch):
    async with AsyncPostgresSaver.from_conn_string(migrated_async_database.libpq_dsn) as checkpointer:
        await checkpointer.setup()
        monkeypatch.setattr(scenario, "InMemorySaver", lambda: checkpointer)
        monkeypatch.setattr(memory_stores, "InMemoryDeliveryBundleStore", DeliveryBundleStore)
        monkeypatch.setattr(memory_stores, "InMemoryTripRunStore", TripRunStore)

        await scenario.test_latest_user_words_and_confirmed_tasks_reach_research_and_delivery(monkeypatch)

        run = await TripRunStore().get_run("offline-flow")
        bundle = await DeliveryBundleStore().get_current("offline-flow")
        assert run.status is TripRunStatus.COMPLETED
        assert bundle is not None
        assert bundle.workspace.itinerary.title == "杭州慢游"
        monkeypatch.setattr(registry, "_components", SimpleNamespace(
            trip_run_store=TripRunStore(), delivery_bundle_store=DeliveryBundleStore(),
        ))
        response = await request("GET", "/api/trip-runs/offline-flow/bundle/current?session_id=offline-flow")
        assert response.status_code == 200
        assert response.json()["workspace"]["itinerary"]["title"] == "杭州慢游"
        async with get_db_session() as session:
            checkpoints = await session.execute(
                text("SELECT count(*) FROM checkpoints WHERE thread_id = :run_id"),
                {"run_id": "offline-flow"},
            )
            assert checkpoints.scalar_one() > 0
