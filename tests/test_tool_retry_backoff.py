"""工具重试退避序列的守卫测试（评审条目 B8）。

守卫的价值在于不复用被守卫的那条推导：期望序列写死字面值，
任何对 ``_tool_retry_backoff_seconds`` 公式的改动都会在这里红。
"""

from __future__ import annotations

from travel_agent.agents.utils import _tool_retry_backoff_seconds


def test_backoff_sequence_matches_pinned_defaults() -> None:
    expected = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
    assert [_tool_retry_backoff_seconds(a) for a in range(6)] == expected


def test_backoff_is_pure_no_jitter() -> None:
    # 今天没有 jitter：同一个 attempt 多次调用必须返回同一个值。
    # 将来若引入随机抖动，这条断言会红——那是应该被看见的行为变更。
    for attempt in range(6):
        first = _tool_retry_backoff_seconds(attempt)
        assert _tool_retry_backoff_seconds(attempt) == first
        assert _tool_retry_backoff_seconds(attempt) == first
