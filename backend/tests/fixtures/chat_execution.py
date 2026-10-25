"""Shared isolated chat resources and execution helpers."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from tests.fixtures.run_commands import FakeCommandStore
from travel_agent.bootstrap import registry
from travel_agent.config import loader
from travel_agent.config.models import Settings
from travel_agent.api.app import create_app
from travel_agent.conversation.chat import preparation
from travel_agent.conversation.chat.contracts import ChatRequest
from travel_agent.conversation.chat.delivery import ChatDelivery
from travel_agent.conversation.chat.execution import execute_chat
from travel_agent.conversation.intake_contracts import RouteDecision, RouteName
from travel_agent.planning.delivery.bundle import DeliveryRevisionManifest
from travel_agent.runtime.cancellation import run_control_registry
from travel_agent.runtime.journal import current_execution_lease
from travel_agent.runtime.run_contracts import (
    RunExecution,
    RunRecoveryStatus,
    TripRunStatus,
)
from travel_agent.storage.trip_run_store import InMemoryTripRunStore


class Commands(FakeCommandStore):
    async def get(self, run_id, command_id):
        command = self.commands.get(command_id)
        return command if command and command.run_id == run_id else None


class ExecutionStore:
    def __init__(self, log=None):
        self.rows = {}
        self.log = log if log is not None else []
        self.released = asyncio.Event()

    async def get(self, run_id):
        return self.rows.get(run_id)

    async def claim(self, run_id, *, lease_seconds, last_safe_checkpoint_id=None):
        self.log.append("lease.claim")
        if await self.has_live_lease(run_id):
            return None
        row = RunExecution(
            run_id=run_id,
            lease_token="request-lease",
            recovery_status=RunRecoveryStatus.CLAIMED,
            last_safe_checkpoint_id=last_safe_checkpoint_id,
        )
        self.rows[run_id] = row
        return row

    async def heartbeat(self, run_id, *, lease_token, **kwargs):
        row = self.rows.get(run_id)
        return bool(row and row.lease_token == lease_token)

    async def mark_safe_checkpoint(self, run_id, *, lease_token, checkpoint_id):
        self.log.append("lease.safe")
        self.rows[run_id].last_safe_checkpoint_id = checkpoint_id
        return True

    async def release(self, run_id, *, lease_token, recovery_status, recovery_reason):
        self.log.append(("lease.release", recovery_reason))
        row = self.rows[run_id]
        if row.lease_token != lease_token:
            return False
        row.lease_token = None
        row.recovery_status = recovery_status
        self.released.set()
        return True

    async def has_live_lease(self, run_id):
        self.log.append("lease.live")
        row = self.rows.get(run_id)
        return bool(row and row.lease_token)


class ChatMemory:
    def __init__(self):
        self.turns = []

    async def ensure_session(self, **kwargs):
        return None

    async def get_recent_messages_within_token_budget(self, **kwargs):
        return []

    async def get_anchor(self, **kwargs):
        return None, 0

    async def save_turn(self, **kwargs):
        self.turns.append(kwargs)


class Profiles:
    async def get_user_profile(self, user_id):
        return SimpleNamespace(revision=7, auto_portrait="fixed baseline")


class FastWorkflow:
    def __init__(self):
        self.calls = []

    async def astream(
        self,
        *,
        user_message,
        session_id,
        user_id,
        selected_mcp_servers,
        conversation_history,
        stream_queue,
        session_anchor,
        session_compressed,
        preset_context,
        preset_pack_constraints,
        run_id,
        route_decision,
    ):
        assert current_execution_lease.get() == "request-lease"
        self.calls.append(user_message)
        await stream_queue.put(("react_thinking", "fast_answer_agent", "never display"))
        await stream_queue.put(("token", "fast_answer_agent", "hello"))
        yield {"fast_answer_agent": {"messages": [SimpleNamespace(content="hello")]}}


@pytest.fixture
def resources(monkeypatch):
    settings = Settings(embedding={"enabled": False})
    monkeypatch.setattr(loader, "_effective", SimpleNamespace(settings=settings))
    workflow = FastWorkflow()
    memory = ChatMemory()
    execution = ExecutionStore()
    runs = InMemoryTripRunStore()
    components = SimpleNamespace(
        trip_run_store=runs,
        run_execution_store=execution,
        run_command_store=Commands(),
        chat_session_memory=memory,
        user_profile_memory=Profiles(),
        travel_workflow=workflow,
        fast_workflow=workflow,
        delivery_bundle_store=None,
        background_job_worker=None,
        checkpointer=None,
    )
    monkeypatch.setattr(registry, "_components", components)
    run_control_registry.clear()
    yield components
    run_control_registry.clear()


def decision(route=RouteName.FAST_ANSWER, *, confirm=False):
    return RouteDecision(
        route=route,
        confidence=0.9,
        requires_trip_draft=route == RouteName.TRIP_PLANNING,
        requires_confirmation=confirm,
    )


def chat_body(**updates):
    body = {
        "messages": [{"role": "user", "content": "苏州适合玩几天？"}],
        "route_decision": decision().model_dump(mode="json"),
    }
    body.update(updates)
    return body


def decode(response):
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


async def request(method, path, body=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://offline"
    ) as client:
        return await client.request(method, path, json=body)


async def prepare(body, resources):
    return await preparation.prepare_chat(
        ChatRequest.model_validate(body),
        trip_run_store=resources.trip_run_store,
        chat_session_memory=resources.chat_session_memory,
        run_execution_store=resources.run_execution_store,
        travel_workflow=resources.travel_workflow,
        checkpointer=resources.checkpointer,
    )


def execute(body, prepared, resources):
    return execute_chat(
        ChatRequest.model_validate(body),
        prepared,
        trip_run_store=resources.trip_run_store,
        chat_session_memory=resources.chat_session_memory,
        user_profile_memory=resources.user_profile_memory,
        travel_workflow=resources.travel_workflow,
        fast_workflow=resources.fast_workflow,
        run_command_store=resources.run_command_store,
        delivery_bundle_store=resources.delivery_bundle_store,
        background_job_worker=None,
    )


async def durable_delivery(resources):
    run = await resources.trip_run_store.create_run(
        session_id="deep", user_id="local", mode="deep"
    )
    await resources.trip_run_store.transition_status(run.run_id, TripRunStatus.RUNNING)
    manifest = DeliveryRevisionManifest(
        run_id=run.run_id,
        generation_id="generation",
        bundle_id="bundle-proof",
        workspace_revision=0,
        fact_data_revision=0,
        weather_data_revision=0,
        contract_versions={},
        content_hashes={},
        created_at=datetime.now(timezone.utc),
    )
    await resources.trip_run_store.complete_delivery(
        run.run_id,
        bundle_id=manifest.bundle_id,
        manifest=manifest.model_dump(mode="json"),
    )
    bundle = SimpleNamespace(manifest=manifest)

    class Bundles:
        async def get_current(self, run_id):
            return bundle

    delivery = ChatDelivery(
        run_id=run.run_id,
        use_deep_research=True,
        trip_run_store=resources.trip_run_store,
        bundle_store=Bundles(),
    )
    return run, bundle, delivery
