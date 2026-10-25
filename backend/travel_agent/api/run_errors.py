from __future__ import annotations
from fastapi import HTTPException
from travel_agent.storage.delivery_bundle_store import BundleContractSuperseded

from travel_agent.planning.run_errors import (
    RunNotFound,
    RunNotCancellable,
    LockedIdentitySupplement,
    RunNotAcceptingSupplement,
    DeliveryBundleMissing,
    ReportRevisionChanged,
)


async def raise_workspace_mutation_conflict(run_id: str, bundle_store) -> None:
    """Answer a lost CAS race from head metadata alone.

    A conflict response is most needed when the run is already in an unexpected
    state, so it must not re-read and re-project the persisted Bundle: the client
    is told which Bundle is current and re-reads it through the current-Bundle
    route.  Same detail shape as ``report_out_of_date``.
    """
    current_bundle_id = await bundle_store.get_current_bundle_id(run_id)
    raise HTTPException(
        status_code=409,
        detail={
            "code": "bundle_revision_conflict",
            "current_bundle_id": current_bundle_id,
        },
    )


def raise_bundle_contract_superseded(exc: BundleContractSuperseded) -> None:
    """Refuse a stored Bundle the current contract no longer describes.

    A refusal, not a fallback.  Reading the old shape "just for this run" would be a
    compatibility layer; what such a row needs is a data decision, taken once, not a
    second code path.  The client is told the plain fact so it stops asking —
    re-reading returns the same answer, so no automatic resync.
    """

    raise HTTPException(
        status_code=409,
        detail={
            "code": "bundle_contract_superseded",
            "message": "这趟旅行的结果是用旧版本保存的，已经无法展示。请重新规划这趟旅行。",
        },
    ) from exc


def raise_run_use_case_error(error: Exception) -> None:
    if isinstance(error, RunNotFound):
        raise HTTPException(status_code=404, detail="TripRun 不存在") from error
    if isinstance(error, RunNotCancellable):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "run_not_cancellable",
                "message": "这次运行已经结束，无法再停止。请刷新后查看当前状态。",
                "status": error.current_status,
            },
        ) from error
    if isinstance(error, LockedIdentitySupplement):
        raise HTTPException(
            status_code=409,
            detail="基础旅行身份已锁定。请结束当前草稿或运行，再新建旅行。",
        ) from error
    if isinstance(error, RunNotAcceptingSupplement):
        raise HTTPException(
            status_code=409,
            detail="当前不在运行中；请在旅行简报的调研计划区域追加要求。",
        ) from error
    if isinstance(error, DeliveryBundleMissing):
        raise HTTPException(
            status_code=404, detail="当前 Delivery Bundle 不存在"
        ) from error
    if isinstance(error, ReportRevisionChanged):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "report_out_of_date",
                "current_bundle_id": error.current_bundle_id,
            },
        ) from error
    raise error
