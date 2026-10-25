"""Planning delivery fact projection."""

from __future__ import annotations

from travel_agent.planning.delivery.projection_errors import DeliveryProjectionError
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.planning.research.evidence import FactStoreSnapshot
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.workspace import TripWorkspaceV2
from typing import Sequence


def build_fact_snapshot(
    workspace: TripWorkspaceV2,
    *,
    weather_sources: Sequence[SourceRecord] = (),
    weather_facts: Sequence[FactAssertion] = (),
    weather_provenance: Sequence = (),
) -> FactStoreSnapshot:
    """Merge packet and weather facts without accepting conflicting identities."""

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
