"""Planning research fallback policy."""

from __future__ import annotations

from dataclasses import dataclass
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.query_contracts import ResearchQuery
from travel_agent.runtime.budget import RunBudgetExhausted
from travel_agent.runtime.budget import current_budget_ledger
from travel_agent.runtime.operations import ModelWindowClosed
from travel_agent.runtime.operations import remaining_model_seconds
from typing import Mapping


FALLBACK_QUERY_POLICY_VERSION = "fallback_query_policy.v3"


_FALLBACK_CATEGORY_TOKENS: Mapping[ResearchDomain, tuple[str, ...]] = {
    ResearchDomain.VISIT: (),
    ResearchDomain.DINING: ("restaurant", "餐厅", "餐馆"),
    ResearchDomain.LODGING: ("hotel", "酒店", "宾馆"),
}


def runtime_fallback_capacity() -> tuple[bool, bool]:
    try:
        remaining_model_seconds("research.generic_fallback")
        research_window_open = True
    except ModelWindowClosed:
        research_window_open = False
    ledger = current_budget_ledger()
    try:
        if ledger is not None:
            ledger.guard("research.generic_fallback", tool_calls=1)
        run_budget_available = True
    except RunBudgetExhausted:
        run_budget_available = False
    return research_window_open, run_budget_available


@dataclass(frozen=True)
class FallbackQueryPolicy:
    policy_version: str = FALLBACK_QUERY_POLICY_VERSION

    def is_allowed(
        self,
        query: ResearchQuery,
        *,
        executed_query_ids: set[str],
        research_window_open: bool,
        run_budget_available: bool,
    ) -> bool:
        """A generic fallback query runs once its prerequisites ran, within budget."""
        if query.query_kind.value != "generic_fallback":
            return False
        return (
            set(query.fallback_after_query_ids) <= executed_query_ids
            and research_window_open
            and run_budget_available
        )


def fallback_template(
    domain: ResearchDomain,
    destination_name: str,
    excluded_categories: list[str],
) -> str | None:
    excluded = " ".join(excluded_categories).casefold()
    templates: Mapping[ResearchDomain, str] = {
        ResearchDomain.VISIT: (
            f"{destination_name} official visitor guide local experiences specific places"
        ),
        ResearchDomain.DINING: (f"restaurant in {destination_name}"),
        ResearchDomain.LODGING: (f"hotel in {destination_name}"),
    }
    template = templates.get(domain)
    if template is None:
        return None
    if any(token.casefold() in excluded for token in _FALLBACK_CATEGORY_TOKENS[domain]):
        return None
    return template
