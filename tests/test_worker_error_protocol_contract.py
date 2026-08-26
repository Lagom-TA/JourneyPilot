"""``last_error`` 前缀协议：写方格式与两个读方结论的现状刻画。

**不需要 PostgreSQL**：本文件是跨模块契约守卫，只用可 import 的真源
（参照 `tests/test_run_command_contract.py` 的 docstring 约定）。

协议现状（以本测试钉住的为准）：

- 写方只有一处：``agents/worker_errors.format_worker_last_error``，输出
  ``f"{PREFIX} {text}"`` —— **前缀后有一个空格**。前缀随 checkpoint 落盘，
  是持久化格式，逐字符不许变。
- 读方有两个：``agents/orchestrator/provider_failure.classify_provider_failure``
  与 ``is_provider_or_model_failure``。四道门（``artifact_gate.py:212/228/246``、
  ``candidate_gate.py:1706``）全部先过 ``is_provider_or_model_failure`` 再进
  ``classify_provider_failure``。

``classify_provider_failure`` 是**双用途函数**，改它的人必须知道有两类输入：

- 输入 A：``state.last_error``，带六个前缀之一（前缀只由
  ``format_worker_last_error`` 加、只加在 last_error 上）。本文件的
  前缀用例钉的就是这一路。
- 输入 B：永远不带前缀的自由文本 —— ``candidate_gate.py:211`` 传的
  ``source.snapshot["error"]`` / ``degradation_reason``，以及
  ``research_packet_output.py:93`` 传的 repair 模型调用异常文本。它们只能走
  ``classify_provider_failure`` 后半段的 free-text 分支；前缀分支的任何改动
  都不得以「输入 B 反正不带前缀」为由忽视这批调用方。

已知缺陷在此按**当前值**钉住，钉的是现状不是背书：

- ``worker_failed:`` 对四道门不可见：它不在 ``_EXPLICIT_EXTERNAL_FAILURE_MARKERS``
  里，``is_provider_or_model_failure`` 先行返回 False，门根本不进分类；带它的
  文本落进 free-text 扫描，分类由残留异常文本里碰巧含什么词决定。它唯一真正
  生效的地方是 ``worker_errors._already_prefixed``（防二次加前缀）。
- 三份裸写路径不经 ``format_worker_last_error``：``run_control.py:721-726``、
  ``itinerary_planner/node.py:3010``、``itinerary_planner/node.py:3731``。
- 两份 query-miss 词表刻意不同：写方三条、读方一条。读方注释
  （``provider_failure.py:24-26``）自陈这是刻意收缩——权威信号是
  ``provider_empty:`` 前缀，读方词表只兜 Provider 自己措辞的空结果。这份
  刻意收缩不许悄悄漂移（钉住差集），但也不预设两份该合并（合并是行为决策）。
"""

from __future__ import annotations

import pytest

from travel_agent.agents import worker_errors
from travel_agent.agents.orchestrator import provider_failure
from travel_agent.agents.orchestrator.provider_failure import (
    classify_provider_failure,
    is_provider_or_model_failure,
)
from travel_agent.agents.worker_errors import (
    PREFIX_PROVIDER_CAPABILITY,
    PREFIX_PROVIDER_DETERMINISTIC,
    PREFIX_PROVIDER_EMPTY,
    PREFIX_PROVIDER_TRANSIENT,
    PREFIX_SCHEMA_GATE,
    PREFIX_WORKER_FAILED,
    format_worker_last_error,
)

# 中性载荷：逐词核过 _DETERMINISTIC_MARKERS / _TRANSIENT_MARKERS /
# _QUERY_MISS_MARKERS，一个都不含（"upstream said no" 这类句子不行，
# "upstream" 本身是 transient marker，会把期望值翻面）。
_NEUTRAL = "planning halted"


def _classify(text: str) -> tuple[str, str]:
    result = classify_provider_failure(text)
    return result.category, result.reason_code


# ---------------------------------------------------------------------------
# A. 六个前缀 × 两个读方函数：当前结论逐条钉住。
# 断言维度是 reason_code 而不是 category：三个不同前缀的 category 都是
# incomplete，只有 reason_code 分得开。
# ---------------------------------------------------------------------------

_PREFIX_EXPECTATIONS = {
    PREFIX_SCHEMA_GATE: ("deterministic", "provider_deterministic_failure", True),
    PREFIX_PROVIDER_DETERMINISTIC: (
        "deterministic",
        "provider_deterministic_failure",
        True,
    ),
    PREFIX_PROVIDER_TRANSIENT: ("transient", "provider_transient_failure", True),
    PREFIX_PROVIDER_EMPTY: ("incomplete", "provider_empty_result", True),
    PREFIX_PROVIDER_CAPABILITY: ("incomplete", "provider_capability_declined", True),
    # 已知缺陷的当前值：is_provider 为 False，四道门不进分类；万一被喂进
    # classify，落 free-text 兜底。见模块 docstring 与 docs/ 待决项。
    PREFIX_WORKER_FAILED: ("incomplete", "provider_incomplete_result", False),
}


@pytest.mark.parametrize("prefix", worker_errors._KNOWN_PREFIXES)
def test_every_known_prefix_keeps_its_current_reader_verdict(prefix: str) -> None:
    expected_category, expected_reason_code, expected_gate_visible = (
        _PREFIX_EXPECTATIONS[prefix]
    )
    text = f"{prefix} {_NEUTRAL}"
    category, reason_code = _classify(text)
    assert reason_code == expected_reason_code, (
        f"{prefix!r} 的 reason_code 变了：{reason_code!r}（category={category!r}）。"
        "前缀是持久化格式，读方结论是路由输入，两者都不许悄悄变"
    )
    assert is_provider_or_model_failure(text) is expected_gate_visible


# ---------------------------------------------------------------------------
# B. schema_gate: 不是常量映射，是条件分支（provider_failure.py:116-125）：
# 前缀只说明失败发生在 packet 收集层，暂态性由文本里的 _TRANSIENT_MARKERS
# 决定。一个用例钉不住这个分支，必须带 / 不带 transient marker 各一个。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected_category", "expected_reason_code"),
    [
        # 收集调用超时：重试不会逐字复现，判 transient。
        (f"{_NEUTRAL}: connection reset by peer", "transient", "provider_transient_failure"),
        # 收集层自身失败（如 schema 拒绝）：判 deterministic。
        (_NEUTRAL, "deterministic", "provider_deterministic_failure"),
    ],
    ids=["transient_marker_in_payload", "no_transient_marker"],
)
def test_schema_gate_prefix_verdict_depends_on_transient_markers_in_the_payload(
    payload: str, expected_category: str, expected_reason_code: str
) -> None:
    category, reason_code = _classify(f"{PREFIX_SCHEMA_GATE} {payload}")
    assert (category, reason_code) == (expected_category, expected_reason_code)
    assert is_provider_or_model_failure(f"{PREFIX_SCHEMA_GATE} {payload}") is True


# ---------------------------------------------------------------------------
# C. worker_failed: 的已知缺陷现状：对四道门不可见、分类随残留文本漂移、
# 唯一生效点是 _already_prefixed。这里钉的是现状，不是背书。
# ---------------------------------------------------------------------------


def test_worker_failed_prefix_is_invisible_to_every_gate() -> None:
    text = f"{PREFIX_WORKER_FAILED} {_NEUTRAL}"
    # is_provider_or_model_failure 挡在 classify 前面；它返回 False，
    # artifact_gate/candidate_gate 的四处读点都不会进分类。
    assert is_provider_or_model_failure(text) is False
    # 万一被喂进 classify（输入 B 那路），落 free-text 兜底。
    assert _classify(text) == ("incomplete", "provider_incomplete_result")


def test_worker_failed_prefix_classification_drifts_with_residual_text() -> None:
    # 同一个前缀，残留文本里碰巧含什么词，分类就是什么 —— 漂移本身被钉住。
    assert _classify(f"{PREFIX_WORKER_FAILED} {_NEUTRAL}") == (
        "incomplete",
        "provider_incomplete_result",
    )
    assert _classify(f"{PREFIX_WORKER_FAILED} {_NEUTRAL}: connection reset") == (
        "transient",
        "provider_transient_failure",
    )
    assert _classify(f"{PREFIX_WORKER_FAILED} bad request from the edge") == (
        "deterministic",
        "provider_deterministic_failure",
    )


def test_worker_failed_prefix_only_takes_effect_in_already_prefixed() -> None:
    # _already_prefixed 认它，于是 format 不二次加前缀 —— 它今天唯一生效的地方。
    text = f"{PREFIX_WORKER_FAILED} {_NEUTRAL}"
    assert worker_errors._already_prefixed(text) is True
    assert format_worker_last_error(ValueError(text)) == text


# ---------------------------------------------------------------------------
# D. 三份协议外裸写路径的当前分类：不经 format_worker_last_error，
# 不带前缀，喂给两个读方钉住当前结论。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "origin"),
    [
        # run_control.py:721-726：按节点身份写，不带前缀。
        ("delivery deadline elapsed before research worker could start", "run_control research"),
        ("delivery deadline elapsed before itinerary composition", "run_control composition"),
        # itinerary_planner/node.py:3010：同一句文案。
        ("delivery deadline elapsed before itinerary composition", "itinerary_planner deadline"),
        # itinerary_planner/node.py:3731：str(exc)，异常文案任意。
        # 代表性样本：含 "research packet" 字样的异常文本今天走 free-text 落
        # incomplete（若改经 format_worker_last_error 会翻成 schema_gate:，
        # is_provider 翻 True —— 那是路由级变化，单独立项，本轮不做）。
        ("research packet validation failed", "itinerary_planner str(exc) representative"),
    ],
    ids=[
        "run_control_research_deadline",
        "run_control_composition_deadline",
        "itinerary_planner_deadline",
        "itinerary_planner_raw_exception",
    ],
)
def test_unprefixed_bare_writes_keep_their_current_verdict(text: str, origin: str) -> None:
    assert _classify(text) == ("incomplete", "provider_incomplete_result"), origin
    # False 意味着四道门把这些失败留在 Delivery Integrity 分支。
    assert is_provider_or_model_failure(text) is False, origin


# ---------------------------------------------------------------------------
# E. 两份 query-miss 词表的差集：钉住「刻意收缩」不许悄悄漂移。
# ---------------------------------------------------------------------------


def test_the_query_miss_vocabularies_divergence_is_pinned() -> None:
    writer = set(worker_errors._QUERY_MISS_MARKERS)
    reader = set(provider_failure._QUERY_MISS_MARKERS)
    # 读方只留一条（provider_failure.py:24-26 注释自陈：权威信号是
    # provider_empty: 前缀，读方词表只兜 Provider 自己措辞的空结果）。
    assert reader == {"found no executable route"}
    assert writer == {"found no executable route", "no results", "empty result"}
    # 差集是这条刻意收缩的形状：不许被顺手抹平（合并是行为决策，另一张票），
    # 也不许被顺手扩大。
    assert writer - reader == {"no results", "empty result"}


# ---------------------------------------------------------------------------
# F. 写方格式与读方匹配的耦合：`f"{PREFIX} {text}"`，前缀后恰好一个空格；
# 读方用 startswith(前缀)，前缀自带冒号，空格不影响匹配。
# ---------------------------------------------------------------------------


def test_writer_emits_prefix_then_exactly_one_space() -> None:
    assert format_worker_last_error(ValueError("boom")) == f"{PREFIX_WORKER_FAILED} boom"
    # 幂等：已带前缀的文本不二次加前缀（_already_prefixed）。
    once = format_worker_last_error(ValueError("boom"))
    assert format_worker_last_error(ValueError(once)) == once


@pytest.mark.parametrize(
    "prefix",
    [
        PREFIX_SCHEMA_GATE,
        PREFIX_PROVIDER_DETERMINISTIC,
        PREFIX_PROVIDER_TRANSIENT,
        PREFIX_PROVIDER_EMPTY,
        PREFIX_PROVIDER_CAPABILITY,
    ],
)
def test_readers_match_on_the_prefix_only_so_the_space_is_not_load_bearing(
    prefix: str,
) -> None:
    with_space = classify_provider_failure(f"{prefix} {_NEUTRAL}")
    without_space = classify_provider_failure(f"{prefix}{_NEUTRAL}")
    assert without_space.reason_code == with_space.reason_code
    # schema_gate: 两个样本都不含 transient marker，结论同为 deterministic；
    # 其余四个前缀是纯映射，空格更不影响。
    assert is_provider_or_model_failure(f"{prefix}{_NEUTRAL}") is True


# ---------------------------------------------------------------------------
# G. 门禁可见前缀的名单边界：_EXPLICIT_EXTERNAL_FAILURE_MARKERS 恰好含五个
# 门禁可见前缀；`worker_failed:` 不在其中（是待决缺陷，收编即路由级变更）；
# 也不许以后用 `*_KNOWN_PREFIXES` 一锅端进来 —— 那会让 `worker_failed:`
# 混进名单，四道门当场翻面。
# ---------------------------------------------------------------------------


def test_explicit_markers_contain_exactly_the_five_gate_visible_prefixes() -> None:
    markers = provider_failure._EXPLICIT_EXTERNAL_FAILURE_MARKERS
    gate_visible = {
        PREFIX_SCHEMA_GATE,
        PREFIX_PROVIDER_DETERMINISTIC,
        PREFIX_PROVIDER_TRANSIENT,
        PREFIX_PROVIDER_EMPTY,
        PREFIX_PROVIDER_CAPABILITY,
    }
    assert gate_visible <= set(markers)
    assert PREFIX_WORKER_FAILED not in markers
    # 禁止 splat 全表的等价断言：全表前缀与名单里的前缀恰好差一个
    # `worker_failed:`。谁把 `*_KNOWN_PREFIXES` 展开进来，这里就红。
    assert set(worker_errors._KNOWN_PREFIXES) - set(markers) == {PREFIX_WORKER_FAILED}
