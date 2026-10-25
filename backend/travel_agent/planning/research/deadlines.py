from __future__ import annotations

from typing import Any, Sequence

from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.itinerary.connectors import LocalConnectorGap
from travel_agent.runtime.deadlines import DeadlineObservation, observe_run_deadline


def _observe_deadline(
    state: TravelAgentState,
) -> tuple[Any | None, DeadlineObservation | None]:
    deadline = state.run_deadline
    if deadline is None:
        return None, None
    return observe_run_deadline(deadline)


def _research_closeout_can_skip_connector_pass(
    state: TravelAgentState,
    observation: Any | None,
) -> bool:
    """Whether closeout has no deterministic skeleton work left to perform."""

    return bool(
        observation is not None
        and observation.research_closed
        and state.placement_skeleton is None
    )


def _closeout_blocks_targeted_round(
    observation: DeadlineObservation | None,
    connector_gaps: Sequence[LocalConnectorGap],
) -> bool:
    """Close discovery at closeout while preserving exact composition lookups."""

    return bool(
        observation is not None
        and observation.research_closed
        and (observation.composition_closed or not connector_gaps)
    )
