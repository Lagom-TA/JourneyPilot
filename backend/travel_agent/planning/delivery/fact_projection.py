"""交付事实快照构建。"""

from __future__ import annotations

from travel_agent.planning.costs.coverage import build_cost_coverage_summary
from travel_agent.planning.costs.coverage import itinerary_price_components
from travel_agent.planning.delivery.projection_errors import DeliveryProjectionError
from travel_agent.planning.itinerary.options import SELECTION_SLOT_ENTITY_TYPES
from travel_agent.planning.references import EntityType
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.planning.research.evidence import FactStoreSnapshot
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.workspace import TripWorkspace
from typing import Sequence


def build_fact_snapshot(
    workspace: TripWorkspace,
    *,
    weather_sources: Sequence[SourceRecord] = (),
    weather_facts: Sequence[FactAssertion] = (),
    weather_provenance: Sequence = (),
) -> FactStoreSnapshot:
    """合并 packet 与天气事实；同一身份出现不同内容时抛出错误。"""

    sources: dict[str, SourceRecord] = {}
    facts: dict[str, FactAssertion] = {}
    provenance: dict[tuple[str, str, str], object] = {}

    def add_unique(index: dict, key: str, value: object, kind: str) -> None:
        current = index.get(key)
        if current is not None and current != value:
            raise DeliveryProjectionError(f"conflicting {kind} identity: {key}")
        index[key] = value

    for packet in workspace.recommendation_catalog.research_packets:
        for source in packet.source_records:
            add_unique(sources, source.source_record_id, source, "source record")
        for fact in packet.fact_assertions:
            add_unique(facts, fact.fact_assertion_id, fact, "fact assertion")
        for item in packet.field_provenance:
            provenance[(item.entity_ref.entity_id, item.field_path, item.origin)] = item
    for source in weather_sources:
        add_unique(sources, source.source_record_id, source, "weather source record")
    for fact in weather_facts:
        add_unique(facts, fact.fact_assertion_id, fact, "weather fact assertion")
    for item in weather_provenance:
        provenance[(item.entity_ref.entity_id, item.field_path, item.origin)] = item

    return FactStoreSnapshot(
        fact_data_revision=workspace.recommendation_catalog.fact_data_revision,
        source_records=list(sources.values()),
        fact_assertions=list(facts.values()),
        field_provenance=list(provenance.values()),
    )


_OPTIONAL_FIELD_SOURCES = {
    EntityType.VISIT_STOP: {
        "opening_window": ("opening_window",),
        "reservation_required": ("reservation_required",),
        "estimated_cost_cny": ("estimated_cost_cny",),
    },
    EntityType.DINING_STOP: {
        "opening_window": ("opening_window",),
        "reservation_required": ("reservation_required",),
        "average_spend_cny": ("average_spend_cny",),
        "estimated_cost_cny": ("estimated_cost_cny", "average_spend_cny"),
    },
    EntityType.LODGING_STAY: {
        "nightly_price_cny": ("nightly_price_cny",),
        "total_price_cny": ("total_price_cny",),
    },
    EntityType.TRANSPORT_LEG: {
        "total_cost_cny": ("total_cost_cny",),
    },
}


def workspace_for_public_projection(
    workspace: TripWorkspace, facts: FactStoreSnapshot
) -> TripWorkspace:
    """在公开副本中清除缺失事实对应的无依据值，保留独立来源支持的值。"""

    fact_index = {fact.fact_assertion_id: fact for fact in facts.fact_assertions}
    source_ids = {source.source_record_id for source in facts.source_records}
    candidates = workspace.recommendation_catalog.candidate_index()

    def is_missing_value(
        value: object, paths: Sequence[str], assertion_ids: Sequence[str],
        entity_type: EntityType, candidate_id: str,
    ) -> bool:
        relevant = [
            fact
            for assertion_id in assertion_ids
            if (fact := fact_index.get(assertion_id)) is not None
            and fact.entity_ref.entity_type == entity_type
            and fact.entity_ref.entity_id == candidate_id
            and fact.field_path in paths
        ]
        if not any(fact.status == "missing" and fact.asserted_value is None for fact in relevant):
            return False
        return not any(
            fact.status not in {"missing", "superseded"}
            and fact.asserted_value is not None
            and (isinstance(fact.asserted_value, bool) == isinstance(value, bool))
            and fact.asserted_value == value
            and any(
                link.source_record_id in source_ids
                and link.relation in {"supports", "qualifies"}
                for link in fact.source_links
            )
            for fact in relevant
        )

    def public_entity(entity, entity_type: EntityType):
        lineage = entity.lineage
        if lineage.lineage_kind != "candidate_entity":
            return entity
        candidate_id = lineage.candidate_id
        assert candidate_id is not None
        updates = {
            field: None
            for field, paths in _OPTIONAL_FIELD_SOURCES[entity_type].items()
            if getattr(entity, field) is not None
            and is_missing_value(
                getattr(entity, field), paths, lineage.fact_assertion_ids,
                entity_type, candidate_id,
            )
        }
        return entity.model_copy(update=updates) if updates else entity

    itinerary = workspace.itinerary
    visits = [public_entity(item, EntityType.VISIT_STOP) for item in itinerary.visit_stops]
    dining = [public_entity(item, EntityType.DINING_STOP) for item in itinerary.dining_stops]
    lodging = [public_entity(item, EntityType.LODGING_STAY) for item in itinerary.lodging_stays]
    transport = [public_entity(item, EntityType.TRANSPORT_LEG) for item in itinerary.transport_legs]
    public_itinerary = itinerary.model_copy(update={
        "visit_stops": visits,
        "dining_stops": dining,
        "lodging_stays": lodging,
        "transport_legs": transport,
        "cost_summary": build_cost_coverage_summary(itinerary_price_components(
            visit_stops=visits, dining_stops=dining,
            lodging_stays=lodging, transport_legs=transport,
        )),
    })

    slots = []
    for slot in workspace.selection_slots:
        entity_type = SELECTION_SLOT_ENTITY_TYPES[slot.slot_type]
        fields = _OPTIONAL_FIELD_SOURCES[entity_type]
        options = []
        for option in slot.options:
            candidate = candidates[option.candidate_id]
            comparison = [
                field for field in option.comparison_facts
                if field not in fields or not is_missing_value(
                    getattr(candidate, field, None), fields[field],
                    option.fact_assertion_ids, entity_type, option.candidate_id,
                )
            ]
            options.append(option.model_copy(update={"comparison_facts": comparison}))
        slots.append(slot.model_copy(update={"options": options}))
    return workspace.model_copy(update={
        "itinerary": public_itinerary,
        "selection_slots": slots,
    })
