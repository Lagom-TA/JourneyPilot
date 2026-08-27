"""静默降级留痕（评审条目 B9）。

三处处置各不相同，这个文件按三处分节钉住：

* ``candidate_gate.route_after_candidate_gate`` 那个 ``except ValueError``：
  不可达分支，**只加注释不加日志**。给不可达分支加 WARNING 只会让读的人以为它
  可能发生。这里只断言它仍然不打日志、仍然返回 fail-open 的 ``"passed"``。
* ``services/candidate_intent_evaluation`` 的三条静默路径：断言在
  ``tests/agent_behavior/test_intent_research_ranking_selection.py`` 末尾那一节 ——
  那里已经有这三条路径要的 ``_intent`` / ``_packet`` / ``_catalog`` 夹具，在这里重建
  一份只会多一份要跟着改的东西。
* ``utils/log_redaction``：脱敏是**加挂载点不是挪原位**。provider 模块 import 时那句
  才是主挂点；日志入口再挂一遍覆盖反方向的缺口，靠的是安装函数幂等。
"""

from __future__ import annotations

import logging
import pytest

from travel_agent.utils.log_redaction import (
    _INSTALLED_LOGGERS,
    _QuerySecretFilter,
    install_query_secret_redaction,
)

_EVAL_LOGGER = "travel_agent.services.candidate_intent_evaluation"
_GATE_LOGGER = "travel_agent.agents.orchestrator.candidate_gate"


# ── 3.1 不可达分支：仍然不留日志 ──────────────────────────────────────────────


def test_unreachable_deadline_branch_stays_silent_and_fails_open(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``run_deadline`` 为 None 时直接返回既定路由，整条路径零日志。

    那个 ``except ValueError`` 今天不可达（入参是 pydantic 校验过的
    ``RunDeadlineSnapshot``），所以这里能验的是它的**邻居**：路由函数在正常输入上
    不打任何日志。加了 WARNING 的话这条会红。
    """

    from travel_agent.agents.orchestrator.candidate_gate import (
        route_after_candidate_gate,
    )
    from travel_agent.entities.state import TravelAgentState

    state = TravelAgentState(candidate_gate_route="transport_researcher")
    assert state.run_deadline is None

    with caplog.at_level(logging.DEBUG, logger=_GATE_LOGGER):
        assert route_after_candidate_gate(state) == "transport_researcher"

    assert [r for r in caplog.records if r.name == _GATE_LOGGER] == []


# ── 3.3 脱敏：幂等 + 日志入口挂得上 ──────────────────────────────────────────


@pytest.fixture
def clean_redaction_state():
    """把安装记录与 httpx logger 的 filter 恢复原状，别把状态漏给别的测试。"""

    httpx_logger = logging.getLogger("httpx")
    saved_installed = set(_INSTALLED_LOGGERS)
    saved_filters = list(httpx_logger.filters)
    yield httpx_logger
    _INSTALLED_LOGGERS.clear()
    _INSTALLED_LOGGERS.update(saved_installed)
    httpx_logger.filters = saved_filters


def _our_filters(logger: logging.Logger) -> list:
    return [f for f in logger.filters if isinstance(f, _QuerySecretFilter)]


def test_install_is_idempotent(clean_redaction_state) -> None:
    """重复调用不叠加 filter —— 「日志入口再挂一遍」这个做法全靠这一条成立。"""

    logger = logging.getLogger("test_redaction_idempotent")
    logger.filters = []
    _INSTALLED_LOGGERS.discard("test_redaction_idempotent")

    for _ in range(5):
        install_query_secret_redaction("test_redaction_idempotent")

    assert len(_our_filters(logger)) == 1
    logger.filters = []
    _INSTALLED_LOGGERS.discard("test_redaction_idempotent")


def test_httpx_logger_carries_the_filter_after_app_logging_setup(
    clean_redaction_state,
) -> None:
    """配置日志（``create_app``）之后，httpx logger 上确实挂着这个 filter。

    先把 filter 与安装记录清空，模拟一个「provider 模块还没被 import」的进程，
    再走入口。挂载点在入口而不只在 provider 模块 import 时，这一条才会绿。
    """

    from travel_agent.api.app import create_app

    httpx_logger = clean_redaction_state
    httpx_logger.filters = []
    _INSTALLED_LOGGERS.discard("httpx")
    assert _our_filters(httpx_logger) == []

    create_app()

    installed = _our_filters(httpx_logger)
    assert len(installed) == 1

    # 再走一次入口不叠加。
    create_app()
    assert len(_our_filters(httpx_logger)) == 1


def test_provider_module_installs_it_at_import_time(clean_redaction_state) -> None:
    """主挂点仍在 provider 模块的 import 时，不是被挪去了入口。

    这一条是 B9 那个「加不是挪」的钉子：任何绕过入口直接 import 这个模块的路径
    （脚本、单测、工具直调）都必须已经装上脱敏。
    """

    import importlib

    httpx_logger = clean_redaction_state
    httpx_logger.filters = []
    _INSTALLED_LOGGERS.discard("httpx")

    import travel_agent.services.amap_route_search as amap

    importlib.reload(amap)

    assert len(_our_filters(httpx_logger)) == 1
