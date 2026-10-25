from fastapi import HTTPException
from travel_agent.conversation.chat.errors import (
    PreparationRefused,
    PreparationRejection,
    SessionAccessDenied,
    SessionHistoryUnavailable,
    PresetNotFound,
    PresetUnavailable,
)
from travel_agent.planning.terminal_reasons import delivery_integrity_reason_code
from travel_agent.planning.outcomes import InternalFailureClass

_PROJECTION_FAILURE_REASON_CODE = delivery_integrity_reason_code(
    InternalFailureClass.PROJECTION_FAILURE
)


def raise_chat_preparation_error(error: Exception) -> None:
    if isinstance(error, PreparationRefused):
        if error.reason is PreparationRejection.EMPTY_MESSAGE:
            raise HTTPException(status_code=400, detail="消息内容不能为空") from error
        if error.reason is PreparationRejection.ROUTE_UNAVAILABLE:
            raise HTTPException(
                status_code=503, detail="暂时无法判断这句话要走哪条处理路径，请重试"
            ) from error
        if error.reason is PreparationRejection.REFINEMENT_REQUIRES_RUN:
            raise HTTPException(
                status_code=422, detail="调整行程需要已有 TripRun"
            ) from error
        if error.reason is PreparationRejection.GATE_REQUIRES_RUN:
            raise HTTPException(
                status_code=400, detail="gate_decision 需要提供 run_id"
            ) from error
        if error.reason is PreparationRejection.GATE_REQUIRES_CHECKPOINT:
            raise HTTPException(
                status_code=409, detail="当前服务未启用 checkpoint，无法使用计划审批门"
            ) from error
        if error.reason is PreparationRejection.RUN_NOT_FOUND:
            raise HTTPException(status_code=404, detail="TripRun 不存在") from error
        if error.reason is PreparationRejection.IDENTITY_LOCKED:
            raise HTTPException(
                status_code=409,
                detail="基础旅行身份已锁定。请结束当前草稿或运行，再新建旅行。",
            ) from error
        if error.reason is PreparationRejection.RUN_STATUS_NOT_CONTINUABLE:
            raise HTTPException(
                status_code=409,
                detail=f"TripRun 当前状态不可继续: {error.current_status}",
            ) from error
        if error.reason is PreparationRejection.GATE_DECISION_REQUIRED:
            raise HTTPException(
                status_code=409,
                detail="TripRun 正在等待审批门决策，需携带 gate_decision 断点续跑",
            ) from error
        if error.reason is PreparationRejection.GATE_NODE_REQUIRED:
            raise HTTPException(
                status_code=409, detail="TripRun 当前节点不是可提交审批决策的断点"
            ) from error
        if error.reason is PreparationRejection.PROJECTION_FAILURE:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": _PROJECTION_FAILURE_REASON_CODE,
                    "message": "这次运行的结果无法生成可展示的方案，断点续跑会得到同一个结果。请重新规划这趟旅行。",
                },
            ) from error
        if error.reason is PreparationRejection.RESUME_REQUIRES_CHECKPOINT:
            raise HTTPException(
                status_code=409, detail="当前服务未启用 checkpoint，无法断点续跑"
            ) from error
        if error.reason is PreparationRejection.RUN_NOT_RESUMABLE:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "run_not_resumable",
                    "message": "上次运行没有可继续的检查点，请重新规划这趟旅行。",
                },
            ) from error
        if error.reason is PreparationRejection.CHECKPOINT_CONTRACT_MISMATCH:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "checkpoint_contract_mismatch",
                    "message": error.explanation,
                },
            ) from error
        if error.reason is PreparationRejection.CHECKPOINT_NOT_FOUND:
            raise HTTPException(
                status_code=409, detail="未找到该 TripRun 的 checkpoint，无法断点续跑"
            ) from error
        if error.reason is PreparationRejection.RESUME_STATUS_RACE:
            raise HTTPException(
                status_code=409, detail="TripRun 已被其他请求恢复或状态已变化"
            ) from error
        if error.reason is PreparationRejection.GATE_STATUS_NOT_CONTINUABLE:
            raise HTTPException(
                status_code=409, detail="TripRun 当前状态不可提交计划审批决策"
            ) from error
    if isinstance(error, SessionAccessDenied):
        raise HTTPException(status_code=403, detail="无权访问该会话") from error
    if isinstance(error, SessionHistoryUnavailable):
        raise HTTPException(status_code=500, detail="会话历史服务不可用") from error
    if isinstance(error, PresetNotFound):
        raise HTTPException(
            status_code=404, detail="选择的旅行风格不存在或无权访问，请重新选择"
        ) from error
    if isinstance(error, PresetUnavailable):
        raise HTTPException(
            status_code=500, detail="加载旅行风格失败，请稍后重试"
        ) from error
    from travel_agent.conversation.chat.errors import ExecutionAlreadyOwned

    if isinstance(error, ExecutionAlreadyOwned):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "run_already_executing",
                "message": "这次运行正在别处执行，请刷新后查看当前状态。",
            },
        ) from error
    raise error
