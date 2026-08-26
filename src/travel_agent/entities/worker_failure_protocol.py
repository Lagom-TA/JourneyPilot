"""Worker ``last_error`` 前缀常量表 —— 零仓内依赖的叶子模块。

前缀协议的常量真源。写方 ``agents/worker_errors.format_worker_last_error``
把 worker 失败写进 ``TravelAgentState.last_error``，输出形状是
``f"{PREFIX} {text}"``（前缀后恰好一个空格）；读方
``agents/orchestrator/provider_failure`` 的 ``classify_provider_failure`` 与
``is_provider_or_model_failure`` 用同一批常量判类。此前常量定义在写方、
读方在依赖方向的上游够不着，只能把字面量重敲十份；这张叶子让写读两方
从同一处取词，方向问题到此为止。

前缀随 checkpoint 落盘，是持久化格式：字符串值逐字符不许变，历史
Run 的 ``last_error`` 还带着旧值等读方认。新增或改动前缀必须先过
``tests/test_worker_error_protocol_contract.py`` 钉住的读方结论。

纯数据表：不承载任何逻辑、校验或派生函数，不导入任何 travel_agent 模块。
"""

from typing import Final

PREFIX_SCHEMA_GATE: Final = "schema_gate:"
PREFIX_PROVIDER_EMPTY: Final = "provider_empty:"
PREFIX_PROVIDER_CAPABILITY: Final = "provider_capability:"
PREFIX_PROVIDER_TRANSIENT: Final = "provider_transient:"
PREFIX_PROVIDER_DETERMINISTIC: Final = "provider_deterministic:"
PREFIX_WORKER_FAILED: Final = "worker_failed:"

KNOWN_PREFIXES: Final = (
    PREFIX_SCHEMA_GATE,
    PREFIX_PROVIDER_EMPTY,
    PREFIX_PROVIDER_CAPABILITY,
    PREFIX_PROVIDER_TRANSIENT,
    PREFIX_PROVIDER_DETERMINISTIC,
    PREFIX_WORKER_FAILED,
)
