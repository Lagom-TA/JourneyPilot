from __future__ import annotations

from travel_agent.planning.requirements.intent_contracts import IntentItem
from travel_agent.planning.requirements.intent_contracts import IntentKind
from travel_agent.planning.requirements.intent_contracts import IntentStrength
from travel_agent.planning.requirements.intent_contracts import IntentTarget
from travel_agent.planning.requirements.intent_contracts import canonical_json_hash
from travel_agent.planning.requirements.request_contracts import RequestContract
from travel_agent.planning.research.brief_builder import _TARGET_DOMAIN
from travel_agent.planning.research.brief_builder import _criterion
from travel_agent.planning.research.brief_contracts import DomainResearchObjective
from travel_agent.planning.research.brief_contracts import ResearchBriefV2
from travel_agent.planning.research.capability_contracts import AgentAssignmentContract
from travel_agent.planning.research.capability_contracts import AgentName
from travel_agent.planning.research.capability_contracts import CapabilityPlan
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.query_contracts import ResearchQueryPlan
from typing import Dict
from typing import Iterable
from typing import List


CAPABILITY_PLAN_POLICY_VERSION = "capability_plan.v2"


_DOMAIN_OWNER: Dict[ResearchDomain, AgentName] = {
    ResearchDomain.VISIT: "destination_researcher",
    ResearchDomain.DINING: "destination_researcher",
    ResearchDomain.LODGING: "accommodation_researcher",
    ResearchDomain.LOCAL_TRANSPORT: "transport_researcher",
    ResearchDomain.LONG_DISTANCE_TRANSPORT: "transport_researcher",
}


_TARGET_OWNER: Dict[IntentTarget, AgentName] = {
    IntentTarget.TRIP: "itinerary_planner",
    IntentTarget.VISIT: "destination_researcher",
    IntentTarget.DINING: "destination_researcher",
    IntentTarget.LODGING: "accommodation_researcher",
    IntentTarget.LOCAL_TRANSPORT: "transport_researcher",
    IntentTarget.LONG_DISTANCE_TRANSPORT: "transport_researcher",
    IntentTarget.ITINERARY: "itinerary_planner",
    IntentTarget.DELIVERY: "itinerary_planner",
}


_TOOLS: Dict[AgentName, List[str]] = {
    "destination_researcher": ["nominatim_place_search", "search_web"],
    "transport_researcher": ["global_route_search", "rail_12306_search"],
    "accommodation_researcher": ["nominatim_place_search", "search_web"],
    "itinerary_planner": [],
}


def _intent_owner(item: IntentItem, research_domains: set[ResearchDomain]) -> AgentName:
    if "research" not in item.impact_stages:
        return "itinerary_planner"
    if (
        item.kind is IntentKind.MUST_EXCLUDE
        and _TARGET_DOMAIN.get(item.target) not in research_domains
    ):
        return "itinerary_planner"
    return _TARGET_OWNER[item.target]


def build_capability_plan(
    *,
    request_contract: RequestContract,
    brief: ResearchBriefV2,
    plan_revision: int,
    research_query_plan: ResearchQueryPlan,
) -> CapabilityPlan:
    active = request_contract.intent_spec.active_items
    agents: set[AgentName] = {
        _DOMAIN_OWNER[objective.domain] for objective in brief.domain_objectives
    }
    research_domains = {objective.domain for objective in brief.domain_objectives}
    agents.update(_intent_owner(item, research_domains) for item in active)
    agents.add("itinerary_planner")
    assignments: Dict[str, AgentAssignmentContract] = {}

    order: List[List[AgentName]] = []
    if "destination_researcher" in agents:
        order.append(["destination_researcher"])
    middle = [
        agent
        for agent in ("transport_researcher", "accommodation_researcher")
        if agent in agents
    ]
    if middle:
        order.append(middle)
    order.append(["itinerary_planner"])

    objective_by_agent: Dict[AgentName, List[DomainResearchObjective]] = {
        agent: [] for agent in agents
    }
    for objective in brief.domain_objectives:
        objective_by_agent[_DOMAIN_OWNER[objective.domain]].append(objective)

    assignment_ids = {
        agent: "assignment_"
        + canonical_json_hash({"generation_id": brief.generation_id, "agent": agent})[
            :24
        ]
        for agent in agents
    }
    for agent in sorted(agents):
        owned_intents = [
            item for item in active if _intent_owner(item, research_domains) == agent
        ]
        objectives = objective_by_agent.get(agent, [])
        upstream = []
        if (
            agent in {"transport_researcher", "accommodation_researcher"}
            and "destination_researcher" in agents
        ):
            upstream.append(assignment_ids["destination_researcher"])
        if agent == "itinerary_planner":
            upstream.extend(
                assignment_ids[owner]
                for owner in (
                    "destination_researcher",
                    "transport_researcher",
                    "accommodation_researcher",
                )
                if owner in agents
            )
        assignments[agent] = AgentAssignmentContract(
            assignment_id=assignment_ids[agent],
            generation_id=brief.generation_id,
            agent_name=agent,
            objective=_assignment_objective(agent, objectives, owned_intents),
            must_cover_intent_ids=[
                item.intent_id
                for item in owned_intents
                if item.strength is IntentStrength.HARD
            ],
            optional_intent_ids=[
                item.intent_id
                for item in owned_intents
                if item.strength is not IntentStrength.HARD
            ],
            research_objective_ids=[item.objective_id for item in objectives],
            required_candidate_kinds=_candidate_kinds(objectives),
            excluded_categories=list(
                dict.fromkeys(
                    value
                    for objective in objectives
                    for value in objective.excluded_categories
                )
            ),
            research_query_ids=[
                query.query_id
                for query in research_query_plan.queries
                if query.domain in {objective.domain for objective in objectives}
            ],
            success_criteria=[
                criterion
                for objective in objectives
                for criterion in objective.success_criteria
            ]
            + (
                [_criterion(item) for item in owned_intents]
                if agent == "itinerary_planner"
                else []
            ),
            recommended_tools=_TOOLS[agent],
            upstream_assignment_ids=upstream,
            intent_spec_revision=request_contract.intent_spec.revision,
            constraint_pack_revision=request_contract.constraint_pack_revision,
        )

    material = {
        "generation_id": brief.generation_id,
        "plan_revision": plan_revision,
        "intent_spec_revision": request_contract.intent_spec.revision,
        "constraint_pack_revision": request_contract.constraint_pack_revision,
        "execution_plan": order,
        "assignments": {
            key: value.model_dump(mode="json") for key, value in assignments.items()
        },
    }
    content_hash = canonical_json_hash(material)
    return CapabilityPlan(
        capability_plan_id=f"capability_plan_{content_hash[:24]}",
        generation_id=brief.generation_id,
        plan_revision=plan_revision,
        intent_spec_revision=request_contract.intent_spec.revision,
        constraint_pack_revision=request_contract.constraint_pack_revision,
        execution_plan=order,
        assignments=assignments,
        content_hash=content_hash,
    )


def _assignment_objective(
    agent: AgentName,
    objectives: List[DomainResearchObjective],
    intents: List[IntentItem],
) -> str:
    if agent == "itinerary_planner":
        labels = [item.public_summary for item in intents]
        return (
            "结合候选目录与用户要求组合可执行按天行程"
            + ("；" + "；".join(labels) if labels else "")
        )[:1000]
    return "；".join(item.summary for item in objectives)[:1000]


def _candidate_kinds(objectives: Iterable[DomainResearchObjective]) -> List[str]:
    mapping = {
        ResearchDomain.VISIT: "visit",
        ResearchDomain.DINING: "dining",
        ResearchDomain.LODGING: "lodging",
        ResearchDomain.LOCAL_TRANSPORT: "transport",
        ResearchDomain.LONG_DISTANCE_TRANSPORT: "transport",
    }
    return list(dict.fromkeys(mapping[item.domain] for item in objectives))
