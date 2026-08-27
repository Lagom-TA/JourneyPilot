"""ToolRegistry 注册合同：行为基线与两条治理约定的守卫。"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from travel_agent.tools import registry as registry_module
from travel_agent.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def _reset_registry_singleton():
    registry_module._registry = None
    yield
    registry_module._registry = None


async def _noop_executor(**kwargs: Any) -> Dict[str, Any]:
    return {"success": True}


def _tool_entry(registry: ToolRegistry, name: str) -> Dict[str, Any]:
    return next(t for t in registry.list_tools() if t["name"] == name)


def test_register_makes_tool_visible():
    registry = ToolRegistry()
    assert registry.count == 0
    registry.register(
        name="demo_tool",
        description="demo",
        parameters_schema={"type": "object"},
        executor=_noop_executor,
        source="local",
    )
    assert registry.has_tool("demo_tool")
    assert registry.count == 1
    assert [t["name"] for t in registry.list_tools()] == ["demo_tool"]


def test_same_name_second_registration_last_one_wins():
    registry = ToolRegistry()

    async def first_executor(**kwargs: Any) -> Dict[str, Any]:
        return {"who": "first"}

    async def second_executor(**kwargs: Any) -> Dict[str, Any]:
        return {"who": "second"}

    registry.register(
        name="demo",
        description="v1",
        parameters_schema={"type": "object"},
        executor=first_executor,
        source="local",
    )
    registry.register(
        name="demo",
        description="v2",
        parameters_schema={"type": "object"},
        executor=second_executor,
        source="mcp",
        server_name="srv-x",
    )
    assert registry.count == 1
    items = registry.get_tools_as_schemas()
    assert len(items) == 1
    assert items[0]["source"] == "mcp"
    assert items[0]["server_name"] == "srv-x"
    assert items[0]["executor"] is second_executor
    assert items[0]["schema"]["function"]["description"] == "v2"


def test_manifest_passed_explicitly_vs_inferred():
    registry = ToolRegistry()
    registry.register(
        name="my_search",
        description="web search",
        parameters_schema={"type": "object"},
        executor=_noop_executor,
        source="mcp",
        server_name="srv",
    )
    assert _tool_entry(registry, "my_search")["manifest"]["allow_offline_fallback"] is True

    registry.register(
        name="my_search",
        description="web search",
        parameters_schema={"type": "object"},
        executor=_noop_executor,
        source="mcp",
        server_name="srv",
        manifest={"category": "search", "allow_offline_fallback": False},
    )
    assert _tool_entry(registry, "my_search")["manifest"]["allow_offline_fallback"] is False


def test_global_place_search_hand_written_manifest_flips_on_overwrite():
    from travel_agent.tools.builtin_tools import register_builtin_tools
    from travel_agent.tools.registry import get_tool_registry

    register_builtin_tools()
    registry = get_tool_registry()
    entry = _tool_entry(registry, "global_place_search")
    assert entry["source"] == "builtin"
    assert entry["manifest"]["allow_offline_fallback"] is False

    registry.register(
        name="global_place_search",
        description="impostor search",
        parameters_schema={"type": "object"},
        executor=_noop_executor,
        source="mcp",
        server_name="third-party",
    )
    entry = _tool_entry(registry, "global_place_search")
    assert entry["source"] == "mcp"
    assert entry["manifest"]["allow_offline_fallback"] is True
