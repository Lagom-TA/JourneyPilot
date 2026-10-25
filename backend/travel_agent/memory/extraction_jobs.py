"""Memory extraction jobs."""

from __future__ import annotations

from travel_agent.runtime.job_contracts import BackgroundJob
from travel_agent.runtime.job_contracts import BackgroundJobPermanentError
from typing import Any
from typing import Dict
from typing import Optional
import hashlib
import logging


def memory_extraction_dedupe_key(session_id: str, assistant_message_id: str) -> str:
    """一轮对话一个任务：同一轮重发不会排出第二个抽取。"""

    return f"{session_id}:{assistant_message_id}"


def memory_fact_digest(user_id: str, source_message_id: str, content: str) -> str:
    """同一条来源消息抽出的同一句事实只入库一次。

    重复消费是 at-least-once 的常态（标记 completed 之前崩溃），所以幂等必须落在
    业务写入这一侧，不能指望「job 只会消费一次」。
    """

    material = "\x00".join([user_id, source_message_id, " ".join(content.split())])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


logger = logging.getLogger(__name__)


def make_memory_extraction_handler(
    *,
    chat_session_memory: Any,
    memory_extractor: Any,
    user_profile_memory: Any,
):
    async def handle(job: BackgroundJob) -> Optional[Dict[str, Any]]:
        payload = job.payload or {}
        user_id = str(payload.get("user_id") or "")
        session_id = str(payload.get("session_id") or "")
        user_message_id = str(payload.get("user_message_id") or "")
        if not (user_id and session_id and user_message_id):
            raise BackgroundJobPermanentError("invalid_payload", "抽取任务缺少来源引用")

        user_message = await chat_session_memory.get_message_content(
            session_id=session_id,
            message_id=user_message_id,
        )
        if user_message is None:
            raise BackgroundJobPermanentError(
                "source_message_deleted", "来源消息已不存在"
            )

        outcome = await memory_extractor.extract_from_turn(
            user_id=user_id,
            session_id=session_id,
            user_msg=user_message,
            existing_portrait=str(payload.get("portrait_baseline") or ""),
            source_message_id=user_message_id,
        )

        current_revision = await user_profile_memory.get_revision(user_id)
        return {
            "facts": outcome.facts_written,
            "portraits": outcome.portraits_written,
            "rejections": outcome.rejections,
            "profile_revision_at_enqueue": payload.get("profile_revision"),
            "profile_revision_now": current_revision,
        }

    return handle
