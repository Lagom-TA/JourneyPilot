"""当前旅行的后续问答与调整。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from tests.fixtures.chat_execution import resources as resources, request, decode
from tests.fixtures.itinerary import itinerary_draft, visit_entry
from tests.fixtures.research_catalog import make_visit_packet
from travel_agent.conversation.chat import preparation
from travel_agent.conversation.chat.refinement import RefinementDecision
from travel_agent.planning.delivery.assembly import assemble_delivery_bundle
from travel_agent.planning.delivery.fact_projection import build_fact_snapshot
from travel_agent.planning.delivery.projection_builder import build_delivery_projections
from travel_agent.planning.itinerary.draft import ItineraryCompositionDraft
from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.storage.delivery_bundle_store import BundleCommitKind
from tests.support.memory_stores import InMemoryDeliveryBundleStore


def identity():
    place = {"place_id": "destination_tokyo", "provider": "osm", "kind": "city", "name": "东京", "display_name": "东京", "country_code": "JP", "latitude": 35.68, "longitude": 139.76, "admin_path": []}
    return {"origin": place, "destinations": [place], "start_date": "2026-10-10", "end_date": "2026-10-10", "party": {"adults": 1, "children": 0, "elderly_companions": False, "accessibility_required": False}, "style": {"primary": "文化", "secondary_interests": [], "source": "current"}}


def delivered_bundle(run_id):
    first = make_visit_packet("candidate_visit", "原有景点")
    second = make_visit_packet("candidate_alternative", "候选公园")
    packet = first.model_copy(update={
        "run_id": run_id, "fact_data_revision": 0,
        "candidates": first.candidates + second.candidates,
        "source_records": first.source_records + second.source_records,
        "fact_assertions": first.fact_assertions + second.fact_assertions,
        "field_provenance": first.field_provenance + second.field_provenance,
    })
    from travel_agent.planning.research.catalog import RecommendationCatalog
    catalog = RecommendationCatalog(generation_id="generation_test", fact_data_revision=0, weather_data_revision=0, research_packets=[packet])
    draft = ItineraryCompositionDraft.model_validate(itinerary_draft([visit_entry()]))
    from travel_agent.planning.requirements.inputs import UserInputAnchor
    from travel_agent.planning.requirements.place_names import CONTROLLED_DESTINATION_ANCHOR_PREFIX
    workspace = materialize_trip_workspace(run_id=run_id, workspace_revision=0, composition=draft, catalog=catalog, requirements="喜欢安静的文化景点", composition_mutations=[], user_input_anchors=[UserInputAnchor(anchor_id="destination", field_path=f"{CONTROLLED_DESTINATION_ANCHOR_PREFIX}destination_tokyo", value=identity()["destinations"][0], input_kind="controlled_identity")])
    now = datetime.now(timezone.utc)
    weather = WeatherContextSnapshot(weather_data_revision=0, trip_start_date=draft.days[0].date, trip_end_date=draft.days[0].date, days=[], retrieved_at=now)
    facts = build_fact_snapshot(workspace)
    report, map_projection, source_index = build_delivery_projections(workspace, facts, weather, generated_at=now)
    return assemble_delivery_bundle(TravelAgentState(run_id=run_id, trip_workspace=workspace, fact_store_snapshot=facts, weather_context=weather, report_projection=report, map_projection=map_projection, source_index_projection=source_index))


@pytest.fixture
async def delivered(resources, monkeypatch):
    run = await resources.trip_run_store.create_run(session_id="trip-session", user_id="local", mode="deep", controlled_trip_identity=identity())
    await resources.trip_run_store.transition_status(run.run_id, TripRunStatus.RUNNING)
    bundle = delivered_bundle(run.run_id)
    bundles = InMemoryDeliveryBundleStore()
    await bundles.commit(bundle=bundle, kind=BundleCommitKind.CREATE, idempotency_key="initial")
    await resources.trip_run_store.complete_delivery(run.run_id, bundle_id=bundle.manifest.bundle_id, manifest=bundle.manifest.model_dump(mode="json"))
    resources.delivery_bundle_store = bundles
    resources.checkpointer = InMemorySaver()
    return run, bundle


async def test_question_uses_current_trip_without_changing_delivery(resources, delivered, monkeypatch):
    run, bundle = delivered
    seen = {}
    async def decide(text, trip_identity, current):
        seen.update(text=text, identity=trip_identity, bundle=current)
        return RefinementDecision(action="answer")
    monkeypatch.setattr(preparation, "understand_followup", decide)
    class Answer:
        async def astream(self, *, refinement_context, stream_queue, **kwargs):
            assert "原有景点" in refinement_context
            await stream_queue.put(("token", "fast_answer_agent", "安排了原有景点。"))
            yield {"fast_answer_agent": {"messages": [SimpleNamespace(content="安排了原有景点。")]}}
    resources.fast_workflow = Answer()
    response = await request("POST", "/api/chat-stream", {"messages": [{"role": "user", "content": "当天安排了什么？", "message_id": "question-1"}], "session_id": "trip-session", "run_id": run.run_id})
    assert response.status_code == 200
    assert any(event.get("final_content") == "安排了原有景点。" for event in decode(response))
    assert seen["bundle"] == bundle
    assert await resources.delivery_bundle_store.get_current(run.run_id) == bundle


async def test_local_revision_reuses_an_unselected_candidate(resources, delivered, monkeypatch):
    run, bundle = delivered
    async def decide(*args): return RefinementDecision(action="revise")
    monkeypatch.setattr(preparation, "understand_followup", decide)
    from travel_agent.planning.itinerary import node as itinerary_node
    class Model:
        async def ainvoke_with_tools_events(self, messages, tools):
            text = "\n".join(str(message.get("content", "")) for message in messages)
            assert "原有景点" in text and "candidate_alternative" in text
            draft = itinerary_draft([{**visit_entry(), "candidate_id": "candidate_alternative"}])
            yield {"type": "finish", "content": json.dumps(draft), "tool_calls": []}
        async def ainvoke(self, *args, **kwargs): return "{}"
    model = Model()
    monkeypatch.setattr(itinerary_node, "get_model_router", lambda: object())
    monkeypatch.setattr(itinerary_node, "llm_for_task", lambda *args, **kwargs: model)
    async def tools(_): return []
    async def keep_copy(workspace, _llm): return workspace
    monkeypatch.setattr(itinerary_node, "get_available_tools", tools)
    monkeypatch.setattr(itinerary_node, "write_itinerary_copy", keep_copy)
    monkeypatch.setattr("travel_agent.planning.execution.ensure_budget_baseline", lambda: _nothing())
    from travel_agent.planning.workflow import TravelPlanningWorkflow
    resources.travel_workflow = TravelPlanningWorkflow(resources.checkpointer, delivery_bundle_store=resources.delivery_bundle_store, trip_run_store=resources.trip_run_store)
    response = await request("POST", "/api/chat-stream", {"messages": [{"role": "user", "content": "把景点换成候选公园", "message_id": "change-1"}], "session_id": "trip-session", "run_id": run.run_id})
    assert response.status_code == 200
    events = decode(response)
    assert any(event["type"] == "delivery_ready" for event in events), events
    new_run_id = next(event["run_id"] for event in events if event["type"] == "delivery_ready")
    updated = await resources.delivery_bundle_store.get_current(new_run_id)
    assert updated.workspace.itinerary.visit_stops[0].name == "候选公园"
    assert await resources.delivery_bundle_store.get_current(run.run_id) == bundle
    repeated = await request("POST", "/api/chat-stream", {"messages": [{"role": "user", "content": "把景点换成候选公园", "message_id": "change-1"}], "session_id": "trip-session", "run_id": run.run_id})
    assert next(event["run_id"] for event in decode(repeated) if event["type"] == "chat_start") == new_run_id


async def test_destination_change_reaches_a_new_plan_and_failure_keeps_the_original(resources, delivered, monkeypatch):
    run, bundle = delivered
    async def decide(*args): return RefinementDecision(action="replan")
    monkeypatch.setattr(preparation, "understand_followup", decide)
    from travel_agent.planning.requirements.understanding import agent as understanding
    from travel_agent.planning.research import research_plan_node
    class Model:
        async def ainvoke_with_tools_events(self, messages, tools):
            changed = identity()
            changed["destinations"] = [{**changed["destinations"][0], "place_id": "destination_kyoto", "name": "京都", "display_name": "京都"}]
            yield {"type": "finish", "content": json.dumps({"action": "ready", "trip_identity": changed}), "tool_calls": []}
        async def ainvoke(self, messages, **kwargs):
            assert "京都" in str(messages)
            return json.dumps({"summary": "京都慢游", "destination_task": "研究京都", "transport_task": "研究交通", "accommodation_task": "研究住宿", "itinerary_task": "安排行程"})
    model = Model()
    for module in (understanding, research_plan_node):
        monkeypatch.setattr(module, "get_model_router", lambda: object())
        monkeypatch.setattr(module, "llm_for_task", lambda *args, **kwargs: model)
    async def tools(_): return []
    monkeypatch.setattr(understanding, "get_available_tools", tools)
    monkeypatch.setattr("travel_agent.planning.execution.ensure_budget_baseline", lambda: _nothing())
    from travel_agent.planning.workflow import TravelPlanningWorkflow
    resources.travel_workflow = TravelPlanningWorkflow(resources.checkpointer, delivery_bundle_store=resources.delivery_bundle_store, trip_run_store=resources.trip_run_store)
    response = await request("POST", "/api/chat-stream", {"messages": [{"role": "user", "content": "目的地改成京都", "message_id": "replan-1"}], "session_id": "trip-session", "run_id": run.run_id})
    events = decode(response)
    gate = next(event for event in events if event["type"] == "approval_gate_raised")
    new_run = await resources.trip_run_store.get_run(gate["run_id"])
    assert new_run.parent_run_id == run.run_id
    assert new_run.controlled_trip_identity["destinations"][0]["name"] == "京都"
    assert new_run.controlled_trip_identity["style"]["primary"] == "文化"
    assert "京都" in gate["payload"]["plan_text"]
    await resources.trip_run_store.transition_status(new_run.run_id, TripRunStatus.FAILED)
    assert await resources.delivery_bundle_store.get_current(run.run_id) == bundle


async def _nothing():
    return None
