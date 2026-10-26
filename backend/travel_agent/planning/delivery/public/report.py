"""公开报告投影。"""

from __future__ import annotations

from travel_agent.planning.costs.presentation import cost_coverage_statement
from travel_agent.planning.delivery.evidence_basis import EvidenceBasisView
from travel_agent.planning.delivery.projections import MapProjection
from travel_agent.planning.delivery.projections import PublicCitationProjection
from travel_agent.planning.delivery.projections import ReportDaySection
from travel_agent.planning.delivery.projections import ReportEntityBlock
from travel_agent.planning.delivery.projections import ReportSelectionSection
from travel_agent.planning.delivery.projections import ReportWeatherDay
from travel_agent.planning.delivery.projections import SourceIndexProjection
from travel_agent.planning.delivery.projections import TripReportDocument
from travel_agent.planning.delivery.projections import TripReportProjection
from travel_agent.planning.delivery.public.itinerary import _day
from travel_agent.planning.delivery.public.itinerary import _public_cost_summary
from travel_agent.planning.delivery.public.itinerary import _public_endpoint
from travel_agent.planning.delivery.public.itinerary import _public_entity_ref
from travel_agent.planning.delivery.public.itinerary import _public_segments
from travel_agent.planning.delivery.public.itinerary import _timestamp
from travel_agent.planning.delivery.travel_content import public_selection_text
from travel_agent.planning.references import EntityType
from typing import Any
from typing import Dict


def _public_citation(citation: PublicCitationProjection) -> Dict[str, Any]:
    """投影引用，不包含 provider 身份与原始 RAG/来源载荷。"""

    return {
        "citation_id": citation.citation_id,
        "entity_ref": _public_entity_ref(citation.entity_ref),
        "field_paths": list(citation.field_paths),
        "fact_status": citation.fact_status,
        "supported_values": [
            value.model_dump(mode="json") for value in citation.supported_values
        ],
        "sources": [
            {
                "source_record_id": source.source_record_id,
                "source_kind": source.source_kind,
                "title": source.title,
                "public_excerpt": source.public_excerpt,
                "canonical_url": source.canonical_url,
                "retrieved_at": source.retrieved_at.isoformat(),
                "observed_at": source.observed_at.isoformat()
                if source.observed_at is not None
                else None,
            }
            for source in citation.sources
        ],
    }


def _public_report_block(
    block: ReportEntityBlock, view: EvidenceBasisView
) -> Dict[str, Any]:
    """投影一个报告条目。

    ``weather_impact_ids`` / ``personalization_influence_ids`` 是内部账本引用，
    没有产品含义，因此不输出；``custom`` 条目不声明证据基础，与 workspace 中
    的处理一致。
    """

    payload: Dict[str, Any] = {
        "entity_ref": _public_entity_ref(block.entity_ref),
        "day_id": block.day_id,
        "projection_role": block.projection_role,
        "title": block.title,
        "entity_kind": block.entity_kind,
        "summary": block.summary,
        "details": dict(block.details),
        "citation_ids": list(block.citation_ids),
    }
    if block.entity_kind != "custom":
        payload["evidence_basis"] = view.basis_for(
            EntityType(block.entity_ref.entity_type), block.entity_ref.entity_id
        )
    return payload


def _public_report_day(
    day: ReportDaySection, view: EvidenceBasisView
) -> Dict[str, Any]:
    return {
        "day_id": day.day_id,
        "day": day.day,
        "date": _day(day.date),
        "destination_id": day.destination_id,
        "destination_name": day.destination_name,
        "theme": day.theme,
        "blocks": [_public_report_block(block, view) for block in day.blocks],
    }


def _public_report_selection(section: ReportSelectionSection) -> Dict[str, Any]:
    """投影一个选择区段，去掉内部候选身份。

    ``candidate_id`` 指向推荐目录中的一行；对读者而言，选项已由 ``option_id``
    与名称标识。
    """

    return {
        "selection_slot_id": section.selection_slot_id,
        "slot_type": section.slot_type,
        "context": dict(section.context),
        "status": section.status,
        "options": [
            {
                "option_id": option.option_id,
                "name": option.name,
                "rank": option.rank,
                "selected": option.selected,
                "recommended": option.recommended,
                "selection_reasons": [
                    public_selection_text(reason) for reason in option.selection_reasons
                ],
                "tradeoff": public_selection_text(option.tradeoff)
                if option.tradeoff
                else None,
                "comparison_facts": list(option.comparison_facts),
                "availability_status": option.availability_status,
                "citation_ids": list(option.citation_ids),
            }
            for option in section.options
        ],
    }


def _public_report_weather_day(day: ReportWeatherDay) -> Dict[str, Any]:
    return {
        "destination_id": day.destination_id,
        "destination_name": day.destination_name,
        "date": _day(day.date),
        "data_kind": day.data_kind,
        "observed_at": day.observed_at.isoformat()
        if day.observed_at is not None
        else None,
        "weather_data_state": day.weather_data_state,
        "condition_label": day.condition_label,
        "high_c": day.high_c,
        "low_c": day.low_c,
        "precipitation_probability_pct": day.precipitation_probability_pct,
        "wind_speed_kph": day.wind_speed_kph,
        "citation_ids": list(day.citation_ids),
    }


def _public_report_document(
    document: TripReportDocument, view: EvidenceBasisView
) -> Dict[str, Any]:
    return {
        "title": document.title,
        "overview": document.overview,
        "destinations": [
            item.model_dump(mode="json") for item in document.destinations
        ],
        "duration_days": document.duration_days,
        "cost_summary": _public_cost_summary(document.cost_summary),
        "cost_coverage_statement": cost_coverage_statement(document.cost_summary),
        "days": [_public_report_day(day, view) for day in document.days],
        "selections": [
            _public_report_selection(section) for section in document.selections
        ],
        "weather": [_public_report_weather_day(day) for day in document.weather],
        "highlights": list(document.highlights),
        "important_notes": list(document.important_notes),
    }


def _public_report(
    report: TripReportProjection, view: EvidenceBasisView
) -> Dict[str, Any]:
    """投影正式报告。

    ``failure_reason`` 不输出：ready 报告是正式产物，失败信息属于完整性诊断。
    """

    return {
        "source_workspace_revision": report.source_workspace_revision,
        "source_fact_data_revision": report.source_fact_data_revision,
        "source_weather_data_revision": report.source_weather_data_revision,
        "status": report.status,
        "document": (
            _public_report_document(report.document, view)
            if report.document is not None
            else None
        ),
        "citations": [_public_citation(item) for item in report.citations],
        "generated_at": _timestamp(report.generated_at),
    }


def _public_map(projection: MapProjection) -> Dict[str, Any]:
    """投影地图，只包含几何信息；证据声明属于卡片。"""

    return {
        "source_workspace_revision": projection.source_workspace_revision,
        "content": {
            "places": [
                {
                    "entity_ref": _public_entity_ref(place.entity_ref),
                    "name": place.name,
                    "place_id": place.place_id,
                    "latitude": place.latitude,
                    "longitude": place.longitude,
                    "citation_ids": list(place.citation_ids),
                }
                for place in projection.content.places
            ],
            "routes": [
                {
                    "entity_ref": _public_entity_ref(route.entity_ref),
                    "transport_class": route.transport_class,
                    "selected_mode": route.selected_mode.value,
                    "route_status": route.route_status,
                    "from_endpoint": _public_endpoint(route.from_endpoint),
                    "to_endpoint": _public_endpoint(route.to_endpoint),
                    "segments": _public_segments(route.segments),
                    "citation_ids": list(route.citation_ids),
                }
                for route in projection.content.routes
            ],
        },
    }


def _public_source_index(projection: SourceIndexProjection) -> Dict[str, Any]:
    return {
        "source_fact_data_revision": projection.source_fact_data_revision,
        "content": {
            "citations": [
                _public_citation(item) for item in projection.content.citations
            ]
        },
    }
