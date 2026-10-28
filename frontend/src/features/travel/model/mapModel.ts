import { type TransportMode, type TransportSegment } from '../types/entities';
import { type MapProjection } from '../types/report';
import { pointOnTileDatum } from './tileDatum';
import { transportSegmentDisplayMode } from './transportPresentation';

export type MapPoint = [number, number];
export type RouteGeometryKind = 'provider' | 'direct' | 'endpoint';

export interface RouteLineSegment {
  segmentId: string;
  mode: TransportMode;
  geometryKind: RouteGeometryKind;
  points: MapPoint[];
}

type ProjectedRoute = MapProjection['content']['routes'][number];
type MaybeLocated = {
  latitude?: number | null;
  longitude?: number | null;
};

function projectPoint(located: MaybeLocated | null | undefined): MapPoint | null {
  if (
    typeof located?.latitude !== 'number'
    || !Number.isFinite(located.latitude)
    || typeof located.longitude !== 'number'
    || !Number.isFinite(located.longitude)
  ) {
    return null;
  }
  return pointOnTileDatum(located);
}

function providerLine(segment: TransportSegment): RouteLineSegment | null {
  if (!segment.path || segment.path.length < 2) return null;

  const points: MapPoint[] = [];
  for (const pathPoint of segment.path) {
    const point = projectPoint(pathPoint);
    if (!point) return null;
    points.push(point);
  }
  return {
    segmentId: segment.segment_id,
    mode: segment.mode,
    geometryKind: 'provider',
    points,
  };
}

export function routeSegmentLine(segment: TransportSegment): RouteLineSegment | null {
  const from = projectPoint(segment.from_endpoint);
  const to = projectPoint(segment.to_endpoint);
  if (segment.mode === 'flight') {
    return from && to ? {
      segmentId: segment.segment_id,
      mode: segment.mode,
      geometryKind: 'direct',
      points: [from, to],
    } : null;
  }

  const provider = providerLine(segment);
  if (provider) return provider;
  return from && to ? {
    segmentId: segment.segment_id,
    mode: segment.mode,
    geometryKind: 'endpoint',
    points: [from, to],
  } : null;
}

export function routeLines(route: ProjectedRoute): RouteLineSegment[] {
  if (route.route_status !== 'ready') return [];
  return route.segments.flatMap((segment) => {
    const line = routeSegmentLine(segment);
    if (!line) return [];
    return [{
      ...line,
      mode: transportSegmentDisplayMode(route.selected_mode, segment.mode),
    }];
  });
}

export function mapViewportDataKey(points: MapPoint[]): string {
  return JSON.stringify(points);
}

export function resolveMapFocusEntityId(
  selectedEntityId: string | null | undefined,
  linkedEntityId: string | null | undefined,
): string | null {
  return selectedEntityId ?? linkedEntityId ?? null;
}

export function shouldAutoFitMap({
  dataKey,
  previousDataKey,
  hasFocusTarget,
}: {
  dataKey: string;
  previousDataKey: string | null;
  hasFocusTarget: boolean;
}): boolean {
  return !hasFocusTarget && dataKey !== previousDataKey;
}
