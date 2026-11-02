"""交付投影构建。"""

from __future__ import annotations

from datetime import date
from datetime import datetime
from travel_agent.planning.delivery.fact_projection import workspace_for_public_projection
from travel_agent.planning.delivery.map_projection import project_map
from travel_agent.planning.delivery.projections import MapProjection
from travel_agent.planning.delivery.projections import PublicCitationProjection
from travel_agent.planning.delivery.projections import SourceIndexDocument
from travel_agent.planning.delivery.projections import SourceIndexProjection
from travel_agent.planning.delivery.projections import TripReportProjection
from travel_agent.planning.delivery.report_projection import project_report
from travel_agent.planning.research.evidence import FactStoreSnapshot
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.planning.workspace import TripWorkspace
from typing import Sequence


def project_source_index(
    facts: FactStoreSnapshot,
    citations: Sequence[PublicCitationProjection],
) -> SourceIndexProjection:
    return SourceIndexProjection(
        source_fact_data_revision=facts.fact_data_revision,
        content=SourceIndexDocument(citations=list(citations)),
    )


def build_delivery_projections(
    workspace: TripWorkspace,
    facts: FactStoreSnapshot,
    weather: WeatherContextSnapshot,
    *,
    generated_at: datetime,
    historical_weather_days: frozenset[tuple[str, date]] = frozenset(),
) -> tuple[TripReportProjection, MapProjection, SourceIndexProjection]:
    report = project_report(
        workspace_for_public_projection(workspace, facts),
        facts,
        weather,
        generated_at=generated_at,
        historical_weather_days=historical_weather_days,
    )
    map_projection = project_map(workspace, facts, report.citations)
    source_index = project_source_index(facts, report.citations)
    return report, map_projection, source_index
