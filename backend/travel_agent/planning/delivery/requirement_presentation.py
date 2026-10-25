"""Planning delivery requirement presentation."""

from __future__ import annotations

from travel_agent.planning.requirements.coverage_contracts import (
    IntentCoverageStatus,
    IntentCoverageItem,
)
from travel_agent.planning.requirements.snapshot_contracts import (
    IntentContractRequirement,
)


def public_requirement_explanation(
    requirement: IntentContractRequirement,
    coverage: "IntentCoverageItem",
) -> str:
    """Say an unresolved requirement identically in every delivery surface."""
    if coverage.status is IntentCoverageStatus.SATISFIED:
        return coverage.public_explanation
    labels = {
        IntentCoverageStatus.PARTIALLY_SATISFIED: "仅部分满足",
        IntentCoverageStatus.UNSATISFIED: "尚未满足",
        IntentCoverageStatus.UNVERIFIABLE: "尚未核实",
        IntentCoverageStatus.UNSUPPORTED: "本次方案尚未支持",
        IntentCoverageStatus.CONFLICTED: "要求存在冲突",
    }
    return f"{labels[coverage.status]}：{requirement.public_summary}"
