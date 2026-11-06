import { type PublicDeliveryBundle } from '../../types/delivery';
import { safeHref } from '../../../../lib/safeHref';

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
    .trim() || raw;
}

export function EntitySourceList({ bundle, entityId }: { bundle: PublicDeliveryBundle; entityId: string }) {
  const citations = bundle.source_index.content.citations.filter((item) => item.entity_ref.entity_id === entityId && item.sources.length > 0);
  if (citations.length === 0) return null;
  type Source = typeof citations[number]['sources'][number];
  const sources = new Map<string, { source: Source; labels: Set<string> }>();
  for (const citation of citations) {
    for (const source of citation.sources) {
      const entry = sources.get(source.source_record_id) ?? { source, labels: new Set<string>() };
      citation.supported_values.forEach((value) => entry.labels.add(FACT_FIELD_LABELS[value.label] ?? value.label));
      sources.set(source.source_record_id, entry);
    }
  }
  return (
    <details className="journey-entity-sources">
      <summary>资料来源</summary>
      <ul>
        {[...sources.values()].map(({ source, labels }) => {
          const href = safeHref(source.canonical_url);
          return (
            <li key={source.source_record_id} data-source-record={source.source_record_id}>
              {labels.size > 0 && <span>{[...labels].join(' · ')}</span>}
              {href ? <a href={href} target="_blank" rel="noreferrer">{source.title}</a> : <p>{source.title}</p>}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
