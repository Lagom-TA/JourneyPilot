from __future__ import annotations

from travel_agent.planning.requirements.identity_contracts import ControlledTripIdentity
from travel_agent.planning.requirements.intent_contracts import CategoryIntentValue
from travel_agent.planning.requirements.intent_contracts import IntentItem
from travel_agent.planning.requirements.intent_contracts import IntentKind
from travel_agent.planning.requirements.intent_contracts import IntentStrength
from travel_agent.planning.requirements.intent_contracts import IntentTarget
from travel_agent.planning.requirements.intent_contracts import canonical_json_hash
from travel_agent.planning.requirements.product_policy import (
    style_selected_physical_candidate_kinds,
)
from travel_agent.planning.requirements.request_contracts import RequestContract
from travel_agent.planning.requirements.route_legs import (
    build_required_long_distance_legs,
)
from travel_agent.planning.research.brief_contracts import DomainResearchObjective
from travel_agent.planning.research.brief_contracts import ResearchBriefV2
from travel_agent.planning.research.brief_contracts import SuccessCriterion
from travel_agent.planning.research.domains import ResearchDomain
from typing import List
from typing import Mapping


RESEARCH_BRIEF_POLICY_VERSION = "research_brief_projection.v3"


_TARGET_DOMAIN = {
    IntentTarget.VISIT: ResearchDomain.VISIT,
    IntentTarget.DINING: ResearchDomain.DINING,
    IntentTarget.LODGING: ResearchDomain.LODGING,
    IntentTarget.LOCAL_TRANSPORT: ResearchDomain.LOCAL_TRANSPORT,
    IntentTarget.LONG_DISTANCE_TRANSPORT: ResearchDomain.LONG_DISTANCE_TRANSPORT,
}


def build_research_brief(
    request_contract: RequestContract,
    controlled_identity: Mapping[str, object],
) -> ResearchBriefV2:
    identity = ControlledTripIdentity.model_validate(controlled_identity)
    active = request_contract.intent_spec.active_items
    hard_ids = [
        item.intent_id for item in active if item.strength is IntentStrength.HARD
    ]
    soft_ids = [
        item.intent_id for item in active if item.strength is IntentStrength.SOFT
    ]

    domains = {
        _TARGET_DOMAIN[item.target]
        for item in active
        if item.target in _TARGET_DOMAIN
        and item.kind is not IntentKind.MUST_EXCLUDE
        and "research" in item.impact_stages
    }
    for candidate_kind in style_selected_physical_candidate_kinds(controlled_identity):
        if candidate_kind == "visit":
            domains.add(ResearchDomain.VISIT)
        elif candidate_kind == "dining":
            domains.add(ResearchDomain.DINING)
    if identity.duration_days > 1:
        domains.add(ResearchDomain.LODGING)
    if build_required_long_distance_legs(
        controlled_identity, cross_day_return_required=False
    ):
        domains.add(ResearchDomain.LONG_DISTANCE_TRANSPORT)

    objectives: List[DomainResearchObjective] = []
    for domain in sorted(domains, key=lambda item: item.value):
        scoped = [
            item
            for item in active
            if _TARGET_DOMAIN.get(item.target) == domain
            or (domain is ResearchDomain.VISIT and item.target is IntentTarget.TRIP)
        ]
        must = [
            item.intent_id for item in scoped if item.strength is IntentStrength.HARD
        ]
        optional = [
            item.intent_id
            for item in scoped
            if item.strength is not IntentStrength.HARD
        ]
        excluded = [
            value
            for item in scoped
            if item.kind is IntentKind.MUST_EXCLUDE
            for value in _category_values(item)
        ]
        criteria = [_criterion(item) for item in scoped]
        objective_material = {
            "generation_id": request_contract.generation_id,
            "domain": domain.value,
            "must": must,
            "optional": optional,
            "excluded": excluded,
        }
        objectives.append(
            DomainResearchObjective(
                objective_id="objective_"
                + canonical_json_hash(objective_material)[:24],
                domain=domain,
                summary=_domain_summary(domain, scoped),
                must_cover_intent_ids=must,
                optional_intent_ids=optional,
                excluded_categories=excluded,
                success_criteria=criteria,
            )
        )
    delivery_requirements = [
        item.public_summary
        for item in active
        if item.target is IntentTarget.DELIVERY or "projection" in item.impact_stages
    ]
    material = {
        "generation_id": request_contract.generation_id,
        "identity_revision": request_contract.controlled_trip_identity_revision,
        "intent_revision": request_contract.intent_spec.revision,
        "constraint_revision": request_contract.constraint_pack_revision,
        "objective_summary": request_contract.intent_spec.objective_summary,
        "identity": identity.model_dump(mode="json"),
        "objectives": [item.model_dump(mode="json") for item in objectives],
        "delivery_requirements": delivery_requirements,
        "hard_intent_ids": hard_ids,
        "soft_intent_ids": soft_ids,
    }
    content_hash = canonical_json_hash(material)
    return ResearchBriefV2(
        brief_id=f"brief_{content_hash[:24]}",
        generation_id=request_contract.generation_id,
        controlled_trip_identity_revision=request_contract.controlled_trip_identity_revision,
        intent_spec_revision=request_contract.intent_spec.revision,
        constraint_pack_revision=request_contract.constraint_pack_revision,
        objective_summary=request_contract.intent_spec.objective_summary,
        controlled_trip_identity=identity,
        domain_objectives=objectives,
        delivery_requirements=delivery_requirements,
        hard_intent_ids=hard_ids,
        soft_intent_ids=soft_ids,
        content_hash=content_hash,
    )


def _category_values(item: IntentItem) -> List[str]:
    return (
        list(item.value.categories)
        if isinstance(item.value, CategoryIntentValue)
        else [item.public_summary]
    )


def _criterion(item: IntentItem) -> SuccessCriterion:
    material = {"intent_id": item.intent_id, "summary": item.public_summary}
    return SuccessCriterion(
        criterion_id="criterion_" + canonical_json_hash(material)[:24],
        description=item.public_summary,
        verification=item.verification_mode.value,
        intent_ids=[item.intent_id],
    )


def _domain_summary(domain: ResearchDomain, scoped: List[IntentItem]) -> str:
    labels = [item.public_summary for item in scoped]
    base = {
        ResearchDomain.VISIT: "查明符合主题和限制的具体游览候选",
        ResearchDomain.DINING: "查明符合用餐要求的具体餐饮候选",
        ResearchDomain.LODGING: "查明覆盖过夜责任的住宿候选",
        ResearchDomain.LOCAL_TRANSPORT: "查明行程内连接段的可执行交通",
        ResearchDomain.LONG_DISTANCE_TRANSPORT: "查明出发、返程和跨城交通责任",
    }[domain]
    return (base + ("；" + "；".join(labels) if labels else ""))[:500]
