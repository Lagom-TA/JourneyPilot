from __future__ import annotations
import logging
from travel_agent.memory.context_builder import ContextBudget
from travel_agent.conversation.chat.errors import (
    SessionAccessDenied,
    SessionHistoryUnavailable,
)

logger = logging.getLogger(__name__)


async def load_session_history(
    chat_session_memory,
    user_id: str,
    session_id: str,
    mode: str,
    title_seed: str,
    controlled_trip_identity,
    *,
    load_anchor: bool = False,
) -> tuple:
    """
    确保会话存在并加载近期消息。
    返回 (history, anchor_data_or_None, is_compressed)。

    `controlled_trip_identity` 原样转给 `ensure_session`，会话标题的判据在那里；
    本层不做解释。
    """
    try:
        await chat_session_memory.ensure_session(
            session_id=session_id,
            user_id=user_id,
            mode=mode,
            title_seed=title_seed,
            controlled_trip_identity=controlled_trip_identity,
        )

        history = await chat_session_memory.get_recent_messages_within_token_budget(
            user_id=user_id,
            session_id=session_id,
            token_budget=ContextBudget().compaction_trigger_tokens,
        )
        anchor_data = None
        is_compressed = False
        if load_anchor:
            anchor_raw, compression_count = await chat_session_memory.get_anchor(
                user_id=user_id,
                session_id=session_id,
            )
            anchor_data = anchor_raw
            is_compressed = compression_count > 0
        return history, anchor_data, is_compressed
    except PermissionError:
        raise SessionAccessDenied()
    except Exception as e:
        logger.error(f"会话历史加载失败: {e}", exc_info=True)
        raise SessionHistoryUnavailable()
