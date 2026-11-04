from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException

from travel_agent.planning.run_errors import (
    RunNotFound,
    RunNotCancellable,
    LockedIdentitySupplement,
    RunNotAcceptingSupplement,
    DeliveryBundleMissing,
    ReportRevisionChanged,
)


async def raise_bundle_revision_conflict(run_id: str, bundle_store) -> NoReturn:
    """仅根据头部元数据返回 CAS 冲突。

    冲突发生时 run 可能已处于异常状态，因此不再读取并重新投影持久化的 Bundle；
    响应告知客户端当前 Bundle id，由客户端通过当前 Bundle 路由重新读取。
    detail 结构与 ``report_out_of_date`` 一致。
    """
    current_bundle_id = await bundle_store.get_current_bundle_id(run_id)
    raise HTTPException(
        status_code=409,
        detail={
            "code": "bundle_revision_conflict",
            "current_bundle_id": current_bundle_id,
        },
    )


def raise_run_use_case_error(error: Exception) -> NoReturn:
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
            detail=(
                "请等待当前回复结束，再围绕已有行程发送新消息。"
                if error.has_delivery
                else "首份旅行方案交付前，不能在运行中追加要求。"
            ),
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
