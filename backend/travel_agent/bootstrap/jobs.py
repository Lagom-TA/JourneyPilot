"""把后台任务类型绑定到领域处理器。"""

from typing import Any, Dict

from travel_agent.memory.extraction_jobs import make_memory_extraction_handler
from travel_agent.runtime.background_jobs import JobHandler
from travel_agent.runtime.job_contracts import BackgroundJobType, coerce_job_type


def build_job_handlers(components: Any) -> Dict[BackgroundJobType, JobHandler]:
    """任务类型 → 处理器。新增类型时只改这一处。"""

    return {
        coerce_job_type(
            BackgroundJobType.MEMORY_EXTRACTION
        ): make_memory_extraction_handler(
            chat_session_memory=components.chat_session_memory,
            memory_extractor=components.memory_extractor,
            user_profile_memory=components.user_profile_memory,
        ),
    }
