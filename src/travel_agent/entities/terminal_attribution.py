"""终态归因 reason code 的单点定义。

``delivery_integrity`` 这个前缀原来在仓里有四种拼法：三个写点各自 f-string 拼一遍、
一个写点手抄同文件已有常量的字面量、两个读点用不带尾下划线的 ``startswith`` 匹配、
再加一个 store 兜底默认值。任何一处改了拼法，度量的桶归属就静默错位 —— 没有编译器
会替你发现两个字符串本来该是同一个。

所以这里只放两样东西：读方匹配用的前缀，和由 ``InternalFailureClass`` 造 reason code
的函数。**分隔符属于函数，不属于常量**：常量就是 ``startswith`` 要匹配的那个前缀，
不带尾下划线；函数负责在前缀和失败分类之间补上 ``_``。两边都带下划线会让读方多匹配
一层，两边都不带会让写点拼出 ``delivery_integrityresearch_gap``。
"""

from __future__ import annotations

from .delivery_bundle import InternalFailureClass

# 读方（``services/run_completion_metrics.py``）拿它做 ``startswith``，所以不带尾下划线。
DELIVERY_INTEGRITY_REASON_PREFIX = "delivery_integrity"

# ``infrastructure/trip_run_store.py`` 在调用方没给 reason_code 时用的兜底值。
# 它**不是** ``InternalFailureClass`` 的任何一个值 —— 单数的 ``failure`` 在那个枚举里
# 不存在。但它以上面那个前缀开头，所以今天会被读方的 ``startswith`` 命中，
# ``delivery_integrity_failed`` 这个桶里因此混着两类 run：有具体失败分类的，和根本
# 没给分类的兜底。改这个字符串的值会改度量输出，是独立的行为票，不在本条范围内。
DELIVERY_INTEGRITY_UNCLASSIFIED_FALLBACK_REASON = "delivery_integrity_failure"


def delivery_integrity_reason_code(failure_class: InternalFailureClass) -> str:
    """由失败分类造终态 reason code，例如 ``delivery_integrity_research_gap``。"""
    return f"{DELIVERY_INTEGRITY_REASON_PREFIX}_{failure_class.value}"


__all__ = [
    "DELIVERY_INTEGRITY_REASON_PREFIX",
    "DELIVERY_INTEGRITY_UNCLASSIFIED_FALLBACK_REASON",
    "delivery_integrity_reason_code",
]
