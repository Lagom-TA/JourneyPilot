import { useReducedMotion } from "motion/react";
import { MapContainer, Marker, Polyline, TileLayer, ZoomControl, useMap, useMapEvents } from "react-leaflet";
import { type MapProjection } from "../../types/report";
import { pointOnTileDatum } from "../../model/tileDatum";
import { transportModeColor } from "../../model/transportPresentation";
import {
    groupBundleMapPlaces,
    type BundleMapPlace,
    type BundleMapPlaceGroup,
} from "../../model/mapPlaces";
import {
    mapViewportDataKey,
    resolveMapFocusEntityId,
    routeLines,
    shouldAutoFitMap,
    type MapPoint,
    type RouteLineSegment,
} from "../../model/mapModel";
import React from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { getMapTileConfig } from '../../../../lib/mapConfig';
import { buildGroupPinHtml, buildPlacePinHtml } from '../../model/mapPinHtml';
import { cssEasing, duration } from '../../../../lib/motion';

type ProjectedRoute = MapProjection['content']['routes'][number];
interface BundleMapLeafletProps {
    places: BundleMapPlace[];
    routes: ProjectedRoute[];
    selectedEntityId: string | null;
    onSelectEntity: (entityId: string) => void;
    linkedEntityId?: string | null;
    onLinkEntity?: (entityId: string | null) => void;
    overlayOffset?: number;
    bottomOffset?: number;
}
const TILE = getMapTileConfig();
const FALLBACK_COLOR = 'var(--color-accent)';
function placeColor(): string {
    if (typeof window === 'undefined') return FALLBACK_COLOR;
    const token = window.getComputedStyle(document.documentElement)
        .getPropertyValue('--color-accent')
        .trim();
    return token || FALLBACK_COLOR;
}
interface RouteLines {
    route: ProjectedRoute;
    segments: RouteLineSegment[];
}
function useRouteLines(routes: ProjectedRoute[]): RouteLines[] {
    return React.useMemo(() => routes.map((route) => ({ route, segments: routeLines(route) })), [routes]);
}
const placePoint = pointOnTileDatum;
type PinState = 'selected' | 'linked' | 'idle';
const PIN_STATE_STYLE: Record<PinState, {
    transform: string;
    boxShadow: string;
}> = {
    selected: {
        transform: 'scale(1.22)',
        boxShadow: 'var(--shadow-map-pin-selected)',
    },
    linked: {
        transform: 'scale(1.14)',
        boxShadow: 'var(--shadow-map-pin-linked)',
    },
    idle: { transform: 'scale(1)', boxShadow: 'var(--shadow-map-pin-idle)' },
};
function placeIcon(place: BundleMapPlace, color: string, offset: [number, number] = [0, 0]): L.DivIcon {
    const idle = PIN_STATE_STYLE.idle;
    const endpoint = place.markerKind === 'transport_endpoint';
    const size = endpoint ? 18 : 30;
    const center = size / 2;
    const content = endpoint
        ? ''
        : String(place.sequence > 0 ? place.sequence : '•');
    return L.divIcon({
        className: '',
        html: buildPlacePinHtml({
            sequence: place.sequence,
            entityId: place.entity_ref.entity_id,
            markerKind: place.markerKind,
            mode: place.modes[0] ?? '',
            color,
            endpoint,
            size,
            content,
            boxShadow: idle.boxShadow,
            transform: idle.transform,
        }),
        iconSize: [size, size],
        iconAnchor: [center - offset[0], center - offset[1]],
        popupAnchor: [0, -center - 2],
    });
}
function groupIcon(group: BundleMapPlaceGroup, color: string): L.DivIcon {
    return L.divIcon({
        className: '',
        html: buildGroupPinHtml({ groupId: group.id, color, count: group.places.length }),
        iconSize: [34, 34],
        iconAnchor: [17, 17],
    });
}
function applyPinState(pin: HTMLElement, state: PinState): void {
    const { transform, boxShadow } = PIN_STATE_STYLE[state];
    pin.style.transform = transform;
    pin.style.boxShadow = boxShadow;
    if (state === 'linked') pin.dataset.linked = 'on';
    else delete pin.dataset.linked;
}
interface PinBase {
    key: string;
    position: [number, number];
    icon: L.DivIcon;
}
interface PlacePin extends PinBase {
    kind: 'place';
    place: BundleMapPlace;
}
interface GroupPin extends PinBase {
    kind: 'group';
    group: BundleMapPlaceGroup;
}
type Pin = PlacePin | GroupPin;
function expandedOffset(index: number, total: number): [number, number] {
    if (total <= 1) return [0, 0];
    if (total > 10) {
        const radius = 30 * Math.sqrt(index + 1);
        const angle = index * 2.399963;
        return [Math.cos(angle) * radius, Math.sin(angle) * radius];
    }
    const radius = Math.min(54, 28 + total * 3);
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / total;
    return [Math.cos(angle) * radius, Math.sin(angle) * radius];
}
function usePins(groups: BundleMapPlaceGroup[], expandedGroupId: string | null): Pin[] {
    const cache = React.useRef(new Map<string, L.DivIcon>()).current;
    return React.useMemo(() => {
        const pins: Pin[] = [];
        for (const group of groups) {
            const position = placePoint(group.places[0]);
            if (!position) continue;
            if (group.places.length > 1 && group.id !== expandedGroupId) {
                const color = 'var(--color-chart)';
                const key = `${group.id}|${color}`;
                let icon = cache.get(key);
                if (!icon) {
                    icon = groupIcon(group, color);
                    cache.set(key, icon);
                }
                pins.push({ kind: 'group', key: group.id, group, position, icon });
                continue;
            }
            group.places.forEach((place, index) => {
                const point = placePoint(place);
                if (!point) return;
                const offset = expandedOffset(index, group.places.length);
                const color = place.markerKind === 'transport_endpoint'
                    ? transportModeColor(place.modes[0] ?? 'other')
                    : placeColor();
                const key = `${place.markerId}|${place.sequence}|${color}|${offset.join(',')}`;
                let icon = cache.get(key);
                if (!icon) {
                    icon = placeIcon(place, color, offset);
                    cache.set(key, icon);
                }
                pins.push({ kind: 'place', key: place.markerId, place, position: point, icon });
            });
        }
        return pins;
    }, [cache, expandedGroupId, groups]);
}
interface RouteSegmentProps {
    routeId: string;
    segmentIndex: number;
    segment: RouteLineSegment;
    color: string;
    selected: boolean;
    linked: boolean;
    dimmed: boolean;
    seen: Set<string>;
    onSelect: () => void;
    onLink: (event: L.LeafletMouseEvent) => void;
    onUnlink: (event: L.LeafletMouseEvent) => void;
}
function RouteSegment({ routeId, segmentIndex, segment, color, selected, linked, dimmed, seen, onSelect, onLink, onUnlink }: RouteSegmentProps) {
    const polyline = React.useRef<L.Polyline | null>(null);
    const reducedMotion = useReducedMotion();
    const geometryKey = `${routeId}:${segmentIndex}:${JSON.stringify(segment.points)}`;
    React.useEffect(() => {
        const path = polyline.current?.getElement();
        path?.setAttribute('data-route-entity', routeId);
        path?.setAttribute('data-route-segment', segment.segmentId);
        path?.setAttribute('data-route-mode', segment.mode);
        path?.setAttribute('data-route-geometry', segment.geometryKind);
    }, [routeId, segment.geometryKind, segment.mode, segment.segmentId]);
    React.useEffect(() => {
        if (reducedMotion || seen.has(geometryKey)) return;
        const frame = window.requestAnimationFrame(() => {
            const path = polyline.current?.getElement();
            if (!(path instanceof SVGPathElement) || seen.has(geometryKey)) return;
            seen.add(geometryKey);
            const length = path.getTotalLength();
            if (!Number.isFinite(length) || length <= 0) return;
            path.style.strokeDasharray = `${length}`;
            path.style.strokeDashoffset = `${length}`;
            const animation = path.animate([
                { strokeDashoffset: length },
                { strokeDashoffset: 0 },
            ], { duration: duration.emphasis * 1000, easing: cssEasing.decelerate });
            animation.onfinish = () => {
                path.style.strokeDasharray = '';
                path.style.strokeDashoffset = '';
            };
        });
        return () => window.cancelAnimationFrame(frame);
    }, [geometryKey, reducedMotion, seen]);
    const { points, geometryKind } = segment;
    return (<React.Fragment>
      <Polyline positions={points} interactive={false} pathOptions={{
            className: `journey-route-halo is-${geometryKind}`,
            color: 'var(--color-panel)',
            weight: selected ? 10 : linked ? 8.5 : 6.5,
            opacity: selected ? 0.95 : 0.78,
            dashArray: geometryKind === 'endpoint' ? '8 8' : undefined,
        }}/>
      <Polyline ref={polyline} positions={points} pathOptions={{
            className: `journey-route-line is-${geometryKind}`,
            color,
            weight: selected ? 7 : linked ? 5.5 : 3.5,
            opacity: selected || linked ? 0.95 : dimmed ? 0.3 : 0.72,
            dashArray: geometryKind === 'endpoint' ? '8 8' : undefined,
        }} eventHandlers={{ click: onSelect, mouseover: onLink, mouseout: onUnlink }}/>
    </React.Fragment>);
}
interface EntranceMarkerProps {
    pin: PlacePin;
    selected: boolean;
    linked: boolean;
    seen: Set<string>;
    onSelect: () => void;
    onLink: (event: L.LeafletMouseEvent) => void;
    onUnlink: (event: L.LeafletMouseEvent) => void;
}
function EntranceMarker({ pin, selected, linked, seen, onSelect, onLink, onUnlink }: EntranceMarkerProps) {
    const marker = React.useRef<L.Marker | null>(null);
    const reducedMotion = useReducedMotion();
    React.useEffect(() => {
        if (reducedMotion || seen.has(pin.place.markerId)) return;
        const frame = window.requestAnimationFrame(() => {
            const element = marker.current?.getElement()?.querySelector<HTMLElement>('[data-bundle-map-marker]');
            if (!element || seen.has(pin.place.markerId)) return;
            seen.add(pin.place.markerId);
            element.animate([
                { opacity: 0, transform: 'scale(.78)' },
                { opacity: 1, transform: 'scale(1)' },
            ], { duration: duration.page * 1000, easing: cssEasing.decelerate });
        });
        return () => window.cancelAnimationFrame(frame);
    }, [pin.place.markerId, reducedMotion, seen]);
    return (<Marker ref={marker} position={pin.position} icon={pin.icon} zIndexOffset={selected ? 1000 : linked ? 800 : 0} eventHandlers={{ click: onSelect, mouseover: onLink, mouseout: onUnlink }} keyboard title={`${pin.place.markerKind === 'transport_endpoint' ? '交通站点 · ' : ''}${pin.place.name}`}/>);
}
const CLOSE_ENOUGH_ZOOM = 14;
const FOCUS_ZOOM = 15;
function MapViewport({ places, lines, selectedEntityId, overlayOffset = 0, bottomOffset = 0 }: Pick<BundleMapLeafletProps, 'places' | 'selectedEntityId' | 'overlayOffset' | 'bottomOffset'> & {
    lines: RouteLines[];
}) {
    const map = useMap();
    const lastTarget = React.useRef('');
    const lastDataKey = React.useRef<string | null>(null);
    const lastOverlayOffset = React.useRef(overlayOffset);
    const lastBottomOffset = React.useRef(bottomOffset);
    const previousContext = React.useRef<string | null>(null);
    const viewHistory = React.useRef(new Map<string, { center: L.LatLng; zoom: number }>());
    const reducedMotion = useReducedMotion();
    // 相机只认显式选中：悬浮／聚焦高亮不进入这个 effect 的依赖，也不构成聚焦目标。
    React.useEffect(() => {
        const focusedEntityId = resolveMapFocusEntityId(selectedEntityId);
        const focusedPlace = places.find((place) => (
            place.markerKind !== 'transport_endpoint' && place.entity_ref.entity_id === focusedEntityId
        ));
        const focusedPoint = focusedPlace ? placePoint(focusedPlace) : null;
        const focusedRoute = focusedPoint ? undefined : lines.find((line) => line.route.entity_ref.entity_id === focusedEntityId);
        const focusedPoints = focusedRoute?.segments.flatMap((segment) => segment.points) ?? [];
        const allPoints: MapPoint[] = [
            ...places.flatMap((place) => { const point = placePoint(place); return point ? [point] : []; }),
            ...lines.flatMap((line) => line.segments.flatMap((segment) => segment.points)),
        ];
        const topPadding = overlayOffset > 0 ? 96 : 156;
        const dataKey = mapViewportDataKey(allPoints);
        const previousDataKey = lastDataKey.current;
        const previousOverlayOffset = lastOverlayOffset.current;
        const previousBottomOffset = lastBottomOffset.current;
        lastDataKey.current = dataKey;
        lastOverlayOffset.current = overlayOffset;
        lastBottomOffset.current = bottomOffset;
        const hasSelection = Boolean(focusedPoint) || focusedPoints.length > 0;
        const contextKey = `${dataKey}:${overlayOffset}:${bottomOffset}`;
        if (previousContext.current !== contextKey) {
            if (previousContext.current) viewHistory.current.set(previousContext.current, { center: map.getCenter(), zoom: map.getZoom() });
            previousContext.current = contextKey;
            const saved = viewHistory.current.get(contextKey);
            if (saved && !hasSelection) {
                map.setView(saved.center, saved.zoom, { animate: !reducedMotion });
                return;
            }
        }
        const fitAllOnContextChange = shouldAutoFitMap({
            dataKey,
            previousDataKey,
            hasSelection,
        }) || (!hasSelection && (previousOverlayOffset !== overlayOffset || previousBottomOffset !== bottomOffset));
        if (focusedPlace && focusedPoint) {
            const key = `place:${focusedPlace.entity_ref.entity_id}`;
            if (lastTarget.current === key) return;
            lastTarget.current = key;
            const target = map.unproject(map.project(L.latLng(focusedPoint), FOCUS_ZOOM).subtract([overlayOffset / 2, -bottomOffset / 2]), FOCUS_ZOOM);
            if (map.getZoom() >= CLOSE_ENOUGH_ZOOM) map.panTo(target, { animate: !reducedMotion });
            else if (reducedMotion) map.setView(target, FOCUS_ZOOM, { animate: false });
            else map.flyTo(target, FOCUS_ZOOM, { duration: duration.mapFocus });
            return;
        }
        if (focusedRoute && focusedPoints.length > 0) {
            const key = `route:${focusedRoute.route.entity_ref.entity_id}`;
            if (lastTarget.current === key) return;
            lastTarget.current = key;
            const bounds = L.latLngBounds(focusedPoints);
            map.fitBounds(bounds, { paddingTopLeft: [overlayOffset + 36, topPadding], paddingBottomRight: [36, bottomOffset + 36], maxZoom: FOCUS_ZOOM, animate: !reducedMotion });
            return;
        }
        lastTarget.current = '';
        if (!fitAllOnContextChange || allPoints.length === 0) return;
        if (allPoints.length === 1) map.setView(map.unproject(map.project(allPoints[0], 13).subtract([overlayOffset / 2, -bottomOffset / 2]), 13), 13, { animate: !reducedMotion });
        else map.fitBounds(L.latLngBounds(allPoints), { paddingTopLeft: [overlayOffset + 32, topPadding], paddingBottomRight: [32, bottomOffset + 32], maxZoom: FOCUS_ZOOM, animate: !reducedMotion });
    }, [map, places, lines, selectedEntityId, reducedMotion, overlayOffset, bottomOffset]);
    React.useEffect(() => {
        map.invalidateSize();
        const frame = window.requestAnimationFrame(() => map.invalidateSize());
        const observer = new ResizeObserver(() => map.invalidateSize());
        observer.observe(map.getContainer());
        return () => {
            window.cancelAnimationFrame(frame);
            observer.disconnect();
        };
    }, [map]);
    return null;
}
type BasemapState = 'loading' | 'ready' | 'degraded';
const BASEMAP_NOTICE: Record<BasemapState, string | null> = {
    loading: '底图加载中…',
    ready: null,
    degraded: '底图暂时没加载出来 · 针的位置仍然准确',
};
function MapScale({ onZoom }: { onZoom: (zoom: number) => void }) {
    const map = useMapEvents({ zoomend: () => onZoom(map.getZoom()) });
    React.useEffect(() => { onZoom(map.getZoom()); }, [map, onZoom]);
    return null;
}
export const BundleMapLeaflet: React.FC<BundleMapLeafletProps> = ({ places, routes, selectedEntityId, onSelectEntity, linkedEntityId = null, onLinkEntity, overlayOffset = 0, bottomOffset = 0 }) => {
    const reducedMotion = useReducedMotion();
    const [basemap, setBasemap] = React.useState<BasemapState>('loading');
    const [expandedGroupId, setExpandedGroupId] = React.useState<string | null>(null);
    const [zoom, setZoom] = React.useState(12);
    const mapInstance = React.useRef<L.Map | null>(null);
    const tileErrors = React.useRef(0);
    const pinRoot = React.useRef<HTMLDivElement>(null);
    const seenRoutes = React.useRef(new Set<string>()).current;
    const seenPins = React.useRef(new Set<string>()).current;
    // 地图可能在缩放动画结束前卸载；移除前清除缩放标记并停止动画，避免结束回调访问已卸载的地图。
    const guardTeardown = React.useCallback((map: L.Map | null) => {
        if (!map) return;
        mapInstance.current = map;
        const instance = map as unknown as { _animatingZoom: boolean; _teardownGuarded?: true };
        if (instance._teardownGuarded) return;
        instance._teardownGuarded = true;
        const removeMap = map.remove.bind(map);
        map.remove = () => {
            instance._animatingZoom = false;
            map.stop();
            return removeMap();
        };
    }, []);
    const link = (entityId: string | null) => (event: L.LeafletMouseEvent) => {
        if ((event.originalEvent as PointerEvent | undefined)?.pointerType === 'touch') return;
        onLinkEntity?.(entityId);
    };
    const lines = useRouteLines(routes);
    const groups = React.useMemo(() => groupBundleMapPlaces(places, (place) => {
        const point = placePoint(place);
        return point ? L.CRS.EPSG3857.latLngToPoint(L.latLng(point), zoom) : null;
    }), [places, zoom]);
    const pins = usePins(groups, expandedGroupId);
    const focusedEntityId = resolveMapFocusEntityId(selectedEntityId);
    React.useEffect(() => {
        setExpandedGroupId((current) => current && groups.some((group) => group.id === current) ? current : null);
    }, [groups]);
    React.useEffect(() => {
        if (!focusedEntityId) return;
        const group = groups.find((candidate) => candidate.places.length > 1 && candidate.places.some(
            (place) => place.entity_ref.entity_id === focusedEntityId,
        ));
        if (group) setExpandedGroupId(group.id);
    }, [focusedEntityId, groups]);
    React.useEffect(() => {
        const root = pinRoot.current;
        if (!root) return;
        root.querySelectorAll<HTMLElement>('[data-bundle-map-entity]').forEach((pin) => {
            const entityId = pin.dataset.bundleMapEntity;
            applyPinState(pin, entityId === selectedEntityId ? 'selected' : entityId === linkedEntityId ? 'linked' : 'idle');
        });
        root.querySelectorAll<HTMLElement>('[data-bundle-map-group]').forEach((pin) => {
            const group = groups.find((item) => item.id === pin.dataset.bundleMapGroup);
            const selected = group?.places.some((place) => place.entity_ref.entity_id === selectedEntityId);
            const linked = group?.places.some((place) => place.entity_ref.entity_id === linkedEntityId);
            applyPinState(pin, selected ? 'selected' : linked ? 'linked' : 'idle');
        });
    }, [groups, pins, selectedEntityId, linkedEntityId]);
    const anchor = React.useRef<[number, number] | null>(null);
    const firstPoint = pins[0]?.position ?? lines.flatMap((line) => line.segments.flatMap((segment) => segment.points))[0] ?? null;
    if (firstPoint) anchor.current = firstPoint;
    if (!anchor.current) return null;
    return (<div ref={pinRoot} className="relative h-full w-full" data-testid="bundle-leaflet-map" data-basemap-state={basemap}>
      {BASEMAP_NOTICE[basemap] && (<p data-testid="bundle-map-basemap-state" role={basemap === 'degraded' ? 'status' : undefined} className="pointer-events-none absolute left-1/2 top-3 z-map-controls max-w-[92%] -translate-x-1/2 truncate rounded-label bg-panel/90 px-2.5 py-1 text-[11px] font-medium text-ink-secondary shadow-sm backdrop-blur">
          {BASEMAP_NOTICE[basemap]}
        </p>)}
    <MapContainer ref={guardTeardown} center={anchor.current} zoom={12} zoomControl={false} attributionControl preferCanvas={false} className="h-full w-full">
      <TileLayer url={TILE.url} {...(TILE.subdomains ? { subdomains: TILE.subdomains } : {})} attribution={TILE.attribution} maxZoom={18} eventHandlers={{
            loading: () => { tileErrors.current = 0; },
            load: () => setBasemap(tileErrors.current > 0 ? 'degraded' : 'ready'),
            tileerror: () => { tileErrors.current += 1; setBasemap('degraded'); },
        }}/>
      <ZoomControl position="bottomright" />
      <MapScale onZoom={setZoom} />
      <MapViewport places={places} lines={lines} selectedEntityId={selectedEntityId} overlayOffset={overlayOffset} bottomOffset={bottomOffset}/>
      {lines.map(({ route, segments }) => {
            const routeId = route.entity_ref.entity_id;
            const selected = routeId === selectedEntityId;
            const linked = routeId === linkedEntityId;
            return segments.map((segment, segmentIndex) => (<RouteSegment
              key={`${routeId}:${segment.segmentId}:${segmentIndex}`}
              routeId={routeId}
              segmentIndex={segmentIndex}
              segment={segment}
              color={transportModeColor(segment.mode)}
              selected={selected}
              linked={linked}
              dimmed={Boolean(selectedEntityId)}
              seen={seenRoutes}
              onSelect={() => onSelectEntity(routeId)}
              onLink={link(routeId)}
              onUnlink={link(null)}
            />));
        })}
      {pins.map((pin) => {
            if (pin.kind === 'group') {
                return (<Marker
                  key={pin.key}
                  position={pin.position}
                  icon={pin.icon}
                  zIndexOffset={500}
                  eventHandlers={{ click: () => {
                    const points = pin.group.places.flatMap((place) => { const point = placePoint(place); return point ? [point] : []; });
                    const bounds = L.latLngBounds(points);
                    if (mapInstance.current && !bounds.getNorthEast().equals(bounds.getSouthWest(), 0.00001) && mapInstance.current.getZoom() < 17) {
                        mapInstance.current.fitBounds(bounds, { paddingTopLeft: [overlayOffset + 48, 110], paddingBottomRight: [48, bottomOffset + 48], maxZoom: 17, animate: !reducedMotion });
                    } else setExpandedGroupId(pin.group.id);
                  } }}
                  keyboard
                  title={`附近 ${pin.group.places.length} 个位置，点击展开`}
                />);
            }
            const entityId = pin.place.entity_ref.entity_id;
            return (<EntranceMarker
              key={pin.key}
              pin={pin}
              selected={entityId === selectedEntityId}
              linked={entityId === linkedEntityId}
              seen={seenPins}
              onSelect={() => onSelectEntity(entityId)}
              onLink={link(entityId)}
              onUnlink={link(null)}
            />);
        })}
    </MapContainer>
    </div>);
};
