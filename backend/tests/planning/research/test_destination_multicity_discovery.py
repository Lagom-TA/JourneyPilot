"""Per-destination research calls and fallback isolation, without providers."""

from travel_agent.planning.research.destination import dining_binding, discovery
from travel_agent.planning.research.query_contracts import ResearchQuery


def query(query_id, destination, text, *, kind="structural", aliases=None, after=None):
    return ResearchQuery.model_validate({
        "query_id": query_id, "generation_id": "offline-generation", "domain": "dining",
        "destination_id": destination, "query_kind": kind, "query_text": text,
        "aliases": aliases or [], "desired_candidate_count": 2,
        "provider_route": "web_discovery", "priority": 60,
        "fallback_after_query_ids": after or [],
    })


def boundary(destination, name, country="cn"):
    return {"destination_id": destination, "name": name, "country_code": country, "latitude": 30.0, "longitude": 120.0}


def tool(name):
    return {"schema": {"function": {"name": name}}}


async def test_second_city_empty_web_result_runs_its_own_fallback(monkeypatch):
    calls = []

    async def amap(name, args, **_kwargs):
        calls.append((name, args))
        if args["city"] == "苏州":
            return {"tool_name": name, "status": "failed", "error": "offline failure"}
        return {
            "tool_name": name, "status": "success", "audit_id": "offline-hangzhou",
            "retrieved_at": "2026-11-01T00:00:00+00:00",
            "sanitized_result": {"results": [{
                "id": "B0-HZ", "name": "杭州茶馆", "address": "杭州", "typecode": "050500",
                "latitude": 30.0, "longitude": 120.0,
            }]},
        }

    async def web(name, args, **_kwargs):
        calls.append((name, args))
        return {
            "tool_name": name, "status": "success", "sanitized_result": {"results": []},
            "metadata": {"provider_result_outcome": "empty_success"},
        }

    monkeypatch.setattr(dining_binding, "execute_tool", amap)
    monkeypatch.setattr(discovery, "execute_tool", web)
    monkeypatch.setattr(discovery, "runtime_fallback_capacity", lambda: (True, True))
    planned = [
        query("hz-struct", "hz", "杭州 茶馆", aliases=["茶馆"]),
        query("sz-struct", "sz", "苏州 素食", aliases=["素食"]),
        query("sz-fallback", "sz", "restaurant in 苏州", kind="generic_fallback", after=["sz-struct"]),
    ]
    executed, results, messages = [], [], []
    await discovery.discover_and_resolve_required_places(
        messages=messages, available_tools=[tool("maps_text_search"), tool("free_web_search")],
        required_candidate_kinds=["dining"], destination_boundaries=[boundary("hz", "杭州"), boundary("sz", "苏州")],
        tool_context={}, authoritative_tool_results=results, planned_queries=planned,
        executed_query_ids=executed,
    )
    assert calls == [
        ("maps_text_search", {"keywords": "茶馆", "city": "杭州"}),
        ("maps_text_search", {"keywords": "素食", "city": "苏州"}),
        ("free_web_search", {"query": "苏州 素食", "max_results": 5}),
        ("free_web_search", {"query": "restaurant in 苏州", "max_results": 5}),
    ]
    assert set(executed) == {"hz-struct", "sz-struct", "sz-fallback"}
    assert any(item.get("tool_name") == "maps_text_search" and item.get("status") == "failed" for item in results)


async def test_china_and_foreign_cities_do_not_share_amap_or_query_ids(monkeypatch):
    calls = []

    async def amap(name, args, **_kwargs):
        calls.append((name, args))
        return {
            "tool_name": name, "status": "success", "audit_id": "offline-hangzhou",
            "retrieved_at": "2026-11-01T00:00:00+00:00",
            "sanitized_result": {"results": [{
                "id": "B0-HZ", "name": "杭州茶馆", "address": "杭州", "typecode": "050500",
                "latitude": 30.0, "longitude": 120.0,
            }]},
        }

    async def web(name, args, **_kwargs):
        calls.append((name, args))
        return {"tool_name": name, "status": "success", "sanitized_result": {"content": "offline result"}}

    monkeypatch.setattr(dining_binding, "execute_tool", amap)
    monkeypatch.setattr(discovery, "execute_tool", web)
    executed = []
    await discovery.discover_and_resolve_required_places(
        messages=[], available_tools=[tool("maps_text_search"), tool("free_web_search")],
        required_candidate_kinds=["dining"],
        destination_boundaries=[boundary("hz", "杭州"), boundary("jp", "京都", "jp")],
        tool_context={}, authoritative_tool_results=[],
        planned_queries=[
            query("hz-query", "hz", "杭州 茶馆", aliases=["茶馆"]),
            query("jp-query", "jp", "京都 素食", aliases=["素食"]),
        ],
        executed_query_ids=executed,
    )
    assert calls == [
        ("maps_text_search", {"keywords": "茶馆", "city": "杭州"}),
        ("free_web_search", {"query": "京都 素食", "max_results": 5}),
    ]
    assert set(executed) == {"hz-query", "jp-query"}
