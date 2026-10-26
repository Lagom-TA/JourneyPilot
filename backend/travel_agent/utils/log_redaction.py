"""当凭证出现在 URL 中时，把它从日志里去掉。

部分 Web API 只接受查询参数中的 key，没有 header 形式，例如 amap 的 Directions
端点。``httpx`` 每个请求写一行 INFO 日志并带上完整 URL，这类请求一旦发出，key
就会以明文进入 ``backend.log``，而日志会被检索、tail 和粘贴到报告中。

脱敏做成 ``httpx`` logger 上的过滤器，而不是在每个调用点处理：格式化这些日志行
的位置只有一处，在该处应用规则不会被下一个使用查询参数鉴权的 Provider 遗漏。
生成带密钥 URL 的模块应在 import 时调用 :func:`install_query_secret_redaction`，
使过滤器在首次请求之前安装，覆盖服务、脚本与测试等入口。

import 时的调用是必要的，不能移到应用的 logging 配置中：脚本、单元测试或直接调用
工具时不经过入口，若 Provider 模块没有自行安装过滤器，key 会以明文写入日志。
logging 入口也会安装该过滤器；函数按 logger 名称幂等，第二次调用为空操作，
过滤器不会重复叠加。
"""

from __future__ import annotations

import logging
import re

# ``key`` 是 amap，``ak`` 是百度，其余是常见写法。匹配锚定在查询参数边界上，
# 路径段中恰好包含这些词时不会被替换。
_QUERY_SECRET = re.compile(
    r"((?:\?|&)(?:key|ak|token|api_?key|access_?token|secret)=)[^&\s\"]+",
    re.IGNORECASE,
)
_REDACTED = r"\1<redacted>"

_INSTALLED_LOGGERS: set[str] = set()


def redact_query_secrets(text: str) -> str:
    """替换所有形似凭证的查询参数值。"""
    return _QUERY_SECRET.sub(_REDACTED, text)


class _QuerySecretFilter(logging.Filter):
    """重写日志记录 message 与 args 中的凭证查询值。

    ``httpx`` 把 URL 作为 ``%s`` 参数传入，而不是拼进 ``msg``，因此两处都要处理。
    映射形式的 ``args`` 不做修改：该 logger 不产生这种形状，盲目改写可能破坏调用方
    自己的键。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and "=" in record.msg:
            record.msg = redact_query_secrets(record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(
                redact_query_secrets(str(value))
                if isinstance(value, str) or type(value).__name__ == "URL"
                else value
                for value in args
            )
        return True


def install_query_secret_redaction(logger_name: str = "httpx") -> None:
    """按进程在 ``logger_name`` 上安装一次脱敏过滤器。"""
    if logger_name in _INSTALLED_LOGGERS:
        return
    logging.getLogger(logger_name).addFilter(_QuerySecretFilter())
    _INSTALLED_LOGGERS.add(logger_name)
