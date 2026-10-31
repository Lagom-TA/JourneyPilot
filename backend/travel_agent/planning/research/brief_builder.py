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
    required_route_names,
)
from travel_agent.planning.research.brief_contracts import DomainResearchObjective
from travel_agent.planning.research.brief_contracts import ResearchBriefV2
from travel_agent.planning.research.brief_contracts import SuccessCriterion
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.research_plan_validation import (
    validate_research_plan_for_contract,
)
from typing import List
from typing import Mapping


RESEARCH_BRIEF_POLICY_VERSION = "research_brief_projection.v5"


def _party_public_text(identity: ControlledTripIdentity) -> str:
    party = f"{identity.party.adults} 位成人"
    if identity.party.children:
        party += f"、{identity.party.children} 位儿童"
    if identity.party.elderly_companions:
        party += "、长辈同行"
    if identity.party.accessibility_required:
        party += "、需要无障碍安排"
    return party


def _style_public_text(identity: ControlledTripIdentity) -> str:
    style = identity.style.primary
    if identity.style.secondary_interests:
        style += f"（{'、'.join(identity.style.secondary_interests)}）"
    return style


def identity_route_text(identity: ControlledTripIdentity) -> str:
    """实际长途链路，例如 深圳市 → 北京市 → 上海市 → 深圳市。"""

    return " → ".join(required_route_names(identity.model_dump(mode="json")))


def identity_domain_scope(identity: ControlledTripIdentity) -> str:
    """可用于研究摘要的城市、日期、同行人与风格范围。"""

    destinations = "、".join(place.name for place in identity.destinations)
    return (
        f"{destinations}（{identity.start_date.isoformat()} 至 "
        f"{identity.end_date.isoformat()}，{_party_public_text(identity)}，"
        f"{_style_public_text(identity)}）"
    )


def identity_itinerary_scope(identity: ControlledTripIdentity) -> str:
    """行程规划任务里的城市顺序、日期、同行人与风格。"""

    destinations = "、".join(place.name for place in identity.destinations)
    return (
        f"{destinations} {identity.start_date.isoformat()} 至 "
        f"{identity.end_date.isoformat()}（{_party_public_text(identity)}，"
        f"{_style_public_text(identity)}）"
    )


_DOMAIN_LABELS = {
    ResearchDomain.VISIT: "景点与体验",
    ResearchDomain.DINING: "餐饮",
    ResearchDomain.LODGING: "住宿",
    ResearchDomain.LOCAL_TRANSPORT: "市内交通",
    ResearchDomain.LONG_DISTANCE_TRANSPORT: "跨城交通",
}


_TARGET_DOMAIN = {
    IntentTarget.VISIT: ResearchDomain.VISIT,
    IntentTarget.DINING: ResearchDomain.DINING,
    IntentTarget.LODGING: ResearchDomain.LODGING,
    IntentTarget.LOCAL_TRANSPORT: ResearchDomain.LOCAL_TRANSPORT,
    IntentTarget.LONG_DISTANCE_TRANSPORT: ResearchDomain.LONG_DISTANCE_TRANSPORT,
}


# 这些类别代表住宿研究领域本身；带限定词的子类（“连锁酒店”“某家酒店”）
# 只在候选阶段排除，不能关掉多日行程的默认住宿调研。
_DOMAIN_WIDE_EXCLUDED_CATEGORIES = {
    ResearchDomain.LODGING: frozenset(
        {
            "住宿",
            "酒店",
            "宾馆",
            "旅馆",
            "hotel",
            "hotels",
            "lodging",
            "lodgings",
            "accommodation",
            "accommodations",
        }
    ),
}


def required_research_domains(
    request_contract: RequestContract,
    controlled_identity: Mapping[str, object],
) -> set[ResearchDomain]:
    identity = ControlledTripIdentity.model_validate(controlled_identity)
    active = request_contract.intent_spec.active_items
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
    if identity.duration_days > 1 and _default_lodging_research_allowed(active):
        domains.add(ResearchDomain.LODGING)
    if build_required_long_distance_legs(
        controlled_identity, cross_day_return_required=False
    ):
        domains.add(ResearchDomain.LONG_DISTANCE_TRANSPORT)
    return domains


def build_research_brief(
    request_contract: RequestContract,
    controlled_identity: Mapping[str, object],
    *,
    candidate_selection=None,
    confirmation_digest: str | None = None,
) -> ResearchBriefV2:
    identity = ControlledTripIdentity.model_validate(controlled_identity)
    active = request_contract.intent_spec.active_items
    hard_ids = [
        item.intent_id for item in active if item.strength is IntentStrength.HARD
    ]
    soft_ids = [
        item.intent_id for item in active if item.strength is IntentStrength.SOFT
    ]

    domains = required_research_domains(request_contract, controlled_identity)
    model_domains, _plan_rejection = validate_research_plan_for_contract(
        request_contract.research_plan,
        identity=identity,
        active_items=active,
        constraint_pack=request_contract.constraint_pack,
        required_domains=domains,
        clause_texts=[item.source_text for item in request_contract.clause_ledger],
        candidate_selection=candidate_selection,
        confirmation_digest=confirmation_digest,
    )
    plan_source = "model" if model_domains is not None else "deterministic_fallback"
    # 确定性投影只保证同一输入得到同一范围；旧文本校验本身不证明语义授权。
    plan_summary = (
        "按本次需求研究"
        + "、".join(_DOMAIN_LABELS[domain] for domain in sorted(domains, key=lambda item: item.value))
        + f"，共 {len(domains)} 个方向；关注点与检索词来自本次需求结构化模型，"
        "已按受控身份、硬约束和排除项校验。"
        if model_domains is not None
        else ""
    )
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
        model_domain = (
            model_domains.get(domain) if model_domains is not None else None
        )
        objectives.append(
            DomainResearchObjective(
                objective_id="objective_"
                + canonical_json_hash(objective_material)[:24],
                domain=domain,
                summary=_domain_summary(domain, scoped, model_domain, identity),
                must_cover_intent_ids=must,
                optional_intent_ids=optional,
                excluded_categories=excluded,
                search_terms=(
                    list(model_domain.search_terms)
                    if model_domain is not None
                    else []
                ),
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
        "research_plan_summary": plan_summary,
        "research_plan_source": plan_source,
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
        research_plan_summary=plan_summary,
        research_plan_source=plan_source,
        controlled_trip_identity=identity,
        domain_objectives=objectives,
        delivery_requirements=delivery_requirements,
        hard_intent_ids=hard_ids,
        soft_intent_ids=soft_ids,
        content_hash=content_hash,
    )


def _default_lodging_research_allowed(active: List[IntentItem]) -> bool:
    """多日行程的默认住宿调研要被明确的领域级排除覆盖。

    正向住宿要求（如指定民宿）与排除并存时保留调研，由候选排除处理剩余范围；
    窄类或具体酒店排除不关闭整个住宿领域。
    """
    if any(
        item.target is IntentTarget.LODGING
        and item.kind is not IntentKind.MUST_EXCLUDE
        and "research" in item.impact_stages
        for item in active
    ):
        return True
    return not any(
        item.target is IntentTarget.LODGING
        and item.kind is IntentKind.MUST_EXCLUDE
        and "research" in item.impact_stages
        and _excludes_whole_domain(item, ResearchDomain.LODGING)
        for item in active
    )


def _excludes_whole_domain(item: IntentItem, domain: ResearchDomain) -> bool:
    if not isinstance(item.value, CategoryIntentValue):
        return False
    labels = _DOMAIN_WIDE_EXCLUDED_CATEGORIES.get(domain, frozenset())
    return any(
        value.strip().casefold() in labels for value in item.value.categories
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


def _domain_summary(
    domain: ResearchDomain,
    scoped: List[IntentItem],
    model_domain: object | None = None,
    identity: ControlledTripIdentity | None = None,
) -> str:
    labels = [item.public_summary for item in scoped]
    base = _domain_base_summary(domain, identity)
    atoms = [
        str(atom) for atom in (getattr(model_domain, "focus_atoms", None) or [])
    ]
    parts = [base]
    if atoms:
        parts.append("研究重点：" + "、".join(f"「{atom}」" for atom in atoms))
    if labels:
        parts.append("；".join(labels))
    return "；".join(parts)[:500]


def _domain_base_summary(
    domain: ResearchDomain, identity: ControlledTripIdentity | None
) -> str:
    if identity is None:
        return {
            ResearchDomain.VISIT: "查找符合主题和要求的景点与体验",
            ResearchDomain.DINING: "查找符合用餐要求的餐饮选择",
            ResearchDomain.LODGING: "查找覆盖整个行程的住宿选择",
            ResearchDomain.LOCAL_TRANSPORT: "查询每天行程中的市内交通与衔接方式",
            ResearchDomain.LONG_DISTANCE_TRANSPORT: "查找合适的往返及跨城交通",
        }[domain]
    destinations = "、".join(place.name for place in identity.destinations)
    scope = identity_domain_scope(identity)
    if domain is ResearchDomain.VISIT:
        return f"在{scope}查找符合该风格的景点与体验"
    if domain is ResearchDomain.DINING:
        return f"在{scope}查找符合该风格的餐饮选择"
    if domain is ResearchDomain.LODGING:
        nights = max(identity.duration_days - 1, 1)
        return f"在{scope}查找覆盖 {nights} 晚的住宿选择"
    if domain is ResearchDomain.LOCAL_TRANSPORT:
        return f"查询{destinations}每天行程中的市内交通与衔接方式"
    route = identity_route_text(identity)
    if route:
        return f"查找{route} 的往返及跨城交通"
    return f"查找{destinations}的往返及跨城交通"
