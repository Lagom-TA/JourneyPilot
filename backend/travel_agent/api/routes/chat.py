from __future__ import annotations
import logging
from typing import Any, AsyncIterator
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from travel_agent.bootstrap.registry import get_components
from travel_agent.conversation.chat.contracts import ChatRequest
from travel_agent.conversation.chat.preparation import (
    prepare_chat,
    ImmediateChat,
    check_input_guard,
)
from travel_agent.conversation.chat.execution import execute_chat
from travel_agent.conversation.prompt_optimization import optimize_travel_prompt
from travel_agent.api.chat_errors import raise_chat_preparation_error
from travel_agent.api.sse import sse_event as encode_sse_event
from travel_agent.api.sse_projection import project_sse_payload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])
_SSE_HEARTBEAT_FRAME = ": heartbeat\n\n"


async def present_chat_events(events: AsyncIterator[dict[str, Any] | None]):
    projection_error = None
    try:
        while True:
            try:
                if projection_error is None:
                    payload = await anext(events)
                else:
                    payload = await events.athrow(projection_error)
                    projection_error = None
            except StopAsyncIteration:
                return
            if payload is None:
                yield _SSE_HEARTBEAT_FRAME
                continue
            try:
                projected = project_sse_payload(payload)
                frame = encode_sse_event(projected) if projected is not None else ""
            except Exception as error:
                # 投影异常交回事件源抛出，由领域层现有终态/恢复路径处理。
                projection_error = error
                continue
            yield frame
    finally:
        await events.aclose()


@router.post(
    "/chat-stream",
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def chat_stream(
    request: ChatRequest,
):
    """
    流式聊天 API（SSE）。
    LangGraph 工作流逐节点 yield 更新，前端实时显示进度。
    事件类型：
      chat_start    - 会话开始
      thinking      - Supervisor 编排状态
      agent_progress - 深度模式 Worker 中间结果（展示在调研过程区，不追加到主消息）
      chat_chunk    - 最终输出 token（仅 synthesizer 或 fast_answer 直接回答）
      chat_complete - 会话完成
      error         - 错误
    """
    components = get_components()
    try:
        prepared = await prepare_chat(
            request,
            trip_run_store=components.trip_run_store,
            chat_session_memory=components.chat_session_memory,
            run_execution_store=components.run_execution_store,
            travel_workflow=components.travel_workflow,
            checkpointer=getattr(components, "checkpointer", None),
        )
    except Exception as error:
        raise_chat_preparation_error(error)
        raise AssertionError("unreachable")
    if isinstance(prepared, ImmediateChat):
        events = prepared.events
    else:
        events = execute_chat(
            request,
            prepared,
            trip_run_store=components.trip_run_store,
            chat_session_memory=components.chat_session_memory,
            user_profile_memory=components.user_profile_memory,
            travel_workflow=components.travel_workflow,
            fast_workflow=components.fast_workflow,
            run_command_store=components.run_command_store,
            delivery_bundle_store=components.delivery_bundle_store,
            background_job_worker=components.background_job_worker,
            cost_ledger_store=getattr(components, "cost_ledger_store", None),
            usage_recorder=getattr(components, "usage_recorder", None),
        )
    return StreamingResponse(
        present_chat_events(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/optimize-prompt")
async def optimize_prompt(request_body: dict):
    """
    提示词优化 API：使用 Fast 模型对用户输入的旅行提示词进行扩充和结构化优化。
    请求体：{ "prompt": string }
    成功返回：{ "optimized_prompt": string, "success": boolean, "error_message"?: string }
    依赖不可用时返回 503，不把服务故障当作业务失败返回。
    """
    prompt = (request_body.get("prompt") or "").strip()

    if len(prompt) < 4:
        return {
            "success": False,
            "optimized_prompt": "",
            "error_message": "提示词太短，请补充更多信息后重试",
        }

    # 与聊天入口共用同一 InputGuard，提示词优化不能绕过注入检查。
    guard_result = await check_input_guard(prompt)
    if guard_result.is_blocked:
        logger.warning("InputGuard blocked optimize-prompt: %s", guard_result.reason)
        return {
            "success": False,
            "optimized_prompt": "",
            "error_message": guard_result.blocked_reply
            or "请求未通过安全检查，请修改后重试",
        }
    try:
        return await optimize_travel_prompt(prompt, get_components().model_router)
    except Exception as e:
        logger.error(f"提示词优化失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=503, detail="优化服务暂时不可用，请稍后重试"
        ) from e
