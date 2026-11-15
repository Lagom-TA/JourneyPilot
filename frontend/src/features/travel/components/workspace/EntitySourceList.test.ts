import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { type PublicDeliveryBundle } from '../../types/delivery';
import { type PublicCitationProjection } from '../../types/report';
import { EntitySourceList, presentPublicSource, selectVisiblePublicSources } from './EntitySourceList';
import { FullReportView } from './FullReportView';

type Source = PublicCitationProjection['sources'][number];

function source(overrides: Partial<Source> = {}): Source {
  return {
    source_record_id: 'source-1', source_kind: 'external_tool', title: '航班查询结果',
    public_excerpt: '', canonical_url: null, retrieved_at: '2026-11-10T00:00:00Z',
    observed_at: null, ...overrides,
  };
}

function citation(sources: Source[], label = 'name', value: unknown = '大雁塔', entityId = 'entity-1'): PublicCitationProjection {
  return {
    citation_id: `citation-${label}`, entity_ref: { entity_type: 'visit_stop', entity_id: entityId },
    field_paths: [label], fact_status: 'verified',
    supported_values: [{ label, value, unit: null, currency: null }], sources,
  };
}

function bundle(citations: PublicCitationProjection[]): PublicDeliveryBundle {
  return {
    manifest: { run_id: 'run', generation_id: 'generation', bundle_id: 'bundle', workspace_revision: 1, fact_data_revision: 1, weather_data_revision: 1, created_at: '2026-11-10T00:00:00Z' },
    workspace: { itinerary: { day_plans: [], unresolved: [] } },
    report_projection: {
      status: 'ready', source_workspace_revision: 1, source_fact_data_revision: 1, source_weather_data_revision: 1,
      document: { title: '西安一日游', destinations: [{ display_name: '西安' }], days: [], duration_days: 1, cost_summary: null, overview: '西安一日游。', highlights: [], unresolved: [] },
    },
    source_index: { content: { citations } },
  } as unknown as PublicDeliveryBundle;
}

describe('public source presentation', () => {
  it.each(['航班查询结果', '地点搜索结果', '网页搜索结果', '路线查询结果', '天气查询结果', 'search_flights 查询结果', '工具查询结果', '交通路线：深圳北站 → 深圳湾公园', '地点资料：大雁塔'])('hides generic source %s without meaningful content', (title) => {
    expect(presentPublicSource(source({ title, public_excerpt: title }))).toBeNull();
  });

  it.each([
    '找到 2 个结果：大雁塔、钟楼', '找到 3 条网页：景点、餐厅', '已核对 4 条外部结果。',
    '没有匹配的结果', '已取到结果', '地铁 · 深圳北站 → 深圳湾公园 · 约 42 分钟',
    '{"results":[{"name":"大雁塔"}]}', 'place_id=osm:123',
  ])('does not present a tool result summary or raw payload as a source: %s', (public_excerpt) => {
    expect(presentPublicSource(source({ public_excerpt }))).toBeNull();
  });

  it('keeps a real named source or substantive excerpt without inventing a URL or title', () => {
    expect(presentPublicSource(source({ source_kind: 'external_web', title: '陕西历史博物馆开放公告' }))).toEqual({
      title: '陕西历史博物馆开放公告', excerpt: null, href: undefined,
    });
    expect(presentPublicSource(source({ public_excerpt: '12306 公告：预售期为 15 天。' }))).toEqual({
      title: null, excerpt: '12306 公告：预售期为 15 天。', href: undefined,
    });
    expect(presentPublicSource(source({ source_kind: 'rag_chunk', title: '铁路出行手册', public_excerpt: '可在发车前办理退票。' }))).toEqual({
      title: '铁路出行手册', excerpt: '可在发车前办理退票。', href: undefined,
    });
    expect(presentPublicSource(source({ title: '12306 余票查询：乐山→重庆北（参考日无结果）', public_excerpt: '参考日无乐山直达重庆北的可售车次。' }))).toEqual({
      title: '12306 余票查询：乐山→重庆北（参考日无结果）', excerpt: '参考日无乐山直达重庆北的可售车次。', href: undefined,
    });
  });

  it('uses a safe absolute web link with its hostname if the title is generic', () => {
    expect(presentPublicSource(source({ canonical_url: '  https://museum.example.org/visit  ' }))).toEqual({
      title: 'museum.example.org', excerpt: null, href: 'https://museum.example.org/visit',
    });
    expect(presentPublicSource(source({ title: '博物馆开放公告', canonical_url: 'https://museum.example.org/visit', public_excerpt: '博物馆开放公告。周一闭馆。' }))).toEqual({
      title: '博物馆开放公告', excerpt: '周一闭馆。', href: 'https://museum.example.org/visit',
    });
  });

  it.each(['javascript:alert(1)', 'data:text/html,hello', '//evil.example/path', '/fake-source', '#source', 'mailto:info@example.org', 'https://', 'https://museum.example.org@evil.example/', 'https://museum.example.org/\npath'])('does not treat %s as a real safe source URL', (canonical_url) => {
    expect(presentPublicSource(source({ canonical_url }))).toBeNull();
  });

  it('keeps independently meaningful content when the URL is unsafe', () => {
    expect(presentPublicSource(source({ title: '陕西历史博物馆官网公告', canonical_url: 'javascript:alert(1)' }))).toEqual({
      title: '陕西历史博物馆官网公告', excerpt: null, href: undefined,
    });
  });

  it('suppresses repeated entity fields while preserving actual source content', () => {
    expect(presentPublicSource(source({ public_excerpt: '大雁塔' }), ['大雁塔'])).toBeNull();
    expect(presentPublicSource(source({ title: '大雁塔', public_excerpt: '西安市雁塔区' }), ['大雁塔', '西安市雁塔区'])).toBeNull();
    expect(presentPublicSource(source({ public_excerpt: '名称：大雁塔；地址：西安市雁塔区' }), ['大雁塔', '西安市雁塔区'])).toBeNull();
    expect(presentPublicSource(source({ public_excerpt: '出发：深圳北站；抵达：深圳湾公园' }), ['深圳北站', '深圳湾公园'])).toBeNull();
    expect(presentPublicSource(source({ title: 'place_id=osm:123' }))).toBeNull();
    expect(presentPublicSource(source({ public_excerpt: '无关, place_id=osm:123' }), ['无关'])).toBeNull();
    expect(presentPublicSource(source({ title: '找到 2 个结果：大雁塔、钟楼' }))).toBeNull();
    expect(presentPublicSource(source({ title: '地铁 · 深圳北站 → 深圳湾公园 · 约 42 分钟' }))).toBeNull();
    expect(presentPublicSource(source({ source_kind: 'external_web', title: '大雁塔参观须知', public_excerpt: '大雁塔周一闭馆。' }), ['大雁塔'])).not.toBeNull();
  });

  it('only shows a generated location or route record when it has a real link', () => {
    expect(presentPublicSource(source({ title: '地点资料：大雁塔', public_excerpt: '西安市雁塔区' }))).toBeNull();
    expect(presentPublicSource(source({ title: '交通路线：深圳北站 → 深圳湾公园', public_excerpt: '深圳北站 → 深圳湾公园 · 42 分钟' }))).toBeNull();
    expect(presentPublicSource(source({ title: '地点资料：大雁塔', public_excerpt: '保护公告：12 月 1 日闭馆维护。' }))).toEqual({
      title: null, excerpt: '保护公告：12 月 1 日闭馆维护。', href: undefined,
    });
    expect(presentPublicSource(source({ title: '地点资料：大雁塔', public_excerpt: '西安市雁塔区', canonical_url: 'https://maps.example.org/place' }))).toEqual({
      title: 'maps.example.org', excerpt: null, href: 'https://maps.example.org/place',
    });
  });

  it('deduplicates records and mapped field labels, collecting all values before filtering', () => {
    const placeholder = source({ source_record_id: 'placeholder', public_excerpt: '大雁塔' });
    const named = source({ source_record_id: 'named', title: '陕西历史博物馆公告', source_kind: 'external_web' });
    const citations = [
      citation([placeholder, named], 'name', '大雁塔'),
      citation([placeholder, named], 'latitude', 34.3),
      citation([named], 'longitude', 108.9),
      citation([named], '坐标', 108.9),
    ];
    expect(selectVisiblePublicSources(citations)).toEqual([{
      source_record_id: 'named', title: '陕西历史博物馆公告', href: undefined, excerpt: null, labels: ['名称', '坐标'],
    }]);
    expect(citations[0].sources).toHaveLength(2);
  });

  it('checks facts across entities while keeping labels specific to the requested entity', () => {
    const repeated = source({ public_excerpt: '名称：大雁塔；地址：西安市雁塔区' });
    const named = source({ source_record_id: 'named', source_kind: 'external_web', title: '景区开放公告' });
    const citations = [
      citation([repeated, named], 'name', '大雁塔', 'entity-1'),
      citation([repeated, named], 'address', '西安市雁塔区', 'entity-2'),
    ];
    expect(selectVisiblePublicSources(citations, 'entity-1')).toEqual([{
      source_record_id: 'named', title: '景区开放公告', excerpt: null, href: undefined, labels: ['名称'],
    }]);
    expect(selectVisiblePublicSources(citations).map((item) => item.source_record_id)).toEqual(['named']);
  });

  it('retains a usable later projection of the same source record', () => {
    const first = source({ source_record_id: 'same' });
    const later = source({ source_record_id: 'same', canonical_url: 'https://example.org/reference' });
    expect(selectVisiblePublicSources([citation([first]), citation([later], 'address', '西安')])).toEqual([{
      source_record_id: 'same', title: 'example.org', href: 'https://example.org/reference', excerpt: null, labels: ['名称', '地址'],
    }]);
  });
});

describe('source list rendering', () => {
  it('renders no empty entity list, report footer, or reference navigation', () => {
    const data = bundle([citation([source({ public_excerpt: '找到 2 个结果：大雁塔、钟楼' })])]);
    expect(renderToStaticMarkup(React.createElement(EntitySourceList, { bundle: data, entityId: 'entity-1' }))).toBe('');
    const report = renderToStaticMarkup(React.createElement(FullReportView, { bundle: data, allowPdf: false }));
    expect(report).not.toContain('资料来源');
    expect(report).not.toContain('参考资料');
    expect(report).not.toContain('航班查询结果');
    expect(report).not.toContain('找到 2 个结果');
  });

  it('scopes card references to the requested entity without hiding report-wide sources', () => {
    const other = source({ source_kind: 'external_web', title: '钟楼开放公告' });
    const data = bundle([citation([other], 'name', '钟楼', 'entity-2')]);
    expect(renderToStaticMarkup(React.createElement(EntitySourceList, { bundle: data, entityId: 'entity-1' }))).toBe('');
    expect(renderToStaticMarkup(React.createElement(FullReportView, { bundle: data, allowPdf: false }))).toContain('钟楼开放公告');
  });

  it('renders the same deduplicated real sources in both views', () => {
    const linked = source({ source_record_id: 'linked', source_kind: 'external_web', title: '景区开放公告', public_excerpt: '景区开放公告。周一闭馆。', canonical_url: 'https://museum.example.org/notice' });
    const excerptOnly = source({ source_record_id: 'excerpt', public_excerpt: '12306 公告：预售期为 15 天。' });
    const data = bundle([citation([linked, excerptOnly, source()]), citation([linked], 'address', '西安')]);
    const entity = renderToStaticMarkup(React.createElement(EntitySourceList, { bundle: data, entityId: 'entity-1' }));
    const report = renderToStaticMarkup(React.createElement(FullReportView, { bundle: data, allowPdf: false }));
    for (const html of [entity, report]) {
      expect(html.match(/景区开放公告/g)).toHaveLength(1);
      expect(html.match(/周一闭馆/g)).toHaveLength(1);
      expect(html.match(/12306 公告/g)).toHaveLength(1);
      expect(html).toContain('href="https://museum.example.org/notice"');
      expect(html).not.toContain('航班查询结果');
    }
    expect(entity).toContain('名称 · 地址');
    expect(entity.match(/data-source-record=/g)).toHaveLength(2);
    expect(report).toContain('href="#report-references"');
    expect(report).toContain('id="report-references"');
    expect(report).toContain('01');
    expect(report).toContain('02');
  });
});
