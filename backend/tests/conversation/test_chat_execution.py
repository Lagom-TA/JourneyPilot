"""用有界的假工作流验证真实的执行器与传输层。"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tests.fixtures.chat_execution import (
    chat_body,
    decision,
    decode,
    execute,
    prepare,
    request,
    resources as resources,
)
from travel_agent.api.routes import chat as chat_api
from travel_agent.conversation.chat import completion, failures
from travel_agent.conversation.intake_contracts import RouteName
from travel_agent.planning.delivery.bundle import DeliveryRevisionManifest
from travel_agent.runtime.command_contracts import RunCommandStatus, RunCommandType
from travel_agent.runtime.journal import current_execution_lease
from travel_agent.runtime.run_contracts import TripRunStatus


@pytest.mark.parametrize("cancel_wins", [False, True])
async def test_await_input_persists_then_marks_checkpoint_then_displays(
    resources, monkeypatch, cancel_wins
):
    runs = resources.trip_run_store
    run = await runs.create_run(
        session_id="gate", user_id="local", mode="deep", resume_policy="checkpoint"
    )
    body = chat_body(
        run_id=run.run_id,
        session_id="gate",
        route_decision=decision(RouteName.TRIP_PLANNING).model_dump(mode="json"),
    )
    observed = []

    class GateWorkflow:
        async def probe_checkpoint(self, run_id):
            assert run_id == run.run_id
            assert run.status is TripRunStatus.AWAITING_INPUT
            observed.append("checkpoint")
            return True, "safe-gate"

        async def astream(self, **kwargs):
            assert current_execution_lease.get() == "request-lease"
            yield {
                "__interrupt__": [
                    {"gate": "plan", "type": "approval_gate", "payload": {}}
                ]
            }

    resources.travel_workflow = GateWorkflow()
    resources.checkpointer = object()
    transition = runs.transition_status

    async def write(run_id, status, **kwargs):
        if status is TripRunStatus.AWAITING_INPUT:
            if cancel_wins:
                await runs.request_cancel(run_id)
            else:
                observed.append("awaiting.persist")
        return await transition(run_id, status, **kwargs)

    monkeypatch.setattr(runs, "transition_status", write)
    prepared = await prepare(body, resources)
    events = []
    async for event in execute(body, prepared, resources):
        events.append(event)
        if event and event["type"] == "approval_gate_raised":
            assert observed == ["awaiting.persist", "checkpoint"]
            assert "lease.safe" in resources.run_execution_store.log
            assert runs.states[run.run_id].pending_user_choice["gate"] == "plan"
            assert any(
                e.event_type == "run.gate_raised" for e in runs.events[run.run_id]
            )
    if cancel_wins:
        assert [e["type"] for e in events] == ["chat_start", "run_cancelled"]
        assert run.status is TripRunStatus.CANCELLED and observed == []
    else:
        assert [e["type"] for e in events] == [
            "chat_start",
            "approval_gate_raised",
            "chat_complete",
        ]
        assert run.status is TripRunStatus.AWAITING_INPUT
    assert len(resources.chat_session_memory.turns) == 1
    assert not await resources.run_execution_store.has_live_lease(run.run_id)


async def test_pending_cancel_is_consumed_before_workflow_can_start(resources):
    run = await resources.trip_run_store.create_run(
        session_id="pending", user_id="local", mode="fast"
    )
    command, _ = await resources.run_command_store.enqueue(
        run.run_id, RunCommandType.CANCEL, {"action": "cancel"}
    )
    from travel_agent.runtime.cancellation import (
        check_cancel_requested,
        run_control_registry,
    )

    class CooperativeWorkflow:
        async def astream(self, **kwargs):
            assert run_control_registry.get(run.run_id).cancel_event.is_set()
            assert command.status is RunCommandStatus.CLAIMED
            from travel_agent.runtime.context import current_run_id

            token = current_run_id.set(run.run_id)
            try:
                check_cancel_requested("fast_answer_agent")
            finally:
                current_run_id.reset(token)
            pytest.fail("pending cancel must stop at the first cooperative boundary")
            yield {}

    resources.fast_workflow = CooperativeWorkflow()
    response = await request(
        "POST", "/api/chat-stream", chat_body(run_id=run.run_id, session_id="pending")
    )
    assert [e["type"] for e in decode(response)] == ["chat_start", "run_cancelled"]
    assert run.status is TripRunStatus.CANCELLED
    assert command.status is RunCommandStatus.CONSUMED


@pytest.mark.parametrize("bookkeeping_failure", [False, True])
async def test_deep_asgi_body_is_backed_by_persisted_bundle_and_ordered_terminal(
    resources, monkeypatch, bookkeeping_failure
):
    runs = resources.trip_run_store
    run = await runs.create_run(session_id="deep-http", user_id="local", mode="deep")
    manifest = DeliveryRevisionManifest(
        run_id=run.run_id,
        generation_id="generation",
        bundle_id="bundle-http",
        workspace_revision=0,
        fact_data_revision=0,
        weather_data_revision=0,
        contract_versions={},
        content_hashes={},
        created_at=datetime.now(timezone.utc),
    )
    bundle = SimpleNamespace(manifest=manifest)

    class Bundles:
        async def get_current(self, run_id):
            assert run_id == run.run_id
            return bundle if run.status is TripRunStatus.COMPLETED else None

    resources.delivery_bundle_store = Bundles()

    class DeepWorkflow:
        async def astream(self, **kwargs):
            assert kwargs["resume_from_checkpoint"] is False
            assert kwargs["controlled_trip_identity"] == {}
            assert current_execution_lease.get() == "request-lease"
            queue = kwargs["stream_queue"]
            await queue.put(
                ("token", "itinerary_planner", "provisional deep text must not publish")
            )
            await queue.put(("state_snapshot", {"run_id": run.run_id}))
            await runs.complete_delivery(
                run.run_id,
                bundle_id=manifest.bundle_id,
                manifest=manifest.model_dump(mode="json"),
            )
            if bookkeeping_failure:
                raise RuntimeError("after durable completion")
            yield {
                "__final_state__": {
                    "run_id": run.run_id,
                    "delivery_bundle": {"manifest": manifest.model_dump(mode="json")},
                }
            }

    resources.travel_workflow = DeepWorkflow()

    def public_bundle(current):
        assert current is bundle and run.status is TripRunStatus.COMPLETED
        durable = [
            e
            for e in runs.events[run.run_id]
            if e.event_type in {"delivery.ready", "run.terminal"}
        ]
        assert len(durable) == 2 and durable[0].sequence < durable[1].sequence
        return {"manifest": manifest.model_dump(mode="json")}

    monkeypatch.setattr(completion, "public_delivery_bundle", public_bundle)
    monkeypatch.setattr(failures, "public_delivery_bundle", public_bundle)
    response = await request(
        "POST",
        "/api/chat-stream",
        chat_body(
            run_id=run.run_id,
            session_id="deep-http",
            route_decision=decision(RouteName.TRIP_PLANNING).model_dump(mode="json"),
        ),
    )
    events = decode(response)
    assert [e["type"] for e in events] == [
        "chat_start",
        "delivery_ready",
        "run_terminal",
    ]
    assert events[1]["event_seq"] < events[2]["event_seq"]
    assert events[1]["bundle_id"] == events[2]["bundle_id"] == manifest.bundle_id
    assert (
        "provisional deep text" not in response.text
        and "raw reasoning" not in response.text
    )
    assert run.status is TripRunStatus.COMPLETED
    assert not await resources.run_execution_store.has_live_lease(run.run_id)
    assert len(resources.chat_session_memory.turns) == (0 if bookkeeping_failure else 1)


async def test_http_projection_failure_returns_to_original_execution_boundary(
    resources, monkeypatch
):
    original = chat_api.project_sse_payload

    def projection(payload):
        if payload["type"] == "chat_chunk":
            raise ValueError("projection failed after headers")
        return original(payload)

    monkeypatch.setattr(chat_api, "project_sse_payload", projection)
    response = await request("POST", "/api/chat-stream", chat_body())
    assert response.status_code == 200
    events = decode(response)
    assert [e["type"] for e in events] == ["chat_start", "run_failed", "error"]
    assert (
        await resources.trip_run_store.get_run(events[0]["run_id"])
    ).status is TripRunStatus.FAILED
    assert not await resources.run_execution_store.has_live_lease(events[0]["run_id"])
