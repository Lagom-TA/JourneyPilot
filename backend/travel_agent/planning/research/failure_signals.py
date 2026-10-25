from __future__ import annotations

import re
from dataclasses import dataclass

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.assignments import strip_round_suffix
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.research.provider_failure import (
    classify_provider_failure,
    is_provider_or_model_failure,
)


@dataclass(frozen=True)
class ProviderFailureSignal:
    tool_name: str
    signature: str
    reason_code: str
    category: str


def _failure_signals(packet: ResearchPacket | None) -> list[ProviderFailureSignal]:
    """Classify the provider failures the *server* compiled for this packet."""
    if packet is None:
        return []
    signals: list[ProviderFailureSignal] = []
    for source in packet.source_records:
        if (
            source.source_kind != "external_tool"
            or source.lifecycle_status != "rejected"
        ):
            continue
        snapshot = source.snapshot
        error = snapshot.get("error") or snapshot.get("degradation_reason")
        fallback_from = snapshot.get("fallback_from")
        error_tool = re.search(
            r"(?:executing\s+)?tool\s+([A-Za-z0-9_-]+)",
            str(error or ""),
            flags=re.IGNORECASE,
        )
        tool_name = (
            str(fallback_from).strip()
            if isinstance(fallback_from, str) and fallback_from.strip()
            else error_tool.group(1)
            if error_tool
            else source.title.split(" ", 1)[0].strip()
        )
        normalized_tool = tool_name.strip().casefold()
        if not re.fullmatch(r"[a-z0-9_-]+", normalized_tool):
            normalized_tool = "unknown_tool"
        classification = classify_provider_failure(error)
        signals.append(
            ProviderFailureSignal(
                tool_name=normalized_tool,
                signature=(
                    f"{classification.category}:{normalized_tool}|"
                    f"provider:{str(source.provider_name or 'unknown').casefold()}|"
                    f"reason:{classification.reason_code}"
                ),
                reason_code=classification.reason_code,
                category=classification.category,
            )
        )
    return list({signal.signature: signal for signal in signals}.values())


def _last_error_is_unambiguously_scoped_to_worker(
    state: TravelAgentState,
    worker: str,
) -> bool:
    """Use the global error only when exactly this base worker failed."""
    failed_workers = {
        strip_round_suffix(agent_key)
        for agent_key, status in (state.agent_status or {}).items()
        if str(status).casefold() == "failed"
    }
    return failed_workers == {worker}


def _worker_failure_signals(
    state: TravelAgentState,
    *,
    packet: ResearchPacket | None,
    worker: str,
) -> list[ProviderFailureSignal]:
    """Classify how one worker's providers failed on its most recent round."""
    signals = _failure_signals(packet)
    if (
        not signals
        and state.last_error
        and _last_error_is_unambiguously_scoped_to_worker(state, worker)
        and is_provider_or_model_failure(state.last_error)
    ):
        classification = classify_provider_failure(str(state.last_error))
        signals = [
            ProviderFailureSignal(
                tool_name=worker,
                signature=(
                    f"{classification.category}:{worker}|provider:unknown|"
                    f"reason:{classification.reason_code}"
                ),
                reason_code=classification.reason_code,
                category=classification.category,
            )
        ]
    return signals
