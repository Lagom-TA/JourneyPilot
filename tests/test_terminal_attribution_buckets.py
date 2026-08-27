"""终态归因前缀的单点化与桶归属穷举（评审条目 A11）。

``delivery_integrity`` 前缀原来在仓里有四种拼法：写点三次 f-string 拼、一次手抄同
文件已有常量的字面量、读点两次不带尾下划线的 ``startswith``，再加一个 store 兜底
默认值。这个文件钉三件事：

1. 七个 ``InternalFailureClass`` × 四个终态 status，``_terminal_bucket`` 各自返回
   什么 —— 今天落 ``None`` 的组合明确写成 ``is None``，**那是当前事实不是期望**。
2. store 那个兜底值 ``delivery_integrity_failure``（单数，不是任何
   ``InternalFailureClass`` 的值）今天照样落进 ``delivery_integrity_failed`` 桶，
   所以这个桶里混着「有具体分类」和「没给分类的兜底」两类 run。把这个不纯钉成
   可见事实，而不是留给下一个人在读度量报表时自己发现。
3. 未识别 reason code 的明细日志**每次 recompute 只打一行**。这段在逐 run 循环里
   跑、上面那个 developer/Eval 端点可能被前端轮询，逐 run 打就是一个放大器。
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from travel_agent.entities.delivery_bundle import InternalFailureClass
from travel_agent.entities.terminal_attribution import (
    DELIVERY_INTEGRITY_REASON_PREFIX,
    DELIVERY_INTEGRITY_UNCLASSIFIED_FALLBACK_REASON,
    delivery_integrity_reason_code,
)
from travel_agent.services.run_completion_metrics import (
    _terminal_bucket,
    recompute_completion_metrics,
)

_METRICS_LOGGER = "travel_agent.services.run_completion_metrics"

# ``_terminal_bucket`` 认的四个终态 status。``interrupted`` 不是它任何一个分支的
# 入参，列进来正是为了把「它落 None」写下来。
_TERMINAL_STATUSES = ("completed", "cancelled", "failed", "interrupted")


def _audit(
    *,
    closure_status: str,
    reason_code: str,
    eligible: bool = True,
) -> dict[str, Any]:
    audit: dict[str, Any] = {
        "planning_authorized_at": "2026-01-01T00:00:00+00:00",
        "terminal_attribution": {
            "closure_status": closure_status,
            "reason_code": reason_code,
        },
    }
    if eligible:
        audit["eligibility_contract"] = {
            "controlled_identity_valid": True,
            "constraint_revision_valid": True,
            "sealed_draft_valid": True,
            "formal_bundle_capable": True,
        }
    return audit


# ── 1. 七个失败分类 × 四个终态 status 穷举 ────────────────────────────────────


@pytest.mark.parametrize("failure_class", list(InternalFailureClass))
@pytest.mark.parametrize("status", _TERMINAL_STATUSES)
def test_terminal_bucket_for_every_failure_class_and_status(
    failure_class: InternalFailureClass, status: str
) -> None:
    reason_code = delivery_integrity_reason_code(failure_class)
    bucket = _terminal_bucket(
        status, _audit(closure_status=status, reason_code=reason_code)
    )

    if status == "failed":
        # 七个分类全部落同一个桶：桶只按前缀分，不按分类分。
        assert bucket == "delivery_integrity_failed"
    else:
        # 以下三条都是**当前事实，不是期望**：
        # - completed 分支只认 reason_code == "delivery_bundle_ready"
        # - cancelled 分支只认 reason_code == "user_cancelled"
        # - interrupted 不是任何一个分支的入参
        # 一个 delivery-integrity 的 reason code 配上非 failed 的终态，今天既不落桶
        # 也不属于任何已命名的结局，只会由 unclassified_terminal_count 兜住。
        assert bucket is None


def test_reason_codes_are_all_distinct_and_share_the_prefix() -> None:
    """七个分类各自造出不同的 reason code，且都带同一个前缀（否则第 1 条是空转的）。"""

    codes = {delivery_integrity_reason_code(fc) for fc in InternalFailureClass}
    assert len(codes) == len(list(InternalFailureClass)) == 7
    assert all(code.startswith(f"{DELIVERY_INTEGRITY_REASON_PREFIX}_") for code in codes)


# ── 2. store 兜底值：不纯，但今天照样落桶 ─────────────────────────────────────


def test_store_fallback_reason_lands_in_the_same_bucket() -> None:
    """``delivery_integrity_failure`` 不是任何 InternalFailureClass 的值，却同桶。

    它是 ``infrastructure/trip_run_store.py`` 在调用方没给 reason_code 时写下的兜底。
    读方只做 ``startswith``，所以 ``delivery_integrity_failed`` 桶里混着两类 run。
    这条断言不是在赞同这个设计，是在让它可见：改这个字符串的值会改度量输出。
    """

    assert DELIVERY_INTEGRITY_UNCLASSIFIED_FALLBACK_REASON not in {
        fc.value for fc in InternalFailureClass
    }
    assert DELIVERY_INTEGRITY_UNCLASSIFIED_FALLBACK_REASON not in {
        delivery_integrity_reason_code(fc) for fc in InternalFailureClass
    }
    assert (
        _terminal_bucket(
            "failed",
            _audit(
                closure_status="failed",
                reason_code=DELIVERY_INTEGRITY_UNCLASSIFIED_FALLBACK_REASON,
            ),
        )
        == "delivery_integrity_failed"
    )


# ── 另外两个桶的正对照：表格不是恒 None ───────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "reason_code", "expected"),
    [
        ("completed", "delivery_bundle_ready", "eligible_completed"),
        ("cancelled", "user_cancelled", "user_cancelled"),
    ],
)
def test_the_other_two_buckets_still_resolve(
    status: str, reason_code: str, expected: str
) -> None:
    assert (
        _terminal_bucket(status, _audit(closure_status=status, reason_code=reason_code))
        == expected
    )


# ── 3. 未识别明细日志：每次 recompute 一行 ────────────────────────────────────


def _detail(run_id: str, *, status: str, reason_code: str) -> dict[str, Any]:
    return {
        "run": {"run_id": run_id, "status": status},
        "state": {
            "completion_audit": _audit(closure_status=status, reason_code=reason_code)
        },
        "events": [],
    }


def test_unclassified_detail_is_one_aggregate_line_per_recompute(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """两个 run、两个未识别 reason code → **一行**汇总，不是两行。"""

    details = [
        _detail("run_a", status="failed", reason_code="mystery_one"),
        _detail("run_b", status="failed", reason_code="mystery_two"),
    ]
    with caplog.at_level(logging.WARNING, logger=_METRICS_LOGGER):
        metrics = recompute_completion_metrics(details)

    assert metrics.unclassified_terminal_count == 2
    lines = [r for r in caplog.records if r.name == _METRICS_LOGGER]
    assert len(lines) == 1, [r.getMessage() for r in lines]

    message = lines[0].getMessage()
    assert "mystery_one=1" in message
    assert "mystery_two=1" in message
    assert "2 unclassified terminal run(s) over 2 authorized" in message


def test_recognised_outcomes_log_nothing(caplog: pytest.LogCaptureFixture) -> None:
    """全部落桶时不打这行：一条恒发的 WARNING 等于没有信号。"""

    details = [
        _detail("run_a", status="completed", reason_code="delivery_bundle_ready"),
        _detail("run_b", status="cancelled", reason_code="user_cancelled"),
    ]
    with caplog.at_level(logging.WARNING, logger=_METRICS_LOGGER):
        metrics = recompute_completion_metrics(details)

    assert metrics.unclassified_terminal_count == 0
    assert [r for r in caplog.records if r.name == _METRICS_LOGGER] == []


def test_repeated_unclassified_reason_code_is_counted_not_repeated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """同一个未识别 reason code 出现三次：一行，计数 3。"""

    details = [
        _detail(f"run_{index}", status="failed", reason_code="mystery_one")
        for index in range(3)
    ]
    with caplog.at_level(logging.WARNING, logger=_METRICS_LOGGER):
        recompute_completion_metrics(details)

    lines = [r for r in caplog.records if r.name == _METRICS_LOGGER]
    assert len(lines) == 1
    assert "mystery_one=3" in lines[0].getMessage()
