from __future__ import annotations

from typing import Mapping, Sequence

from travel_agent.entities.provider_evidence import ProviderRouteLegScope
from travel_agent.entities.state import TravelAgentState
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.requirements import _destination_country_codes
from travel_agent.services.candidate_admission import (
    DETERMINISTIC_IDENTITY_VERDICT_FIELD_PATHS,
)

_ALTERNATIVE_TOOLS = {
    "destination_researcher": [
        "global_place_search",
        "maps_text_search",
        "tavily_search",
        "free_web_search",
        "brave_web_search",
        "firecrawl_search",
    ],
    "accommodation_researcher": [
        "global_place_search",
        "maps_text_search",
        "maps_search_detail",
        "tavily_search",
        "free_web_search",
        "brave_web_search",
    ],
    "transport_researcher": [
        "global_route_search",
        "maps_direction_transit_integrated",
        "maps_direction_walking",
        "maps_direction_driving",
        "free_web_search",
        "get-interline-tickets",
        "get-tickets",
    ],
}


_LOCAL_ONLY_ROUTE_TOOLS = frozenset(
    {
        "global_route_search",
        "maps_direction_transit_integrated",
        "maps_direction_walking",
        "maps_direction_driving",
    }
)


_LONG_DISTANCE_ROUTE_TOOLS = [
    "get-tickets",
    "get-interline-tickets",
    "search_flights",
]


def _recommended_tools(
    state: TravelAgentState,
    worker: str,
    excluded_tools: set[str],
    domain: ResearchDomain,
) -> list[str]:
    tools = [tool for tool in _ALTERNATIVE_TOOLS[worker] if tool not in excluded_tools]
    if worker == "transport_researcher":
        if domain != ResearchDomain.LONG_DISTANCE_TRANSPORT:
            return tools
        return [
            tool
            for tool in dict.fromkeys(
                [*_LONG_DISTANCE_ROUTE_TOOLS, *_ALTERNATIVE_TOOLS[worker]]
            )
            if tool not in excluded_tools and tool not in _LOCAL_ONLY_ROUTE_TOOLS
        ]
    country_codes = set(_destination_country_codes(state).values())
    if country_codes and country_codes != {"cn"}:
        tools = [
            tool
            for tool in tools
            if tool not in {"maps_text_search", "maps_search_detail"}
        ]
    return tools


_LONG_DISTANCE_EVIDENCE_REQUIREMENT = (
    "必须使用真实外部 Provider 结果，"
    "具体到可核验的出发/到达端点与时间。实时班次不可得时明确保留缺口，"
    "禁止用市内路线、空路线或常识描述代替。"
)


def _long_distance_leg_clause(leg: ProviderRouteLegScope) -> str:
    """Spell out one exact long-distance responsibility, field by field."""
    return (
        f"leg_role={leg.leg_role}，"
        f"from_place_id={leg.from_place_id}，"
        f"to_place_id={leg.to_place_id}，"
        f"service_date={leg.service_date.isoformat()}，"
        f"cross_day_required={str(leg.cross_day_required).lower()}"
    )


def _long_distance_instruction(legs: Sequence[ProviderRouteLegScope]) -> str:
    """Name every long-distance responsibility this one research round owes."""
    if not legs:
        return ""
    if len(legs) == 1:
        return (
            " 本轮只补一个精确 long-distance 责任："
            f"{_long_distance_leg_clause(legs[0])}。"
            f"{_LONG_DISTANCE_EVIDENCE_REQUIREMENT}"
        )
    enumerated = "；".join(
        f"[{index}] {_long_distance_leg_clause(leg)}"
        for index, leg in enumerate(legs, start=1)
    )
    return (
        f" 本轮必须补齐 {len(legs)} 个精确 long-distance 责任：{enumerated}。"
        f"{_LONG_DISTANCE_EVIDENCE_REQUIREMENT}"
        "每一条责任都要单独给出结果，不得只覆盖其中一条。"
    )


def _deterministically_rejected_candidate_ids(
    catalog: RecommendationCatalog,
    packet_workers: Mapping[str, str],
    worker: str,
) -> list[str]:
    """One worker's candidates whose rejection no further research can change."""
    return sorted(
        {
            admission.candidate_id
            for admission in catalog.admission_results
            if admission.status == "insufficient_for_admission"
            and packet_workers.get(admission.candidate_id) == worker
            and DETERMINISTIC_IDENTITY_VERDICT_FIELD_PATHS.intersection(
                admission.missing_field_paths
            )
        }
    )
