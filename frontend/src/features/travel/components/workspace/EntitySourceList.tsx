import { type PublicDeliveryBundle } from '../../types/delivery';
import { type PublicCitationProjection } from '../../types/report';
import { safeHref } from '../../../../lib/safeHref';

type PublicSource = PublicCitationProjection['sources'][number];

export type PublicSourcePresentation = {
  title: string | null;
  excerpt: string | null;
  href: string | undefined;
};

export type VisiblePublicSource = PublicSourcePresentation & {
  source_record_id: string;
  labels: string[];
};

const FACT_FIELD_LABELS: Record<string, string> = {
  name: '名称',
  branch_name: '餐厅名称',
  property_name: '住宿名称',
  place_id: '地点信息',
  provider_place_type: '地点类型',
  provider_country_code: '所在国家或地区',
  address: '地址',
  latitude: '坐标',
  longitude: '坐标',
  opening_window: '开放时间',
  reservation_required: '预约要求',
  visit_type: '类型',
  meal_type: '餐次',
  cuisine_types: '菜系',
  average_spend_cny: '人均消费',
  estimated_cost_cny: '参考费用',
  nightly_price_cny: '每晚价格',
  total_price_cny: '整段价格',
  check_in_date: '入住日期',
  check_out_date: '退房日期',
  check_in_time: '入住时间',
  check_out_time: '退房时间',
  nights: '入住晚数',
  room_type: '房型',
  facilities: '设施',
  availability_status: '房态',
  from_endpoint: '出发站点',
  to_endpoint: '到达站点',
  boarding_stop: '上车站点',
  alighting_stop: '下车站点',
  selected_mode: '交通方式',
  segments: '班次与路线',
  departure_at: '出发时间',
  arrival_at: '抵达时间',
  duration_minutes: '耗时',
  distance_meters: '距离',
  transfer_count: '换乘',
  booking_status: '预订要求',
  total_cost_cny: '票价',
  condition_label: '天气状况',
  high_c: '最高气温',
  low_c: '最低气温',
  precipitation_probability_pct: '降水概率',
  wind_speed_kph: '风速',
};

export function cleanPublicSourceExcerpt(excerpt: string): string {
  const raw = (excerpt || '').trim();
  if (!raw) return '';
  return raw
    .replace(/^(?:\s*[a-z][a-z0-9]*(?:_[a-z0-9]+)+=[^，,；;\s]+[，,；;\s]*)+/, '')
    .replace(/[，,；;\s]*\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+=[^，,；;\s]+[，,；;]?/g, '')
    .replace(/POI 编码与经纬度/g, '地点位置与坐标')
    .replace(/\s+weather forecast$/i, ' 天气预报')
    .replace(/\b(\d+)\s*min\b/g, '$1 分钟')
    .replace(/^[，,；;\s]+|[，,；;\s]+$/g, '');
}

const GENERIC_TITLE = /^(?:(?:航班|航线|机票|车次|中转车次|车站代码|地点|周边|位置|地图|路线|路径|驾车路线|步行路线|公共交通路线|公交路线|交通路线|天气|网页|网络|资料库|酒店|住宿|景点|餐厅|工具|数据|信息|交通)?(?:查询|搜索|检索|定位)(?:结果|记录|信息|数据|摘要)?|地点资料(?:[：:].*)?|交通路线(?:[：:].*)?|天气参考|备用来源记录|外部来源|资料来源|参考资料|来源|未知来源|无标题|已取到结果|没有匹配的结果|未取到结果|无结果|[a-z0-9_:-]+\s+查询结果|unknown|untitled)$/i;
const TOOL_RESULT_SUMMARY = /^(?:找到\s*\d+\s*(?:个结果|条结果|条网页|个地点|条路线)|读到\s*\d+\s*段资料库资料|已核对\s*(?:\d+\s*条)?外部结果|已取到结果|没有匹配的结果|未取到结果|无结果)(?:[：:。.!！…\s]|$)/;
const TOOL_ROUTE_SUMMARY = /^(?:步行|骑行|自驾|公交|地铁|有轨电车|火车|高铁|长途巴士|轮渡)?\s*·?\s*.+?\s*[→➜]\s*.+?(?:\s*·\s*约?\s*\d+\s*分钟)?$/;
const SOURCE_CONTENT_MARKER = /(?:公告|通知|须知|规定|政策|指南|官网|官方网站|官方信息|提醒|说明|报告|票务|官方|建议|提示|开放|闭馆|预售|发售|维修|维护|暂停|关闭|停运|延期|延误|调整|取消|更新|变更|恢复|查询|发布|article|notice|guide|official|policy|report|advisory|update)/i;

function isToolRouteSummary(text: string): boolean {
  return TOOL_ROUTE_SUMMARY.test(text) && !SOURCE_CONTENT_MARKER.test(text);
}
const GENERATED_PLACE_TITLE = /^地点资料[：:]/;
const PLACE_ADDRESS = /^(?:地址[：:]\s*)?[^，,；;。.!！\n]{1,80}(?:省|市|区|县|街道|街|路|号|镇|乡|村|大厦|广场|园区)$/;

function sourceTextKey(text: string): string {
  return text.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
}

function sourceLink(url: string | null): { href: string; host: string } | null {
  const href = safeHref(url);
  // 来源需要可识别的真实网页，而不仅是站内相对路径、锚点或邮件地址。
  if (!href || !/^https?:\/\//i.test(href) || [...href].some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)) return null;
  try {
    const parsed = new URL(href);
    const authority = href.slice(href.indexOf('//') + 2).split(/[/?#]/, 1)[0];
    if (!parsed.hostname || parsed.username || parsed.password || authority.includes('@') || authority.includes('\\')) return null;
    return { href, host: parsed.hostname };
  } catch {
    return null;
  }
}

function collectValueKeys(value: unknown, keys: Set<string>, depth = 0): void {
  if (depth > 5 || value == null) return;
  if (typeof value === 'string' || typeof value === 'number') {
    const key = sourceTextKey(String(value));
    if (key.length >= 2) keys.add(key);
  } else if (Array.isArray(value)) {
    value.forEach((item) => collectValueKeys(item, keys, depth + 1));
  } else if (typeof value === 'object') {
    Object.values(value).forEach((item) => collectValueKeys(item, keys, depth + 1));
  }
}

function isRepeatedEntityExcerpt(excerpt: string, valueKeys: ReadonlySet<string>): boolean {
  const pieces = excerpt.split(/[，,；;。·|\n]+/).map((part) => part.trim()).filter(Boolean);
  return pieces.length > 0 && pieces.every((piece) => {
    const value = piece.replace(/^(?:名称|餐厅名称|住宿名称|地址|地点|出发站点|到达站点|出发时间|抵达时间|出发|抵达|耗时|距离|换乘|交通方式|开放时间|营业时间|费用|参考费用|票价|坐标)[：:]\s*/, '');
    const key = sourceTextKey(value);
    return key.length >= 2 && valueKeys.has(key);
  });
}

/** 返回可展示的来源文本；仅使用来源记录中已有的链接和内容。 */
export function presentPublicSource(source: PublicSource, supportedValues: readonly unknown[] = []): PublicSourcePresentation | null {
  const link = sourceLink(source.canonical_url);
  const rawTitle = (source.title || '').trim();
  const valueKeys = new Set<string>();
  supportedValues.forEach((value) => collectValueKeys(value, valueKeys));
  const title = rawTitle && !GENERIC_TITLE.test(rawTitle) && !TOOL_RESULT_SUMMARY.test(rawTitle)
    && !rawTitle.startsWith('{') && !rawTitle.startsWith('[')
    && !(source.source_kind === 'external_tool' && !cleanPublicSourceExcerpt(rawTitle))
    && !(source.source_kind === 'external_tool' && (isToolRouteSummary(rawTitle) || isRepeatedEntityExcerpt(rawTitle, valueKeys))) ? rawTitle : '';
  const rawExcerpt = (source.public_excerpt || '').trim();
  let excerpt = rawExcerpt.startsWith('{') || rawExcerpt.startsWith('[') ? '' : cleanPublicSourceExcerpt(rawExcerpt);

  if (excerpt && (GENERIC_TITLE.test(excerpt) || TOOL_RESULT_SUMMARY.test(excerpt)
    || (source.source_kind === 'external_tool' && GENERATED_PLACE_TITLE.test(rawTitle) && PLACE_ADDRESS.test(excerpt))
    || (source.source_kind === 'external_tool' && isToolRouteSummary(excerpt))
    || (source.source_kind === 'external_tool' && isRepeatedEntityExcerpt(excerpt, valueKeys)))) {
    excerpt = '';
  }
  if (title && excerpt) {
    if (sourceTextKey(title) === sourceTextKey(excerpt)) {
      excerpt = '';
    } else if (excerpt.startsWith(title) && /^[\s。:：;；,，—-]/.test(excerpt.slice(title.length))) {
      excerpt = excerpt.slice(title.length).replace(/^[\s。:：;；,，—-]+/, '');
    }
  }

  const displayTitle = title || link?.host || null;
  if (!displayTitle && !excerpt) return null;
  return { title: displayTitle, excerpt: excerpt || null, href: link?.href };
}

/** 按来源记录合并引用，先收集全部事实再判断是否有可见内容。 */
export function selectVisiblePublicSources(citations: readonly PublicCitationProjection[], entityId?: string): VisiblePublicSource[] {
  const groups = new Map<string, { sources: PublicSource[]; labels: Set<string>; values: unknown[]; selected: boolean }>();
  for (const citation of citations) {
    for (const source of citation.sources) {
      const group = groups.get(source.source_record_id) ?? { sources: [], labels: new Set<string>(), values: [], selected: false };
      group.sources.push(source);
      const selected = entityId === undefined || citation.entity_ref.entity_id === entityId;
      group.selected ||= selected;
      citation.supported_values.forEach(({ label, value }) => {
        const text = (FACT_FIELD_LABELS[label] ?? label).trim();
        if (selected && text) group.labels.add(text);
        group.values.push(value);
      });
      groups.set(source.source_record_id, group);
    }
  }
  return [...groups.entries()].flatMap(([source_record_id, group]) => {
    if (!group.selected) return [];
    const presentations = group.sources
      .map((source) => presentPublicSource(source, group.values))
      .filter((item): item is PublicSourcePresentation => item !== null);
    // 如果同一记录的不同投影信息不一致，优先展示有链接的版本。
    const presentation = presentations.find((item) => item.href) ?? presentations[0];
    return presentation ? [{ source_record_id, labels: [...group.labels], ...presentation }] : [];
  });
}

export function EntitySourceList({ bundle, entityId }: { bundle: PublicDeliveryBundle; entityId: string }) {
  const sources = selectVisiblePublicSources(bundle.source_index.content.citations, entityId);
  if (sources.length === 0) return null;
  return (
    <details className="journey-entity-sources">
      <summary>资料来源</summary>
      <ul>
        {sources.map(({ source_record_id, labels, title, href, excerpt }) => (
          <li key={source_record_id} data-source-record={source_record_id}>
            {labels.length > 0 && <span>{labels.join(' · ')}</span>}
            {title && (href ? <a href={href} target="_blank" rel="noreferrer">{title}</a> : <p>{title}</p>)}
            {excerpt && <p>{excerpt}</p>}
          </li>
        ))}
      </ul>
    </details>
  );
}
