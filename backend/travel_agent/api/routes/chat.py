from __future__ import annotations
import logging
from typing import Any, AsyncIterator
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from travel_agent.bootstrap.registry import get_components
from travel_agent.config.loader import get_settings
from travel_agent.conversation.chat.contracts import ChatRequest
from travel_agent.conversation.chat.preparation import (
    prepare_chat,
    ImmediateChat,
)
from travel_agent.conversation.chat.execution import execute_chat
from travel_agent.conversation.prompt_optimization import (
    inferred_preferences_text,
    optimize_travel_prompt,
    prepare_prompt_optimization,
)
from travel_agent.api.chat_errors import raise_chat_preparation_error
from travel_agent.api.schemas.chat import OptimizePromptRequest
from travel_agent.api.sse import sse_event as encode_sse_event
from travel_agent.api.sse_projection import project_sse_payload
from travel_agent.runtime.local_identity import LOCAL_USER_ID

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
    memory_revision_at_start = None
    if get_settings().embedding.enabled:
        try:
            memory_revision_at_start = await components.user_profile_memory.get_revision(LOCAL_USER_ID)
        except Exception as error:
            logger.warning("无法读取记忆版本，本轮不安排记忆抽取: %s", error)
    try:
        prepared = await prepare_chat(
            request,
            trip_run_store=components.trip_run_store,
            chat_session_memory=components.chat_session_memory,
            run_execution_store=components.run_execution_store,
            travel_workflow=components.travel_workflow,
            checkpointer=getattr(components, "checkpointer", None),
            delivery_bundle_store=components.delivery_bundle_store,
        )
    except Exception as error:
        raise_chat_preparation_error(error)
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
            memory_revision_at_start=memory_revision_at_start,
        )
    return StreamingResponse(
        present_chat_events(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/optimize-prompt")
async def optimize_prompt(request: OptimizePromptRequest):
    """
    提示词优化 API：使用 Fast 模型对用户输入的旅行提示词进行扩充和结构化优化。

    请求体由 ``OptimizePromptRequest`` 约束：过长、非字符串或缺字段返回 422。
    过短（<4）仍返回 200 + success=false 的内联提示；依赖不可用返回 503。
    """
    prompt, rejection = await prepare_prompt_optimization(request.prompt)
    if rejection is not None:
        return rejection
    try:
        components = get_components()
        return await optimize_travel_prompt(
            prompt,
            components.model_router,
            inferred_preferences=await inferred_preferences_text(
                components.user_profile_memory
            ),
        )
    except Exception as e:
        logger.error(f"提示词优化失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=503, detail="优化服务暂时不可用，请稍后重试"
        ) from e
