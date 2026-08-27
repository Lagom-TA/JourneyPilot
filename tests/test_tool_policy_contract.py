"""Worker 工具策略合同：filter_tools_for_agent 的黑盒行为基线。"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from travel_agent.agents import utils as agent_utils
from travel_agent.agents.utils import filter_tools_for_agent


def _local(name: str) -> Dict[str, Any]:
    return {"schema": {"function": {"name": name}}, "source": "builtin", "server_name": None}


def _mcp(name: str, server_name: str) -> Dict[str, Any]:
    return {"schema": {"function": {"name": name}}, "source": "mcp", "server_name": server_name}


_FAKE_TOOLS: List[Dict[str, Any]] = [
    _local("ask_user"),
    _local("global_place_search"),
    _local("global_route_search"),
    _mcp("tavily_search", "tavily-search"),
    _mcp("brave_search", "brave-search"),
    _mcp("firecrawl_scrape", "firecrawl"),
    _mcp("duckduckgo_search", "duckduckgo-search"),
    _mcp("fetch_web", "fetch"),
    _mcp("train_ticket_search", "12306-train"),
    _mcp("duffel_search_flights", "duffel-flights"),
    _mcp("maps_geo", "amap-maps"),
    _mcp("maps_geocode", "amap-maps"),
    _mcp("maps_weather", "amap-maps"),
    _mcp("maps_text_search", "amap-maps"),
    _mcp("maps_around_search", "amap-maps"),
    _mcp("maps_search_detail", "amap-maps"),
    _mcp("currency_convert", "currency-exchange-mcp"),
    _mcp("baidu_place_search", "baidu-maps"),
    _mcp("free_web_search", "duckduckgo-search"),
]


def _names(tools: List[Dict[str, Any]]) -> List[str]:
    return sorted(t["schema"]["function"]["name"] for t in tools)


class _FakePolicy(dict):
    """假策略对象：建模前按 .get() 消费，建模后按属性消费，两种形态都成立。"""

    def __getattr__(self, key: str) -> Any:
        return self.get(key, set())


@pytest.fixture
def fake_policy(monkeypatch):
    def apply(policy: Dict[str, _FakePolicy]) -> None:
        monkeypatch.setattr(agent_utils, "_AGENT_TOOL_POLICY", policy)

    return apply


_EXPECTED_REAL_RESULTS: Dict[str, List[str]] = {
    "destination_researcher": [
        "ask_user",
        "brave_search",
        "duckduckgo_search",
        "fetch_web",
        "firecrawl_scrape",
        "free_web_search",
        "global_place_search",
        "maps_around_search",
        "maps_search_detail",
        "maps_text_search",
        "tavily_search",
    ],
    "transport_researcher": [
        "duffel_search_flights",
        "free_web_search",
        "global_route_search",
        "maps_around_search",
        "maps_search_detail",
        "maps_text_search",
        "train_ticket_search",
    ],
    "accommodation_researcher": [
        "brave_search",
        "currency_convert",
        "free_web_search",
        "global_place_search",
        "maps_around_search",
        "maps_search_detail",
        "maps_text_search",
        "tavily_search",
    ],
    "itinerary_planner": [],
}


def test_real_workers_keep_their_policy_toolsets():
    for agent_name, expected in _EXPECTED_REAL_RESULTS.items():
        got = _names(filter_tools_for_agent(_FAKE_TOOLS, agent_name))
        assert got == expected, f"{agent_name}: {got}"


def test_unknown_agent_keeps_only_unscoped_local_tools():
    assert _names(filter_tools_for_agent(_FAKE_TOOLS, "no_such_agent")) == ["ask_user"]


def test_deny_star_returns_empty_list(fake_policy):
    fake_policy({"blocked": _FakePolicy(deny_tools={"*"}, servers={"tavily-search"})})
    assert filter_tools_for_agent(_FAKE_TOOLS, "blocked") == []


def test_scoped_local_tools_need_extra_tools(fake_policy):
    fake_policy({"with_extra": _FakePolicy(extra_tools={"global_place_search"})})
    got = _names(filter_tools_for_agent(_FAKE_TOOLS, "with_extra"))
    assert "global_place_search" in got
    assert "global_route_search" not in got

    fake_policy({"bare": _FakePolicy()})
    got = _names(filter_tools_for_agent(_FAKE_TOOLS, "bare"))
    assert "global_place_search" not in got
    assert "global_route_search" not in got
    assert "ask_user" in got


def test_mcp_tools_filtered_by_server_whitelist(fake_policy):
    fake_policy({"scoped": _FakePolicy(servers={"tavily-search"})})
    got = _names(filter_tools_for_agent(_FAKE_TOOLS, "scoped"))
    assert "tavily_search" in got
    assert "brave_search" not in got
    assert "currency_convert" not in got


def test_extra_tools_admits_mcp_outside_servers(fake_policy):
    fake_policy({"pinhole": _FakePolicy(extra_tools={"currency_convert"})})
    assert _names(filter_tools_for_agent(_FAKE_TOOLS, "pinhole")) == [
        "ask_user",
        "currency_convert",
    ]
