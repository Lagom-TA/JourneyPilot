import { type DaySummaryVM } from './itineraryPresentation';
import { type PublicDeliveryBundle } from '../types/delivery';

export interface TripSegment {
  id: string;
  label: string;
  days: DaySummaryVM[];
  dateLabel: string;
}

/** 同一城市再次到访时保留独立停留段，以免改变日程顺序。 */
export function tripSegments(days: readonly DaySummaryVM[]): TripSegment[] {
  const segments: TripSegment[] = [];
  for (const day of days) {
    const label = day.destinationLabel || '行程';
    let segment = segments[segments.length - 1];
    if (!segment || segment.label !== label) {
      segment = { id: day.dayId, label, days: [], dateLabel: '' };
      segments.push(segment);
    }
    segment.days.push(day);
    const first = segment.days[0];
    segment.dateLabel = first.dateLabel && day.dateLabel
      ? first.dateLabel === day.dateLabel ? first.dateLabel : `${first.dateLabel} — ${day.dateLabel}`
      : first.day === day.day ? `第 ${day.day} 天` : `第 ${first.day} — ${day.day} 天`;
  }
  return segments;
}

export function unresolvedForDay(bundle: PublicDeliveryBundle, dayId: string): string[] {
  const day = bundle.workspace.itinerary.day_plans.find((item) => item.day_id === dayId);
  if (!day) return [];
  const dayPattern = new RegExp(`第\\s*${day.day}\\s*天`);
  return bundle.workspace.itinerary.unresolved.filter((text) => dayPattern.test(text) || Boolean(day.date && text.includes(day.date)));
}

export function isUnscheduledItem(text: string): boolean {
  return /尚未安排|未安排|尚未覆盖|未覆盖/.test(text);
}

/** 仅排除独立的日期假设和通用核对提示，保留具体行程缺口。 */
export function isUsefulUnresolvedItem(text: string): boolean {
  const value = text.trim().replace(/[。；;\s]+$/g, '');
  if (!value) return false;
  if (/^(?:入住|出发|旅行|行程|查询)?日期(?:为|是|属于)?(?:规划)?(?:假设|暂定)$/u.test(value.replace(/[（）()]/g, ''))) return false;
  return !/^(?:出行|出发|预订|前往)前(?:请|需|建议)?(?:核对|确认)(?:开放时间|营业时间|票价|门票价格|预约信息|营业安排|费用)(?:[、，,和与及/](?:开放时间|营业时间|票价|门票价格|预约信息|营业安排|费用))*$/u.test(value);
}
