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


def test_collision_recorded_with_provenance():
    registry = ToolRegistry()
    registry.register(
        name="t",
        description="v1",
        parameters_schema={"type": "object"},
        executor=_noop_executor,
        source="builtin",
        manifest={"allow_offline_fallback": False},
    )
    assert registry.collisions() == []

    collided = registry.register(
        name="t",
        description="v2",
        parameters_schema={"type": "object"},
        executor=_noop_executor,
        source="mcp",
        server_name="srv",
    )
    assert collided is True
    rows = registry.collisions()
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "t"
    assert rows[0]["previous"] == {
        "source": "builtin",
        "server_name": None,
        "manifest_hand_written": True,
    }
    assert rows[0]["incoming"] == {
        "source": "mcp",
        "server_name": "srv",
        "manifest_hand_written": False,
    }
    rows[0]["previous"]["source"] = "tampered"
    assert registry.collisions()[0]["previous"]["source"] == "builtin"


def test_no_collision_keeps_ledger_empty():
    registry = ToolRegistry()
    assert registry.collisions() == []
    registry.register(
        name="a",
        description="d",
        parameters_schema={"type": "object"},
        executor=_noop_executor,
    )
    assert registry.register(
        name="b",
        description="d",
        parameters_schema={"type": "object"},
        executor=_noop_executor,
        source="mcp",
        server_name="srv",
    ) is False
    assert registry.collisions() == []


def test_scoped_non_mcp_tools_are_builtin_owned():
    from travel_agent.agents.utils import _SCOPED_NON_MCP_TOOLS
    from travel_agent.tools.builtin_tools import register_builtin_tools
    from travel_agent.tools.registry import get_tool_registry

    register_builtin_tools()
    registry = get_tool_registry()
    sources = {t["source"] for t in registry.list_tools()}
    for name in sorted(_SCOPED_NON_MCP_TOOLS):
        entry = next((t for t in registry.list_tools() if t["name"] == name), None)
        assert entry is not None and entry["source"] != "mcp", (
            f"[{name}] 被 source=mcp 的注册抢走（当前 sources={sorted(sources)}）。"
            "agents/utils.py 的 _SCOPED_NON_MCP_TOOLS 限制表只在 source != 'mcp' 分支生效，"
            "一旦被 MCP 同名工具覆盖，「只给 extra_tools 点名的 agent」就静默放宽成"
            "「给所有 allowed_servers 覆盖到那台 server 的 agent」。要么改限制表，"
            "要么换工具名，不能让覆盖无声生效。"
        )


def test_hand_written_no_fallback_tools_absent_from_fallback_map():
    from travel_agent.tools.builtin_tools import register_builtin_tools
    from travel_agent.tools.fallback import _FALLBACK_MAP
    from travel_agent.tools.registry import get_tool_registry

    register_builtin_tools()
    registry = get_tool_registry()
    no_fallback = {
        tool["name"]
        for tool in registry._tools.values()
        if tool.get("manifest_hand_written") and not tool["manifest"].allow_offline_fallback
    }
    overlap = no_fallback & set(_FALLBACK_MAP)
    assert overlap == set(), (
        f"{sorted(overlap)} 同时出现在手写 manifest 的 allow_offline_fallback=False 与 "
        "tools/fallback.py 的 _FALLBACK_MAP 里。这是同一条约定的两半：手写声明说"
        "「这个工具不接受替身」，_FALLBACK_MAP 缺它的键是承诺的执行面。只改前一半，"
        "声明变成无人执行的空话；只改后一半，降级边失去了声明依据。两边必须同改。"
    )
