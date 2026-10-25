from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class PreparationRejection(str, Enum):
    EMPTY_MESSAGE = "empty_message"
    ROUTE_UNAVAILABLE = "route_unavailable"
    REFINEMENT_REQUIRES_RUN = "refinement_requires_run"
    GATE_REQUIRES_RUN = "gate_requires_run"
    GATE_REQUIRES_CHECKPOINT = "gate_requires_checkpoint"
    RUN_NOT_FOUND = "run_not_found"
    IDENTITY_LOCKED = "identity_locked"
    RUN_STATUS_NOT_CONTINUABLE = "run_status_not_continuable"
    GATE_DECISION_REQUIRED = "gate_decision_required"
    GATE_NODE_REQUIRED = "gate_node_required"
    PROJECTION_FAILURE = "projection_failure"
    RESUME_REQUIRES_CHECKPOINT = "resume_requires_checkpoint"
    RUN_NOT_RESUMABLE = "run_not_resumable"
    CHECKPOINT_CONTRACT_MISMATCH = "checkpoint_contract_mismatch"
    CHECKPOINT_NOT_FOUND = "checkpoint_not_found"
    RESUME_STATUS_RACE = "resume_status_race"
    GATE_STATUS_NOT_CONTINUABLE = "gate_status_not_continuable"


@dataclass
class PreparationRefused(Exception):
    reason: PreparationRejection
    current_status: str | None = None
    explanation: str | None = None


class SessionAccessDenied(Exception):
    pass


class SessionHistoryUnavailable(Exception):
    pass


class PresetNotFound(Exception):
    pass


class PresetUnavailable(Exception):
    pass


class ExecutionAlreadyOwned(Exception):
    pass
