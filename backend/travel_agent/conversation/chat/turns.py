from __future__ import annotations
import logging
from travel_agent.runtime.local_identity import LOCAL_USER_ID
from travel_agent.utils.json_helpers import strip_think_blocks

from travel_agent.conversation.stream_text import (
    strip_non_display_blocks,
    strip_thinking_text,
)

logger = logging.getLogger(__name__)


class ChatTurns:
    """先持久化本轮对话，再调度记忆抽取；以 saved 标记避免重复保存。"""

    def __init__(
        self,
        *,
        chat_session_memory,
        presentation,
        run_id,
        session_id,
        mode,
        user_message,
        user_message_id,
        message_id,
        request_trip_identity,
    ):
        self.chat_session_memory = chat_session_memory
        self.presentation = presentation
        self.run_id = run_id
        self.session_id = session_id
        self.mode = mode
        self.user_message = user_message
        self.user_message_id = user_message_id
        self.message_id = message_id
        self.request_trip_identity = request_trip_identity
        self.saved = False

    async def save_partial(self, assistant_type: str) -> str:
        assistant_content = strip_non_display_blocks(
            strip_thinking_text(strip_think_blocks(self.presentation.full_response))
        )
        if not self.saved:
            await self.chat_session_memory.save_turn(
                session_id=self.session_id,
                user_id=LOCAL_USER_ID,
                mode=self.mode,
                user_message=self.user_message,
                user_message_id=self.user_message_id,
                assistant_message_id=self.message_id,
                assistant_content=assistant_content,
                assistant_display_content=assistant_content,
                assistant_type="normal",
                task_type=self.presentation.task_type or None,
                agent_name=self.presentation.final_agent_name,
                step_name=self.presentation.final_step_name,
                thinking_steps=self.presentation.thinking_steps,
                context_report=self.presentation.context_report,
                trip_summary_card=self.presentation.trip_summary_card,
                run_id=self.run_id,
                controlled_trip_identity=self.request_trip_identity,
            )
            self.saved = True
        return assistant_content

    async def save_success(self, assistant_content: str, assistant_type: str) -> None:
        await self.chat_session_memory.save_turn(
            session_id=self.session_id,
            user_id=LOCAL_USER_ID,
            mode=self.mode,
            user_message=self.user_message,
            user_message_id=self.user_message_id,
            assistant_message_id=self.message_id,
            assistant_content=assistant_content,
            assistant_display_content=assistant_content,
            assistant_type=assistant_type,
            task_type=self.presentation.task_type or None,
            agent_name=self.presentation.final_agent_name,
            step_name=self.presentation.final_step_name,
            thinking_steps=self.presentation.thinking_steps,
            context_report=self.presentation.context_report,
            trip_summary_card=self.presentation.trip_summary_card,
            run_id=self.run_id,
            controlled_trip_identity=self.request_trip_identity,
        )
        self.saved = True
