import { type TripSegment } from '../../model/itineraryNavigation';

interface TripRouteNavProps {
  segments: readonly TripSegment[];
  activeSegmentId: string | null;
  onSelect: (segmentId: string | null) => void;
}

export function TripRouteNav({ segments, activeSegmentId, onSelect }: TripRouteNavProps) {
  return (
    <nav className="journey-route-nav" aria-label="按城市查看行程" data-testid="itinerary-route-nav">
      <button type="button" className="journey-route-all" aria-pressed={activeSegmentId === null} onClick={() => onSelect(null)}>全程</button>
      {segments.length > 4 ? (
        <select aria-label="城市停留段" value={activeSegmentId ?? ''} onChange={(event) => onSelect(event.target.value || null)}>
          <option value="">选择城市停留段</option>
          {segments.map((segment) => <option key={segment.id} value={segment.id}>{segment.label} · {segment.dateLabel}</option>)}
        </select>
      ) : segments.map((segment) => (
        <button key={segment.id} type="button" aria-pressed={activeSegmentId === segment.id} onClick={() => onSelect(segment.id)} style={{ flexGrow: segment.days.length }}>
          <strong title={segment.label}>{segment.label}</strong>
          <span>{segment.dateLabel.replace(/(\d+)月(\d+)日/g, (_, month: string, day: string) => `${month.padStart(2, '0')}.${day.padStart(2, '0')}`)}</span>
        </button>
      ))}
    </nav>
  );
}
