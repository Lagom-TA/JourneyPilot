from typing import NoReturn

from fastapi import HTTPException
from travel_agent.conversation.chat.errors import (
    PreparationRefused,
    PreparationRejection,
    SessionAccessDenied,
    SessionHistoryUnavailable,
    PresetNotFound,
    PresetUnavailable,
)

# 投影失败拒绝续跑时返回给前端的错误协议值，前端按这个字符串匹配引导文案。
_PROJECTION_FAILURE_REASON_CODE = "delivery_integrity_projection_failure"


def raise_chat_preparation_error(error: Exception) -> NoReturn:
    if isinstance(error, PreparationRefused):
        if error.reason is PreparationRejection.EMPTY_MESSAGE:
            raise HTTPException(status_code=400, detail="消息内容不能为空") from error
        if error.reason is PreparationRejection.ROUTE_UNAVAILABLE:
            raise HTTPException(
                status_code=503, detail="暂时无法理解你的意图，请重试"
            ) from error
        if error.reason is PreparationRejection.REFINEMENT_REQUIRES_RUN:
            raise HTTPException(
                status_code=422, detail="调整行程需要先完成一次规划"
            ) from error
        if error.reason is PreparationRejection.GATE_REQUIRES_RUN:
            raise HTTPException(
                status_code=400, detail="确认操作需要指定当前规划记录"
            ) from error
        if error.reason is PreparationRejection.GATE_REQUIRES_CHECKPOINT:
            raise HTTPException(
                status_code=409, detail="当前服务未启用进度保存，无法执行确认操作"
            ) from error
        if error.reason is PreparationRejection.PLAN_GATE_DISABLED:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "plan_gate_disabled",
                    "message": "当前服务未启用方案确认，完整规划暂不可用；旅行问答仍可继续。",
                },
            ) from error
        if error.reason is PreparationRejection.RUN_NOT_FOUND:
            raise HTTPException(status_code=404, detail="未找到这趟规划记录") from error
        if error.reason is PreparationRejection.IDENTITY_LOCKED:
            raise HTTPException(
                status_code=409,
                detail="基础旅行身份已锁定。请先结束当前规划，再新建旅行。",
            ) from error
        if error.reason is PreparationRejection.RUN_STATUS_NOT_CONTINUABLE:
            raise HTTPException(
                status_code=409,
                detail=f"当前规划状态不可继续：{error.current_status}",
            ) from error
        if error.reason is PreparationRejection.GATE_DECISION_REQUIRED:
            raise HTTPException(
                status_code=409,
                detail="当前规划正在等待你的确认，请先提交确认结果",
            ) from error
        if error.reason is PreparationRejection.GATE_NODE_REQUIRED:
            raise HTTPException(
                status_code=409, detail="当前规划不在等待确认的步骤"
            ) from error
        if error.reason is PreparationRejection.PROJECTION_FAILURE:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": _PROJECTION_FAILURE_REASON_CODE,
                    "message": "上次规划的结果无法生成可展示的方案，继续规划会得到相同结果。请重新规划这趟旅行。",
                },
            ) from error
        if error.reason is PreparationRejection.RESUME_REQUIRES_CHECKPOINT:
            raise HTTPException(
                status_code=409, detail="当前服务未启用进度保存，无法继续上次规划"
            ) from error
        if error.reason is PreparationRejection.RUN_NOT_RESUMABLE:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "run_not_resumable",
                    "message": "上次规划没有可继续的进度，请重新规划这趟旅行。",
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
                status_code=409, detail="未找到可继续的规划进度，请重新规划这趟旅行"
            ) from error
        if error.reason is PreparationRejection.RESUME_STATUS_RACE:
            raise HTTPException(
                status_code=409, detail="这趟规划已在其他请求中继续或状态已变化"
            ) from error
        if error.reason is PreparationRejection.GATE_STATUS_NOT_CONTINUABLE:
            raise HTTPException(
                status_code=409, detail="当前规划状态不可提交确认结果"
            ) from error
        if error.reason is PreparationRejection.GATE_VERSION_STALE:
            detail: dict = {
                "code": "plan_gate_version_stale",
                "message": "确认信息缺失或已过期，请刷新后查看最新进展再回答。",
            }
            if error.current_revision is not None:
                detail["current_revision"] = error.current_revision
            raise HTTPException(status_code=409, detail=detail) from error
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
                "message": "这趟旅行正在其他页面或窗口中规划，请刷新后查看当前状态。",
            },
        ) from error
    raise error
