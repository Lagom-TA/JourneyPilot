from __future__ import annotations

from typing import Any, Dict

from travel_agent.planning.research.provider_assignments import (
    parse_provider_evidence_assignments,
)
from travel_agent.planning.state import TravelAgentState


_NODE_NAME = "transport_researcher"


def transport_provider_assignments(assignment: Dict[str, Any], state: TravelAgentState):
    return parse_provider_evidence_assignments(
        assignment,
        expected_worker=_NODE_NAME,
        expected_run_id=state.run_id,
    )
