from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Response
from travel_agent.bootstrap.registry import get_components
from travel_agent.storage.delivery_bundle_store import (
    BundleContractSuperseded,
    BundleIdempotencyMismatch,
    BundleRevisionConflict,
    BundleRevisionVector,
)
from travel_agent.planning.delivery.weather_refresh_contracts import (
    WeatherRefreshRefused,
)
from travel_agent.runtime.blocking_work import BlockingWorkBusy
from travel_agent.integrations.pdf_readiness import PdfFontUnavailable
from travel_agent.planning.delivery.pdf_export import ReportOutOfDateError
from travel_agent.api.schemas.delivery import (
    PublicDeliveryBundleResponse,
    TripReportPdfExportRequest,
)
from travel_agent.api.schemas.weather import (
    WeatherBundleRefreshRequest,
    WeatherBundleRefreshResponse,
)
from travel_agent.planning.delivery.public.bundle import public_delivery_bundle

from travel_agent.api.run_authorization import _get_authorized_run
from travel_agent.api.run_errors import (
    raise_workspace_mutation_conflict,
    raise_bundle_contract_superseded,
    raise_run_use_case_error,
)
from travel_agent.planning.weather.bundle_refresh import refresh_delivery_weather
from travel_agent.planning.delivery.export import export_trip_report
from travel_agent.planning.run_errors import (
    DeliveryBundleMissing,
    ReportRevisionChanged,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trip-runs", tags=["trip-runs"])


def _weather_refresh_expected(
    request: WeatherBundleRefreshRequest,
) -> BundleRevisionVector:
    return BundleRevisionVector(
        workspace_revision=request.base_workspace_revision,
        fact_data_revision=request.base_fact_data_revision,
        weather_data_revision=request.base_weather_data_revision,
        bundle_id=request.base_bundle_id,
    )


@router.get("/{run_id}/bundle/current", response_model=PublicDeliveryBundleResponse)
async def read_current_delivery_bundle(
    run_id: str,
    session_id: Optional[str] = Query(default=None),
) -> PublicDeliveryBundleResponse:
    components = get_components()
    await _get_authorized_run(run_id, session_id=session_id)
    try:
        bundle = await components.delivery_bundle_store.get_current(run_id)
    except BundleContractSuperseded as exc:
        raise_bundle_contract_superseded(exc)
        raise AssertionError("unreachable")
    if bundle is None:
        raise HTTPException(status_code=404, detail="当前 Delivery Bundle 不存在")
    return PublicDeliveryBundleResponse.model_validate(public_delivery_bundle(bundle))


@router.post(
    "/{run_id}/bundle/current/weather/refresh",
    response_model=WeatherBundleRefreshResponse,
)
async def refresh_current_bundle_weather(
    run_id: str,
    request: WeatherBundleRefreshRequest,
) -> WeatherBundleRefreshResponse:
    components = get_components()
    await _get_authorized_run(run_id, session_id=request.session_id)
    try:
        result = await refresh_delivery_weather(
            run_id,
            expected=_weather_refresh_expected(request),
            refresh_id=request.refresh_id,
            bundle_store=components.delivery_bundle_store,
            trip_run_store=components.trip_run_store,
            clock=getattr(components, "weather_refresh_clock", None),
            weather_context_builder=getattr(
                components, "weather_context_builder", None
            ),
        )
    except DeliveryBundleMissing as error:
        raise_run_use_case_error(error)
    except BundleContractSuperseded as exc:
        raise_bundle_contract_superseded(exc)
        raise AssertionError("unreachable")
    except BundleRevisionConflict:
        await raise_workspace_mutation_conflict(
            run_id, components.delivery_bundle_store
        )
        raise AssertionError("unreachable")
    except BundleIdempotencyMismatch as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "refresh_id_reused",
                "message": "这次天气刷新的标识已用于另一项操作。",
            },
        ) from exc
    except BundleContractSuperseded as exc:
        raise_bundle_contract_superseded(exc)
        raise AssertionError("unreachable")
    except WeatherRefreshRefused as exc:
        logger.warning(
            "weather refresh refused at API boundary run_id=%s reason=%s: %s",
            run_id,
            exc.code,
            exc,
        )

        try:
            current = await components.delivery_bundle_store.get_current(run_id)
        except BundleContractSuperseded as superseded:
            raise_bundle_contract_superseded(superseded)
            raise AssertionError("unreachable")
        if current is None:
            raise HTTPException(status_code=404, detail="当前 Delivery Bundle 不存在")
        return WeatherBundleRefreshResponse(
            refresh_id=request.refresh_id,
            attempted=True,
            committed=False,
            used_previous_values=False,
            refusal_reason=exc.code,
            bundle=PublicDeliveryBundleResponse.model_validate(
                public_delivery_bundle(current)
            ),
        )
    return WeatherBundleRefreshResponse(
        refresh_id=request.refresh_id,
        attempted=result.attempted,
        committed=result.committed,
        used_previous_values=result.used_previous_values,
        refusal_reason=result.refusal_reason,
        bundle=PublicDeliveryBundleResponse.model_validate(
            public_delivery_bundle(result.bundle)
        ),
    )


@router.post("/{run_id}/bundle/current/pdf")
async def export_current_trip_report_pdf(
    run_id: str,
    request: TripReportPdfExportRequest,
) -> Response:
    components = get_components()
    await _get_authorized_run(run_id, session_id=request.session_id)
    try:
        artifact = await export_trip_report(
            run_id,
            expected=BundleRevisionVector(
                bundle_id=request.bundle_id,
                workspace_revision=request.workspace_revision,
                fact_data_revision=request.fact_data_revision,
                weather_data_revision=request.weather_data_revision,
            ),
            bundle_store=components.delivery_bundle_store,
        )
    except BundleContractSuperseded as exc:
        raise_bundle_contract_superseded(exc)
        raise AssertionError("unreachable")
    except (DeliveryBundleMissing, ReportRevisionChanged) as error:
        raise_run_use_case_error(error)
    except ReportOutOfDateError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "report_out_of_date"},
        ) from exc
    except PdfFontUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "pdf_temporarily_unavailable",
                "message": "PDF 暂时无法生成，请稍后重试。",
            },
        ) from exc
    except BlockingWorkBusy as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "pdf_export_busy",
                "message": "正在导出的报告太多，稍后再试。",
            },
        ) from exc
    return Response(
        content=artifact.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-JourneyPilot-Bundle-ID": artifact.bundle_id,
            "X-JourneyPilot-Workspace-Revision": str(
                artifact.build_context.source_workspace_revision
            ),
            "X-JourneyPilot-Fact-Revision": str(
                artifact.build_context.source_fact_data_revision
            ),
            "X-JourneyPilot-Weather-Revision": str(
                artifact.build_context.source_weather_data_revision
            ),
        },
    )
