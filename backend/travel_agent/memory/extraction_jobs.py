"""Memory extraction jobs."""

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
            "profile_revision_at_enqueue": payload.get("profile_revision"),
            "profile_revision_now": current_revision,
        }

    return handle


async def load_user_profile(user_profile_memory, user_id: str):
    """加载用户画像对象；取不到就是 ``None``。

    **这里不再拼任何「画像摘要」字符串。** 画像抵达模型的通道只有一条：
    Constraint Pack 的统一装配入口自己读取 ``UserProfileMemory``
    （``panels/constraint.py::_map_manual_profile`` 映六组偏好、``_auto_portrait_block``
    映系统画像）。此前这里还会把偏好与画像拼成一段散文塞进 state，只有快路径读它 ——
    于是同一份节奏 / 预算在快路径上是一句不参与仲裁的散文、在深度路径上是 pack 里可被
    preset 压过的一条 item，两条路各有各的赢家。路由这一侧现在只把对象交出去，
    唯一的读者是记忆抽取（它要 ``auto_portrait`` 当增量基线）。
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
    """把这一轮的记忆抽取排进 `background_jobs`。

    在聊天保存事务之后调用：任务只带引用，正文由 worker 从会话记录读回。画像基线随
    payload 固定，延迟几小时才执行的抽取不会改用另一版画像去判「这条已经知道了」。
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
