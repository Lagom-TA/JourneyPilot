"""记忆抽取后台任务。"""

from __future__ import annotations

from travel_agent.config.loader import get_settings

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

    任务按至少一次投递（例如标记 completed 前崩溃会重跑），因此幂等由业务写入
    这一侧保证，不能假定任务只消费一次。
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
            "profile_revision_at_enqueue": payload.get("profile_revision"),
            "profile_revision_now": current_revision,
        }

    return handle


async def load_user_profile(user_profile_memory, user_id: str):
    """加载用户画像对象；取不到时返回 None。

    画像抵达模型的唯一通道是 Constraint Pack 的统一装配入口
    （``panels/constraint.py`` 中 ``_map_manual_profile`` 映射六组偏好、
    ``_auto_portrait_block`` 映射系统画像）。本函数只返回画像对象，
    供记忆抽取作为 ``auto_portrait`` 增量基线。
    """
    try:
        return await user_profile_memory.get_user_profile(user_id)
    except Exception as e:
        logger.warning(f"加载用户画像失败: {e}")
        return None


async def enqueue_memory_extraction(
    *,
    user_id: str,
    session_id: str,
    user_message: str,
    user_message_id: str,
    assistant_message_id: str,
    profile_revision: int,
    portrait_baseline: str,
    background_job_worker=None,
) -> None:
    """把本轮的记忆抽取排入 `background_jobs`。

    在聊天保存事务之后调用：任务只保存引用，正文由 worker 从会话记录读回。
    画像基线随 payload 固定，延迟执行的抽取仍使用入队时的画像版本。
    """
    if not get_settings().embedding.enabled:
        return
    if not user_message or not user_message_id:
        return
    from travel_agent.runtime.job_contracts import BackgroundJobType
    from travel_agent.storage.background_job_store import get_background_job_store

    try:
        await get_background_job_store().enqueue(
            BackgroundJobType.MEMORY_EXTRACTION,
            memory_extraction_dedupe_key(session_id, assistant_message_id),
            {
                "user_id": user_id,
                "session_id": session_id,
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "profile_revision": profile_revision,
                "portrait_baseline": portrait_baseline,
            },
        )
    except Exception as e:
        logger.warning(f"记忆抽取入队失败: {e}")
        return
    if background_job_worker is not None:
        background_job_worker.notify()
