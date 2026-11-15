from copy import deepcopy
from types import SimpleNamespace

import pytest

from travel_agent.planning.delivery.source_presentation import present_public_source


def source(**overrides):
    values = {
        "source_record_id": "source-1",
        "source_kind": "external_tool",
        "title": "航班查询结果",
        "public_excerpt": "",
        "canonical_url": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "title",
    [
        "航班查询结果", "地点搜索结果", "网页搜索结果", "路线查询结果", "天气查询结果",
        "search_flights 查询结果", "工具查询结果", "交通路线：深圳北站 → 深圳湾公园",
        "地点资料：大雁塔", "找到 2 个结果：大雁塔、钟楼",
        "地铁 · 深圳北站 → 深圳湾公园 · 约 42 分钟",
    ],
)
def test_generic_title_without_meaningful_content_is_hidden(title):
    assert present_public_source(source(title=title, public_excerpt=title)) is None


@pytest.mark.parametrize(
    "excerpt",
    [
        "找到 2 个结果：大雁塔、钟楼", "找到 3 条网页：景点、餐厅", "已核对 4 条外部结果。",
        "没有匹配的结果", "已取到结果", "地铁 · 深圳北站 → 深圳湾公园 · 约 42 分钟",
        '{"results":[{"name":"大雁塔"}]}', "place_id=osm:123",
    ],
)
def test_tool_summaries_and_payloads_are_not_sources(excerpt):
    assert present_public_source(source(public_excerpt=excerpt)) is None


def test_raw_tool_source_titles_are_cleaned_before_display():
    assert present_public_source(source(title="duffel route: duffel:offer_1", public_excerpt="广州 → 海口")) is None
    assert present_public_source(source(title="nominatim place record: 大雁塔", public_excerpt="西安市雁塔区")) is None
    assert present_public_source(source(title="search_flights 查询结果", canonical_url="https://airline.example/flight")) == (
        "airline.example", None, "https://airline.example/flight"
    )


def test_actual_named_sources_or_substantive_excerpts_do_not_need_a_url():
    assert present_public_source(
        source(source_kind="external_web", title="陕西历史博物馆开放公告")
    ) == ("陕西历史博物馆开放公告", None, None)
    assert present_public_source(
        source(public_excerpt="12306 公告：预售期为 15 天。")
    ) == (None, "12306 公告：预售期为 15 天。", None)
    assert present_public_source(
        source(source_kind="rag_chunk", title="铁路出行手册", public_excerpt="可在发车前办理退票。")
    ) == ("铁路出行手册", "可在发车前办理退票。", None)
    assert present_public_source(
        source(
            title="12306 余票查询：乐山→重庆北（参考日无结果）",
            public_excerpt="参考日无乐山直达重庆北的可售车次。",
        )
    ) == ("12306 余票查询：乐山→重庆北（参考日无结果）", "参考日无乐山直达重庆北的可售车次。", None)


def test_safe_url_supplies_a_real_hostname_and_deduplicates_the_excerpt():
    assert present_public_source(
        source(canonical_url="  https://museum.example.org/visit  ")
    ) == ("museum.example.org", None, "https://museum.example.org/visit")
    assert present_public_source(
        source(
            title="博物馆开放公告", public_excerpt="博物馆开放公告。周一闭馆。",
            canonical_url="https://museum.example.org/visit",
        )
    ) == ("博物馆开放公告", "周一闭馆。", "https://museum.example.org/visit")
    assert present_public_source(
        source(canonical_url="HTTPS://例子.测试/公告")
    ) == ("xn--fsqu00a.xn--0zwm56d", None, "HTTPS://例子.测试/公告")


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)", "data:text/html,hello", "//evil.example/path", "/fake-source",
        "#source", "mailto:info@example.org", "https://", "https://museum.example.org@evil.example/",
        "https://@evil.example/", "https://museum.example.org/\npath", "https://invalid.example:99999/",
        "https://museum.example.org\\@evil.example/",
    ],
)
def test_only_safe_http_urls_are_considered_real_links(url):
    assert present_public_source(source(canonical_url=url)) is None


def test_unsafe_link_does_not_hide_a_named_source():
    assert present_public_source(
        source(title="陕西历史博物馆官网公告", canonical_url="javascript:alert(1)")
    ) == ("陕西历史博物馆官网公告", None, None)


def test_repeated_nested_entity_facts_are_not_external_source_content():
    values = [{"name": "大雁塔", "address": "西安市雁塔区"}, ["深圳北站", "深圳湾公园"]]
    assert present_public_source(source(public_excerpt="大雁塔"), values) is None
    assert present_public_source(source(title="大雁塔", public_excerpt="西安市雁塔区"), values) is None
    assert present_public_source(source(public_excerpt="名称：大雁塔；地址：西安市雁塔区"), values) is None
    assert present_public_source(source(public_excerpt="出发：深圳北站；抵达：深圳湾公园"), values) is None
    assert present_public_source(source(title="place_id=osm:123")) is None
    assert present_public_source(source(public_excerpt="无关, place_id=osm:123"), ["无关"]) is None
    assert present_public_source(
        source(source_kind="external_web", title="大雁塔参观须知", public_excerpt="大雁塔周一闭馆。"), values
    ) == ("大雁塔参观须知", "大雁塔周一闭馆。", None)


def test_generated_place_and_route_labels_do_not_make_entity_facts_a_source():
    assert present_public_source(source(title="地点资料：大雁塔", public_excerpt="西安市雁塔区")) is None
    assert present_public_source(
        source(title="交通路线：深圳北站 → 深圳湾公园", public_excerpt="深圳北站 → 深圳湾公园 · 42 分钟")
    ) is None
    assert present_public_source(
        source(title="地点资料：大雁塔", public_excerpt="保护公告：12 月 1 日闭馆维护。")
    ) == (None, "保护公告：12 月 1 日闭馆维护。", None)
    assert present_public_source(
        source(title="地点资料：大雁塔", public_excerpt="西安市雁塔区", canonical_url="https://maps.example.org/place")
    ) == ("maps.example.org", None, "https://maps.example.org/place")


def test_presentation_does_not_change_audit_or_fact_data():
    item = source(public_excerpt="place_id=osm:123", canonical_url="https://example.org/path")
    item.snapshot = {"result": ["original"]}
    facts = [{"name": "大雁塔"}]
    before = deepcopy(item.__dict__), deepcopy(facts)
    assert present_public_source(item, facts) == ("example.org", None, "https://example.org/path")
    assert (item.__dict__, facts) == before
