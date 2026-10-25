from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from travel_agent.bootstrap.registry import get_components
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2MutationError
from travel_agent.storage.delivery_bundle_store import (
    BundleContractSuperseded,
    BundleIdempotencyMismatch,
    BundleRevisionConflict,
    BundleRevisionVector,
)
from travel_agent.planning.delivery.workspace_mutations import WorkspaceV2Service
from travel_agent.api.schemas.delivery import PublicDeliveryBundleResponse
from travel_agent.api.schemas.workspace import (
    WorkspaceV2MutationImpactResponse,
    WorkspaceV2MutationPreviewResponse,
    WorkspaceV2MutationRequest,
    WorkspaceV2MutationResponse,
    WorkspaceV2UndoHeadResponse,
    WorkspaceV2UndoRequest,
    WorkspaceV2UndoResponse,
)
from travel_agent.planning.delivery.public.bundle import public_delivery_bundle

from travel_agent.api.run_authorization import _get_authorized_run
from travel_agent.api.run_errors import (
    raise_workspace_mutation_conflict,
    raise_bundle_contract_superseded,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trip-runs", tags=["trip-runs"])


def _workspace_expected(request: WorkspaceV2MutationRequest) -> BundleRevisionVector:
    return BundleRevisionVector(
        workspace_revision=request.base_workspace_revision,
        fact_data_revision=request.base_fact_data_revision,
        weather_data_revision=request.base_weather_data_revision,
        bundle_id=request.base_bundle_id,
    )


def _undo_expected(request: WorkspaceV2UndoRequest) -> BundleRevisionVector:
    return BundleRevisionVector(
        workspace_revision=request.base_workspace_revision,
        fact_data_revision=request.base_fact_data_revision,
        weather_data_revision=request.base_weather_data_revision,
        bundle_id=request.base_bundle_id,
    )


@router.post(
    "/{run_id}/workspace/mutations/preview",
    response_model=WorkspaceV2MutationPreviewResponse,
)
async def preview_workspace_v2_mutation(
    run_id: str,
    request: WorkspaceV2MutationRequest,
) -> WorkspaceV2MutationPreviewResponse:
    components = get_components()
    await _get_authorized_run(run_id, session_id=request.session_id)
    service = WorkspaceV2Service(components.delivery_bundle_store)
    try:
        preview = await service.preview(
            run_id=run_id,
            expected=_workspace_expected(request),
            mutation=request.operation,
        )
    except BundleContractSuperseded as exc:
        raise_bundle_contract_superseded(exc)
        raise AssertionError("unreachable")
    except BundleRevisionConflict:
        await raise_workspace_mutation_conflict(
            run_id, components.delivery_bundle_store
        )
        raise AssertionError("unreachable")
    except WorkspaceV2MutationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    impacts: list[WorkspaceV2MutationImpactResponse] = []
    if preview.total_cost_delta_cny not in (None, 0.0):
        delta = preview.total_cost_delta_cny
        direction = "增加" if delta > 0 else "减少"
        impacts.append(
            WorkspaceV2MutationImpactResponse(
                kind="total_cost",
                delta_cny=delta,
                summary=f"行程预计总费用{direction} ¥{abs(delta):.0f}",
            )
        )
    return WorkspaceV2MutationPreviewResponse(
        mutation_id=request.mutation_id,
        changed=preview.application.changed,
        requires_confirmation=preview.requires_confirmation,
        impacts=impacts,
    )


@router.post(
    "/{run_id}/workspace/mutations",
    response_model=WorkspaceV2MutationResponse,
)
async def apply_workspace_v2_mutation(
    run_id: str,
    request: WorkspaceV2MutationRequest,
) -> WorkspaceV2MutationResponse:
    components = get_components()
    await _get_authorized_run(run_id, session_id=request.session_id)
    service = WorkspaceV2Service(components.delivery_bundle_store)
    try:
        result = await service.apply(
            run_id=run_id,
            expected=_workspace_expected(request),
            mutation=request.operation,
            idempotency_key=request.mutation_id,
        )
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
                "code": "mutation_id_reused",
                "message": "这次调整的标识已用于另一项操作。",
            },
        ) from exc
    except WorkspaceV2MutationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    if result.commit is None:
        try:
            bundle = await components.delivery_bundle_store.get_current(run_id)
        except BundleContractSuperseded as exc:
            raise_bundle_contract_superseded(exc)
            raise AssertionError("unreachable")
        if bundle is None:
            raise HTTPException(status_code=404, detail="当前 Delivery Bundle 不存在")
        replay = False
    else:
        bundle = result.commit.bundle
        replay = result.commit.idempotent_replay
    return WorkspaceV2MutationResponse(
        mutation_id=request.mutation_id,
        changed=result.application.changed,
        idempotent_replay=replay,
        bundle=PublicDeliveryBundleResponse.model_validate(
            public_delivery_bundle(bundle)
        ),
    )


@router.get(
    "/{run_id}/workspace/mutations/{mutation_id}",
    response_model=WorkspaceV2MutationResponse,
)
async def read_workspace_v2_mutation(
    run_id: str,
    mutation_id: str,
    session_id: Optional[str] = Query(default=None),
) -> WorkspaceV2MutationResponse:
    components = get_components()
    await _get_authorized_run(run_id, session_id=session_id)
    try:
        record = await components.delivery_bundle_store.get_commit(run_id, mutation_id)
    except BundleContractSuperseded as exc:
        raise_bundle_contract_superseded(exc)
        raise AssertionError("unreachable")
    if record is None or "mutation" not in record.metadata:
        raise HTTPException(status_code=404, detail="行程调整记录不存在")
    return WorkspaceV2MutationResponse(
        mutation_id=mutation_id,
        changed=record.metadata.get("mutation_outcome") != "no_op",
        idempotent_replay=True,
        bundle=PublicDeliveryBundleResponse.model_validate(
            public_delivery_bundle(record.result.bundle)
        ),
    )


@router.get(
    "/{run_id}/workspace/undo-head",
    response_model=WorkspaceV2UndoHeadResponse,
)
async def read_workspace_v2_undo_head(
    run_id: str,
    session_id: Optional[str] = Query(default=None),
) -> WorkspaceV2UndoHeadResponse:
    components = get_components()
    await _get_authorized_run(run_id, session_id=session_id)
    head = await components.delivery_bundle_store.get_undo_head(run_id)
    if head is None:
        return WorkspaceV2UndoHeadResponse(available=False)
    return WorkspaceV2UndoHeadResponse(
        available=True,
        mutation_id=head.mutation_id,
        label=head.label,
    )


@router.post(
    "/{run_id}/workspace/undo",
    response_model=WorkspaceV2UndoResponse,
)
async def undo_workspace_v2_mutation(
    run_id: str,
    request: WorkspaceV2UndoRequest,
) -> WorkspaceV2UndoResponse:
    components = get_components()
    await _get_authorized_run(run_id, session_id=request.session_id)
    service = WorkspaceV2Service(components.delivery_bundle_store)
    try:
        result = await service.undo_current(
            run_id=run_id,
            expected=_undo_expected(request),
            undo_of_mutation_id=request.undo_of_mutation_id,
            idempotency_key=request.undo_id,
        )
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
                "code": "undo_id_reused",
                "message": "这次撤销的标识已用于另一项操作。",
            },
        ) from exc
    except WorkspaceV2MutationError as exc:
        if exc.code == "undo_head_changed":
            current_bundle_id = (
                await components.delivery_bundle_store.get_current_bundle_id(run_id)
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": exc.code,
                    "message": "行程已更新，请重新加载后重试。",
                    "current_bundle_id": current_bundle_id,
                },
            ) from exc
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return WorkspaceV2UndoResponse(
        undo_id=request.undo_id,
        idempotent_replay=result.idempotent_replay,
        bundle=PublicDeliveryBundleResponse.model_validate(
            public_delivery_bundle(result.bundle)
        ),
    )
