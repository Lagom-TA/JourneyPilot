"""规划工作流入口。"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Dict, List, NoReturn, Optional

from langgraph.types import Command
from pydantic import ValidationError

from travel_agent.config.loader import get_settings
from travel_agent.conversation.messages import build_messages
from travel_agent.llm.usage import get_usage_recorder
from travel_agent.planning.graph import get_travel_graph
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.context import run_attribution
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from travel_agent.runtime.run_contracts import generate_trip_run_id
from travel_agent.storage.cost_ledger_store import get_cost_ledger_store
from travel_agent.storage.delivery_bundle_store import DeliveryBundleStore
from travel_agent.storage.tool_audit_store import get_tool_audit_store
from travel_agent.storage.trip_run_store import TripRunStore, get_trip_run_store

logger = logging.getLogger(__name__)


class CheckpointContractError(RuntimeError):
    """持久化的图状态不满足当前 v2 契约。"""


def _is_checkpoint_contract_failure(exc: BaseException) -> bool:
    if isinstance(exc, (ValidationError, AttributeError)):
        return True
    nested = getattr(exc, "exceptions", None)
    return bool(nested) and all(
        _is_checkpoint_contract_failure(item) for item in nested
    )


def _reject_checkpoint_contract(
    run_id: str,
    exc: Exception,
    *,
    warning_template: str,
    contract_message: str,
) -> NoReturn:
    """checkpoint 合同拒绝的公共收尾：先 warning 再把原异常包成 CheckpointContractError。"""
    logger.warning(warning_template, run_id, exc)
    raise CheckpointContractError(contract_message) from exc


def _configured_model_versions() -> Dict[str, str]:
    settings = get_settings()
    primary = str(settings.primary_model.model_name or "").strip()
    fast = str(settings.fast_model.model_name or "").strip() or primary
    return {"primary": primary, "fast": fast}


GRAPH_RECURSION_LIMIT = 250


class TravelPlanningWorkflow:
    """深度调研工作流封装类。"""

    def __init__(
        self,
        checkpointer: Optional[Any] = None,
        *,
        delivery_bundle_store: Optional[DeliveryBundleStore] = None,
        trip_run_store: Optional[TripRunStore] = None,
    ) -> None:
        self._graph = get_travel_graph(checkpointer=checkpointer)
        self._checkpointer = checkpointer
        self._delivery_bundle_store = delivery_bundle_store or DeliveryBundleStore()
        self._trip_run_store = trip_run_store or get_trip_run_store()

    async def has_checkpoint(self, run_id: str) -> bool:
        """返回编译后的图是否为 run_id 持久化过状态。"""
        available, _checkpoint_id = await self.probe_checkpoint(run_id)
        return available

    async def probe_checkpoint(self, run_id: str) -> tuple[bool, Optional[str]]:
        """返回是否可恢复，以及承载该状态的 checkpoint id。"""
        if self._checkpointer is None:
            return False, None
        try:
            snapshot = await self._graph.aget_state(
                {"configurable": {"thread_id": run_id}}
            )
        except Exception as exc:
            if not _is_checkpoint_contract_failure(exc):
                raise
            _reject_checkpoint_contract(
                run_id,
                exc,
                warning_template="Checkpoint rejected by current v2 contract run_id=%s error=%s",
                contract_message="checkpoint does not satisfy the current JourneyPilot v2 contract",
            )
        if snapshot.values:
            try:
                TravelAgentState.model_validate(snapshot.values)
            except Exception as exc:
                _reject_checkpoint_contract(
                    run_id,
                    exc,
                    warning_template="Checkpoint completion contract rejected run_id=%s error=%s",
                    contract_message="checkpoint does not satisfy the current JourneyPilot completion contract",
                )
        available = bool(
            snapshot.values or snapshot.next or snapshot.tasks or snapshot.interrupts
        )
        configurable = (snapshot.config or {}).get("configurable") or {}
        checkpoint_id = configurable.get("checkpoint_id")
        return available, str(checkpoint_id) if checkpoint_id else None

    async def astream(
        self,
        user_message: str,
        session_id: str,
        user_id: str = LOCAL_USER_ID,
        selected_mcp_servers: Optional[List[str]] = None,
        current_time: str = "",
        conversation_history: Optional[list] = None,
        stream_queue=None,
        session_anchor: Optional[Dict[str, Any]] = None,
        session_compressed: bool = False,
        preset_context: str = "",
        preset_pack_constraints: Optional[Dict[str, str]] = None,
        run_id: Optional[str] = None,
        resume_from_checkpoint: bool = False,
        resume_payload: Optional[Dict[str, Any]] = None,
        plan_gate_enabled: Optional[bool] = None,
        controlled_trip_identity: Optional[Dict[str, Any]] = None,
        route_decision: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行深度调研工作流。"""
        import datetime

        effective_run_id = run_id or generate_trip_run_id()
        graph_input: Optional[TravelAgentState | Command]
        if resume_from_checkpoint:
            graph_input = (
                Command(resume=resume_payload) if resume_payload is not None else None
            )
        else:
            messages = build_messages(conversation_history, user_message)
            graph_input = TravelAgentState(
                messages=messages,
                session_id=session_id,
                user_id=user_id,
                selected_mcp_servers=selected_mcp_servers or [],
                user_query=user_message,
                run_id=effective_run_id,
                current_time=current_time
                or datetime.datetime.now().strftime("%Y-%m-%d %A %H:%M:%S"),
                session_anchor=session_anchor,
                session_compressed=session_compressed,
                preset_context=preset_context,
                preset_pack_constraints=dict(preset_pack_constraints or {}),
                controlled_trip_identity=controlled_trip_identity or {},
                route_decision=route_decision or {},
                model_versions=_configured_model_versions(),
            )

        effective_plan_gate_enabled = (
            bool(plan_gate_enabled)
            if plan_gate_enabled is not None
            else bool(
                getattr(self, "_checkpointer", None) is not None
                and get_settings().run_control.plan_gate_enabled
            )
        )
        config = {
            "recursion_limit": GRAPH_RECURSION_LIMIT,
            "configurable": {
                "thread_id": effective_run_id,
                "plan_gate_enabled": effective_plan_gate_enabled,
                "cost_ledger_store": get_cost_ledger_store(),
                "usage_recorder": get_usage_recorder(),
                "tool_audit_store": get_tool_audit_store(),
                "delivery_bundle_store": self._delivery_bundle_store,
                "trip_run_store": self._trip_run_store,
            },
        }
        if stream_queue is not None:
            config["configurable"]["stream_queue"] = stream_queue

        last_values = None
        interrupted = False

        async def lifecycle_sink(payload: Dict[str, Any]) -> None:
            if stream_queue is not None:
                await stream_queue.put(("node_lifecycle", payload))

        with run_attribution(
            effective_run_id,
            lifecycle_sink=lifecycle_sink if stream_queue is not None else None,
        ):
            async for mode, chunk in self._graph.astream(
                graph_input,
                stream_mode=["updates", "values"],
                config=config,
                durability="sync",
            ):
                if mode == "updates":
                    if isinstance(chunk, dict) and "__interrupt__" in chunk:
                        interrupted = True
                    yield chunk
                else:
                    if isinstance(chunk, dict) and "__interrupt__" in chunk:
                        filtered = dict(chunk)
                        filtered.pop("__interrupt__", None)
                        last_values = filtered
                        interrupted = True
                    else:
                        last_values = chunk
                    if stream_queue is not None and isinstance(last_values, dict):
                        await stream_queue.put(("state_snapshot", last_values))
        if last_values is not None and not interrupted:
            yield {"__final_state__": last_values}
