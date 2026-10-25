"""验证正常路由不会误报错误，日志脱敏不会泄露查询凭证。"""

from __future__ import annotations

import logging
import pytest

from travel_agent.utils.log_redaction import (
    _INSTALLED_LOGGERS,
    _QuerySecretFilter,
    install_query_secret_redaction,
)

_EVAL_LOGGER = "travel_agent.planning.requirements.candidate_evaluation"
_GATE_LOGGER = "travel_agent.planning.research.node"


def test_missing_deadline_preserves_route_without_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:

    from travel_agent.planning.research.node import route_after_candidate_gate
    from travel_agent.planning.state import TravelAgentState

    state = TravelAgentState(candidate_gate_route="transport_researcher")
    assert state.run_deadline is None

    with caplog.at_level(logging.DEBUG, logger=_GATE_LOGGER):
        assert route_after_candidate_gate(state) == "transport_researcher"

    assert [r for r in caplog.records if r.name == _GATE_LOGGER] == []


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


    import travel_agent.integrations.routes.amap as amap

    importlib.reload(amap)

    assert len(_our_filters(httpx_logger)) == 1
