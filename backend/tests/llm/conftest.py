"""离线模型测试不继承开发机的 HTTP 代理。"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_offline_http_clients(offline_http_environment):
    """模型适配目录全部使用离线响应，代理由真实集成测试负责验证。"""
