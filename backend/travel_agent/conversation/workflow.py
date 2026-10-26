"""快速模式工作流封装。"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional

from travel_agent.conversation.graph import get_fast_graph
from travel_agent.conversation.messages import build_messages
from travel_agent.planning.state import TravelAgentState
from travel_agent.runtime.context import run_attribution
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from travel_agent.runtime.run_contracts import generate_trip_run_id


class FastAnswerWorkflow:
    """快速模式工作流封装类。"""

    def __init__(self) -> None:
        self._graph = get_fast_graph()

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
        route_decision: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行快速模式工作流。"""
        import datetime

        messages = build_messages(conversation_history, user_message)

        initial_state = TravelAgentState(
            messages=messages,
            session_id=session_id,
            user_id=user_id,
            selected_mcp_servers=selected_mcp_servers or [],
            user_query=user_message,
            run_id=run_id or generate_trip_run_id(),
            current_time=current_time
            or datetime.datetime.now().strftime("%Y-%m-%d %A %H:%M:%S"),
            session_anchor=session_anchor,
            session_compressed=session_compressed,
            preset_context=preset_context,
            preset_pack_constraints=dict(preset_pack_constraints or {}),
            route_decision=route_decision or {},
        )

        config = {"configurable": {"thread_id": initial_state.run_id}}
        if stream_queue is not None:
            config["configurable"]["stream_queue"] = stream_queue

        last_values = None

        async def lifecycle_sink(payload: Dict[str, Any]) -> None:
            if stream_queue is not None:
                await stream_queue.put(("node_lifecycle", payload))

        with run_attribution(
            initial_state.run_id,
            lifecycle_sink=lifecycle_sink if stream_queue is not None else None,
        ):
            async for mode, chunk in self._graph.astream(
                initial_state, stream_mode=["updates", "values"], config=config
            ):
                if mode == "updates":
                    yield chunk
                else:
                    last_values = chunk
                    if stream_queue is not None and isinstance(last_values, dict):
                        await stream_queue.put(("state_snapshot", last_values))
        if last_values is not None:
            yield {"__final_state__": last_values}
