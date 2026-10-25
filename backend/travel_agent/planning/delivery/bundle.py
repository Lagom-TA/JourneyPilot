from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from travel_agent.planning.delivery.projections import (
    MapProjection,
    SourceIndexProjection,
    TripReportProjection,
)
from travel_agent.planning.itinerary.options import SELECTION_SLOT_ENTITY_TYPES
from travel_agent.planning.references import EntityType
from travel_agent.planning.research.candidates import VisitCandidate
from travel_agent.planning.research.evidence import (
    FactAssertion,
    FactStoreSnapshot,
    SourceRecord,
)
from travel_agent.planning.weather.models import (
    WeatherContextSnapshot,
    WeatherRescheduleOperation,
    WeatherSelectionOperation,
    WeatherTransportModeOperation,
    WeatherVisitReplacementOperation,
)
from travel_agent.planning.workspace import TripWorkspaceV2
from travel_agent.schema import StrictModel

DELIVERY_BUNDLE_CONTRACT_VERSION = "journeypilot.delivery_bundle.v10"


class DeliveryRevisionManifest(StrictModel):
    contract_version: Literal[DELIVERY_BUNDLE_CONTRACT_VERSION] = (
        DELIVERY_BUNDLE_CONTRACT_VERSION
    )
    run_id: str = Field(min_length=1)
    generation_id: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    workspace_revision: int = Field(ge=0)
    fact_data_revision: int = Field(ge=0)
    weather_data_revision: int = Field(ge=0)
    contract_versions: Dict[str, str]
    content_hashes: Dict[str, str]
    created_at: datetime


def _report_entity_kind(entity_type: EntityType) -> str:
    return {
        EntityType.VISIT_STOP: "visit",
        EntityType.DINING_STOP: "dining",
        EntityType.LODGING_STAY: "lodging",
        EntityType.TRANSPORT_LEG: "transport",
        EntityType.CUSTOM_BLOCK: "custom",
    }[entity_type]


def _immutable_source_payload(
    source: Optional[SourceRecord],
) -> Optional[Dict[str, Any]]:
    if source is None:
        return None
    return source.model_dump(mode="json", exclude={"lifecycle_status"})


def _immutable_fact_payload(fact: Optional[FactAssertion]) -> Optional[Dict[str, Any]]:
    if fact is None:
        return None
    return fact.model_dump(mode="json", exclude={"status"})


class DeliveryBundle(StrictModel):
    manifest: DeliveryRevisionManifest
    workspace: TripWorkspaceV2
    fact_snapshot: FactStoreSnapshot
    weather_snapshot: WeatherContextSnapshot
    report_projection: TripReportProjection
    map_projection: MapProjection
    source_index: SourceIndexProjection

    @model_validator(mode="after")
    def validate_manifest(self) -> "DeliveryBundle":
        revisions = (
            self.workspace.workspace_revision,
            self.fact_snapshot.fact_data_revision,
            self.weather_snapshot.weather_data_revision,
        )
        manifest_revisions = (
            self.manifest.workspace_revision,
            self.manifest.fact_data_revision,
            self.manifest.weather_data_revision,
        )
        if revisions != manifest_revisions:
            raise ValueError("bundle snapshots do not match manifest revisions")
        if self.workspace.run_id != self.manifest.run_id:
            raise ValueError("workspace run id does not match manifest")
        if self.workspace.generation_id != self.manifest.generation_id:
            raise ValueError("workspace generation does not match manifest")
        expected_contract_versions = {
            "workspace": self.workspace.contract_version,
            "facts": self.fact_snapshot.contract_version,
            "weather": self.weather_snapshot.contract_version,
        }
        if self.manifest.contract_versions != expected_contract_versions:
            raise ValueError("bundle manifest contract versions do not match snapshots")
        catalog = self.workspace.recommendation_catalog
        if catalog.fact_data_revision > self.fact_snapshot.fact_data_revision:
            raise ValueError("recommendation catalog cannot use a future fact revision")
        source_index = {
            item.source_record_id: item for item in self.fact_snapshot.source_records
        }
        fact_index = {
            item.fact_assertion_id: item for item in self.fact_snapshot.fact_assertions
        }
        provenance = set(
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            for item in self.fact_snapshot.field_provenance
        )
        for packet in catalog.research_packets:
            if packet.run_id != self.manifest.run_id:
                raise ValueError("research packet belongs to another run")
            if any(
                _immutable_source_payload(source_index.get(item.source_record_id))
                != _immutable_source_payload(item)
                for item in packet.source_records
            ):
                raise ValueError(
                    "research packet source is absent from current fact snapshot"
                )
            if any(
                _immutable_fact_payload(fact_index.get(item.fact_assertion_id))
                != _immutable_fact_payload(item)
                for item in packet.fact_assertions
            ):
                raise ValueError(
                    "research packet fact is absent from current fact snapshot"
                )
            if any(
                json.dumps(
                    item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
                )
                not in provenance
                for item in packet.field_provenance
            ):
                raise ValueError(
                    "research packet provenance is absent from current fact snapshot"
                )
        for weather_day in self.weather_snapshot.days:
            expected_entity_id = (
                f"weather:{weather_day.destination_id}:{weather_day.date.isoformat()}"
            )
            for assertion_id in weather_day.fact_assertion_ids:
                assertion = fact_index.get(assertion_id)
                if assertion is None:
                    raise ValueError(
                        "weather context fact is absent from current fact snapshot"
                    )
                if (
                    assertion.entity_ref.entity_type != EntityType.WEATHER_DAY
                    or assertion.entity_ref.entity_id != expected_entity_id
                ):
                    raise ValueError(
                        "weather context fact targets another destination/date"
                    )
        for impact in self.weather_snapshot.impacts:
            if not set(impact.fact_assertion_ids) <= fact_index.keys():
                raise ValueError("weather impact references a missing fact assertion")
        weather_impact_ids = {
            impact.weather_impact_id for impact in self.weather_snapshot.impacts
        }
        for candidate in catalog.candidate_index().values():
            if not set(candidate.weather_impact_ids) <= weather_impact_ids:
                raise ValueError("candidate references a missing weather impact")
        for admission in catalog.admission_results:
            if not set(admission.weather_impact_ids) <= weather_impact_ids:
                raise ValueError(
                    "candidate admission references a missing weather impact"
                )
        for entity in [
            *self.workspace.itinerary.visit_stops,
            *self.workspace.itinerary.dining_stops,
            *self.workspace.itinerary.lodging_stays,
            *self.workspace.itinerary.transport_legs,
        ]:
            if not set(entity.lineage.weather_impact_ids) <= weather_impact_ids:
                raise ValueError("canonical entity references a missing weather impact")
        itinerary = self.workspace.itinerary
        scheduled_ids = {
            item.item_id
            for item in [
                *itinerary.visit_stops,
                *itinerary.dining_stops,
                *itinerary.custom_blocks,
            ]
        }
        visit_ids = {item.item_id for item in itinerary.visit_stops}
        transport_ids = {item.transport_leg_id for item in itinerary.transport_legs}
        slot_ids = {item.selection_slot_id for item in self.workspace.selection_slots}
        timeline_by_day = {
            day.day_id: {item.entity_id for item in day.timeline}
            for day in itinerary.day_plans
        }
        candidates = catalog.candidate_index()
        for proposal in self.weather_snapshot.adjustment_proposals:
            if not set(proposal.fact_assertion_ids) <= fact_index.keys():
                raise ValueError("weather proposal references a missing fact assertion")
            if proposal.base_workspace_revision > self.workspace.workspace_revision:
                raise ValueError(
                    "weather proposal cannot reference a future workspace revision"
                )
            for operation in proposal.operations:
                if isinstance(operation, WeatherRescheduleOperation):
                    if operation.item_id not in scheduled_ids:
                        raise ValueError(
                            "weather reschedule references a missing scheduled item"
                        )
                elif isinstance(operation, WeatherSelectionOperation):
                    if operation.selection_slot_id not in slot_ids:
                        raise ValueError("weather selection references a missing slot")
                elif isinstance(operation, WeatherVisitReplacementOperation):
                    candidate = candidates.get(operation.candidate_id)
                    if (
                        operation.item_id not in visit_ids
                        or not isinstance(candidate, VisitCandidate)
                    ):
                        raise ValueError(
                            "weather visit replacement references a missing visit candidate"
                        )
                elif isinstance(operation, WeatherTransportModeOperation):
                    if operation.transport_leg_id not in transport_ids:
                        raise ValueError(
                            "weather transport adjustment references a missing leg"
                        )
                elif operation.target_entity_id not in timeline_by_day.get(
                    operation.day_id, set()
                ):
                    raise ValueError("weather buffer target is missing from its day")
        projection_revisions = (
            self.report_projection.source_workspace_revision,
            self.report_projection.source_fact_data_revision,
            self.report_projection.source_weather_data_revision,
        )
        if (
            self.report_projection.status == "ready"
            and projection_revisions != revisions
        ):
            raise ValueError("ready report projection is not based on bundle revisions")
        if self.report_projection.status == "stale":
            if any(
                source > current
                for source, current in zip(projection_revisions, revisions)
            ):
                raise ValueError(
                    "stale report projection cannot reference a future revision"
                )
        if self.map_projection.source_workspace_revision != revisions[0]:
            raise ValueError("map projection is not based on workspace revision")
        if self.source_index.source_fact_data_revision != revisions[1]:
            raise ValueError("source index is not based on fact revision")
        real_workspace_entity_refs = (
            {
                (EntityType.VISIT_STOP, item.item_id)
                for item in self.workspace.itinerary.visit_stops
            }
            | {
                (EntityType.DINING_STOP, item.item_id)
                for item in self.workspace.itinerary.dining_stops
            }
            | {
                (EntityType.LODGING_STAY, item.stay_id)
                for item in self.workspace.itinerary.lodging_stays
            }
            | {
                (EntityType.TRANSPORT_LEG, item.transport_leg_id)
                for item in self.workspace.itinerary.transport_legs
            }
            | {
                (EntityType.CUSTOM_BLOCK, item.item_id)
                for item in self.workspace.itinerary.custom_blocks
            }
        )
        workspace_entity_refs = real_workspace_entity_refs
        projection_fact_ids_by_ref: Dict[tuple[EntityType, str], set[str]] = {
            **{
                (EntityType.VISIT_STOP, item.item_id): set(
                    item.lineage.fact_assertion_ids
                )
                for item in self.workspace.itinerary.visit_stops
            },
            **{
                (EntityType.DINING_STOP, item.item_id): set(
                    item.lineage.fact_assertion_ids
                )
                for item in self.workspace.itinerary.dining_stops
            },
            **{
                (EntityType.LODGING_STAY, item.stay_id): set(
                    item.lineage.fact_assertion_ids
                )
                for item in self.workspace.itinerary.lodging_stays
            },
            **{
                (EntityType.TRANSPORT_LEG, item.transport_leg_id): set(
                    item.lineage.fact_assertion_ids
                )
                if item.route_status == "ready"
                else set()
                for item in self.workspace.itinerary.transport_legs
            },
            **{
                (EntityType.CUSTOM_BLOCK, item.item_id): set()
                for item in self.workspace.itinerary.custom_blocks
            },
            **{
                (
                    EntityType.WEATHER_DAY,
                    f"weather:{day.destination_id}:{day.date.isoformat()}",
                ): set(day.fact_assertion_ids)
                for day in self.weather_snapshot.days
            },
        }
        for slot in self.workspace.selection_slots:
            entity_type = SELECTION_SLOT_ENTITY_TYPES[slot.slot_type]
            for option in slot.options:
                if option.option_id == slot.selected_option_id:
                    continue
                projection_fact_ids_by_ref[(entity_type, option.candidate_id)] = set(
                    option.fact_assertion_ids
                )
        citations = self.source_index.content.citations
        citation_ids = [item.citation_id for item in citations]
        if len(citation_ids) != len(set(citation_ids)):
            raise ValueError("source projection citation ids must be unique")
        for citation in citations:
            ref = (citation.entity_ref.entity_type, citation.entity_ref.entity_id)
            allowed_fact_ids = projection_fact_ids_by_ref.get(ref)
            if allowed_fact_ids is None:
                raise ValueError(
                    "source projection contains a dangling entity reference"
                )
            if not set(citation.fact_assertion_ids) <= allowed_fact_ids:
                raise ValueError(
                    "source projection attributes facts to the wrong entity or selection option"
                )
            projected_source_ids = {
                source.source_record_id for source in citation.sources
            }
            if not projected_source_ids <= source_index.keys():
                raise ValueError("source projection references a missing source record")
        map_refs = {
            (item.entity_ref.entity_type, item.entity_ref.entity_id)
            for item in [
                *self.map_projection.content.places,
                *self.map_projection.content.routes,
            ]
        }
        if not map_refs <= real_workspace_entity_refs:
            raise ValueError(
                "map projection references an entity outside the itinerary"
            )
        known_citations = set(citation_ids)
        map_citations = {
            citation_id
            for item in [
                *self.map_projection.content.places,
                *self.map_projection.content.routes,
            ]
            for citation_id in item.citation_ids
        }
        if not map_citations <= known_citations:
            raise ValueError("map projection references a missing public citation")
        if self.report_projection.status == "ready":
            if self.report_projection.citations != citations:
                raise ValueError(
                    "report and source index must share one citation projection"
                )
            document = self.report_projection.document
            assert document is not None
            report_refs = {
                (block.entity_ref.entity_type, block.entity_ref.entity_id)
                for day in document.days
                for block in day.blocks
            }
            if not report_refs <= workspace_entity_refs:
                raise ValueError(
                    "report projection contains a dangling workspace entity reference"
                )
            if any(
                block.entity_kind != _report_entity_kind(block.entity_ref.entity_type)
                for day in document.days
                for block in day.blocks
            ):
                raise ValueError(
                    "report projection renders an entity with the wrong content type"
                )
            if any(
                not set(block.weather_impact_ids) <= weather_impact_ids
                for day in document.days
                for block in day.blocks
            ):
                raise ValueError(
                    "report projection references a missing weather impact"
                )
            expected_timeline = [
                (day.day_id, ref.entity_type, ref.entity_id, ref.projection_role)
                for day in self.workspace.itinerary.day_plans
                for ref in day.timeline
            ]
            projected_timeline = [
                (
                    day.day_id,
                    block.entity_ref.entity_type,
                    block.entity_ref.entity_id,
                    block.projection_role,
                )
                for day in document.days
                for block in day.blocks
            ]
            if projected_timeline != expected_timeline:
                raise ValueError(
                    "report projection must preserve the canonical timeline and projection roles"
                )
            report_citations = (
                {
                    citation_id
                    for day in document.days
                    for block in day.blocks
                    for citation_id in block.citation_ids
                }
                | {
                    citation_id
                    for selection in document.selections
                    for option in selection.options
                    for citation_id in option.citation_ids
                }
                | {
                    citation_id
                    for day in document.weather
                    for citation_id in day.citation_ids
                }
            )
            if not report_citations <= known_citations:
                raise ValueError(
                    "report projection references a missing public citation"
                )
        expected_hashes = bundle_content_hashes(
            workspace=self.workspace,
            fact_snapshot=self.fact_snapshot,
            weather_snapshot=self.weather_snapshot,
            report_projection=self.report_projection,
            map_projection=self.map_projection,
            source_index=self.source_index,
        )
        if self.manifest.content_hashes != expected_hashes:
            raise ValueError("bundle content hashes do not match payload")
        return self


def canonical_content_hash(value: BaseModel) -> str:
    payload = value.model_dump(mode="json", by_alias=True, exclude_none=False)
    encoded = json.dumps(
        _normalize_canonical_json_numbers(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_canonical_json_numbers(value: Any) -> Any:
    # JSONB normalizes signed zero; hash equivalent numbers without changing evidence.
    if isinstance(value, dict):
        return {
            key: _normalize_canonical_json_numbers(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_canonical_json_numbers(item) for item in value]
    if isinstance(value, float) and value == 0.0:
        return 0.0
    return value


def bundle_content_hashes(
    *,
    workspace: TripWorkspaceV2,
    fact_snapshot: FactStoreSnapshot,
    weather_snapshot: WeatherContextSnapshot,
    report_projection: TripReportProjection,
    map_projection: MapProjection,
    source_index: SourceIndexProjection,
) -> Dict[str, str]:
    return {
        "workspace": canonical_content_hash(workspace),
        "fact_snapshot": canonical_content_hash(fact_snapshot),
        "weather_snapshot": canonical_content_hash(weather_snapshot),
        "report_projection": canonical_content_hash(report_projection),
        "map_projection": canonical_content_hash(map_projection),
        "source_index": canonical_content_hash(source_index),
    }
