"""未知异常在 HTTP 边界的统一投影。

内部异常原文只写日志，不进入响应体：路径、DSN、Provider 片段和堆栈细节一旦
返回浏览器，就会被用户原样贴进 issue 或截图。
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def internal_server_error(
    exc: Exception,
    *,
    log_message: str,
    message: str = "服务暂时不可用，请稍后重试",
) -> HTTPException:
    """记录异常并返回固定文案的 500。"""

    logger.exception(log_message)
    return HTTPException(
        status_code=500,
        detail={"code": "internal_error", "message": message},
    )
