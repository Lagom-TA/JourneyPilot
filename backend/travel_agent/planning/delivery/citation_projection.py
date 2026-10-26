"""交付引用投影。"""

from __future__ import annotations

from travel_agent.planning.delivery.projection_errors import DeliveryProjectionError
from travel_agent.planning.delivery.projections import PublicCitationProjection
from travel_agent.planning.delivery.projections import PublicSourceSummary
from travel_agent.planning.delivery.projections import PublicSupportedValue
from travel_agent.planning.delivery.source_presentation import (
    _public_source_presentation,
)
from travel_agent.planning.itinerary.options import SELECTION_SLOT_ENTITY_TYPES
from travel_agent.planning.references import EntityRef
from travel_agent.planning.references import EntityType
from travel_agent.planning.research.evidence import FactAssertion
from travel_agent.planning.research.evidence import FactStoreSnapshot
from travel_agent.planning.research.evidence import SourceRecord
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.planning.workspace import TripWorkspaceV2
from typing import Iterable
from typing import Sequence
import hashlib


def _public_source(source: SourceRecord) -> PublicSourceSummary:
    chunk_content = None
    chunk_locator = None
    if source.source_kind == "rag_chunk":
        chunk_content = source.snapshot.get("chunk_content") or source.snapshot.get(
            "content"
        )
        if not isinstance(chunk_content, str) or not chunk_content.strip():
            raise DeliveryProjectionError(
                f"RAG source {source.source_record_id} is missing the complete chunk"
            )
        locator_parts = [
            source.snapshot.get("document_id"),
            source.snapshot.get("document_revision"),
            source.snapshot.get("chunk_id"),
            source.snapshot.get("section") or source.snapshot.get("page"),
        ]
        chunk_locator = " / ".join(
            str(part) for part in locator_parts if part is not None
        )
    title, public_excerpt, canonical_url = _public_source_presentation(source)
    return PublicSourceSummary(
        source_record_id=source.source_record_id,
        source_kind=source.source_kind,
        title=title,
        provider_name=source.provider_name,
        public_excerpt=public_excerpt,
        canonical_url=canonical_url,
        retrieved_at=source.retrieved_at,
        observed_at=source.observed_at,
        content_hash=source.content_hash,
        rag_chunk_content=chunk_content,
        rag_document_locator=chunk_locator or None,
    )


def _citation_id(entity_ref: EntityRef, fact: FactAssertion) -> str:
    payload = f"{entity_ref.entity_type.value}:{entity_ref.entity_id}:{fact.fact_assertion_id}"
    return f"cite_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def _entity_lineage_targets(
    workspace: TripWorkspaceV2,
) -> list[tuple[EntityRef, Sequence[str]]]:
    itinerary = workspace.itinerary
    targets: list[tuple[EntityRef, Sequence[str]]] = []
    targets.extend(
        (
            EntityRef(entity_type=EntityType.VISIT_STOP, entity_id=item.item_id),
            item.lineage.fact_assertion_ids,
        )
        for item in itinerary.visit_stops
    )
    targets.extend(
        (
            EntityRef(entity_type=EntityType.DINING_STOP, entity_id=item.item_id),
            item.lineage.fact_assertion_ids,
        )
        for item in itinerary.dining_stops
    )
    targets.extend(
        (
            EntityRef(entity_type=EntityType.LODGING_STAY, entity_id=item.stay_id),
            item.lineage.fact_assertion_ids,
        )
        for item in itinerary.lodging_stays
    )
    targets.extend(
        (
            EntityRef(
                entity_type=EntityType.TRANSPORT_LEG, entity_id=item.transport_leg_id
            ),
            item.lineage.fact_assertion_ids if item.route_status == "ready" else [],
        )
        for item in itinerary.transport_legs
    )
    for slot in workspace.selection_slots:
        entity_type = SELECTION_SLOT_ENTITY_TYPES[slot.slot_type]
        for option in slot.options:
            if option.option_id == slot.selected_option_id:
                continue
            targets.append(
                (
                    EntityRef(entity_type=entity_type, entity_id=option.candidate_id),
                    option.fact_assertion_ids,
                )
            )
    return targets


def project_public_citations(
    workspace: TripWorkspaceV2,
    facts: FactStoreSnapshot,
    weather: WeatherContextSnapshot,
) -> list[PublicCitationProjection]:
    fact_index = {item.fact_assertion_id: item for item in facts.fact_assertions}
    source_index = {item.source_record_id: item for item in facts.source_records}
    targets = _entity_lineage_targets(workspace)
    for day in weather.days:
        targets.append(
            (
                EntityRef(
                    entity_type=EntityType.WEATHER_DAY,
                    entity_id=f"weather:{day.destination_id}:{day.date.isoformat()}",
                ),
                day.fact_assertion_ids,
            )
        )

    projections: dict[str, PublicCitationProjection] = {}
    for target_ref, assertion_ids in targets:
        for assertion_id in assertion_ids:
            fact = fact_index.get(assertion_id)
            if fact is None:
                raise DeliveryProjectionError(
                    f"projection fact is missing: {assertion_id}"
                )
            source_ids = [
                link.source_record_id
                for link in fact.source_links
                if link.relation in {"supports", "qualifies"}
            ]
            if not source_ids:
                raise DeliveryProjectionError(
                    f"projection fact has no public source: {assertion_id}"
                )
            missing = [
                source_id for source_id in source_ids if source_id not in source_index
            ]
            if missing:
                raise DeliveryProjectionError(
                    f"projection source is missing: {missing[0]}"
                )
            citation_id = _citation_id(target_ref, fact)
            projections[citation_id] = PublicCitationProjection(
                citation_id=citation_id,
                entity_ref=target_ref,
                field_paths=[fact.field_path],
                fact_status=fact.status if fact.status != "superseded" else "stale",
                supported_values=[
                    PublicSupportedValue(
                        label=fact.field_path,
                        value=fact.asserted_value,
                        unit=fact.unit,
                        currency=fact.currency,
                    )
                ],
                sources=[
                    _public_source(source_index[source_id])
                    for source_id in dict.fromkeys(source_ids)
                ],
                fact_assertion_ids=[assertion_id],
            )
    return sorted(projections.values(), key=lambda item: item.citation_id)


def _citation_lookup(
    citations: Iterable[PublicCitationProjection],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    by_fact: dict[str, str] = {}
    by_entity: dict[str, list[str]] = {}
    for citation in citations:
        for fact_id in citation.fact_assertion_ids:
            by_fact[f"{citation.entity_ref.entity_id}:{fact_id}"] = citation.citation_id
        by_entity.setdefault(citation.entity_ref.entity_id, []).append(
            citation.citation_id
        )
    return by_fact, by_entity
