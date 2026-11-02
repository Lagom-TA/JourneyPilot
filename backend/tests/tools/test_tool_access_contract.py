"""工具目录读取失败必须显式失败，不能静默降级成“没有工具”。"""

from __future__ import annotations

import pytest

from travel_agent.tools import access


class _ExplodingRegistry:
    def get_tools_as_schemas(self):
        raise RuntimeError("registry unavailable")


async def test_get_available_tools_raises_instead_of_returning_an_empty_catalog(
    monkeypatch,
):
    monkeypatch.setattr(access, "get_tool_registry", lambda: _ExplodingRegistry())
    with pytest.raises(access.ToolAccessUnavailable):
        await access.get_available_tools([])
