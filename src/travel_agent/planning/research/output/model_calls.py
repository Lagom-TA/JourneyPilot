"""Research packet model calls responsibilities."""

from __future__ import annotations

import asyncio
from typing import Any, Mapping, Sequence

from travel_agent.planning.research.provider_failure import classify_provider_failure

from .policy import ResearchPacketOutputError

_PACKET_MODEL_CALL_TIMEOUT_SECONDS = 120.0


def _is_transient_model_call_failure(error: BaseException) -> bool:
    "Classify a repair model call exactly as the gates classify a Provider."
    return classify_provider_failure(str(error)).category == "transient"


async def _bounded_packet_model_call(
    llm: Any,
    messages: Sequence[Mapping[str, Any]],
    **kwargs: Any,
) -> str:
    "Cap the whole packet-repair operation to the finalization timeout."
    # Bound transport retries inside the same whole-operation timeout.
    timeout = _PACKET_MODEL_CALL_TIMEOUT_SECONDS
    call = llm.ainvoke(list(messages), timeout=timeout, **kwargs)
    try:
        return await asyncio.wait_for(call, timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise ResearchPacketOutputError(
            f"packet model operation exceeded configured timeout ({timeout:g}s)"
        ) from exc
