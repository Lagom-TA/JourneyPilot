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
