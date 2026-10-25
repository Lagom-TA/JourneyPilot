import { useReducedMotion } from "motion/react";
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import { type MapProjection } from "../../types/report";
import { type TransportEndpoint } from "../../types/entities";
import { pointOnTileDatum } from "../../model/tileDatum";
import React from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
type ProjectedPlace = MapProjection['content']['places'][number];
type ProjectedRoute = MapProjection['content']['routes'][number];
export interface BundleMapPlace extends ProjectedPlace {
    days: number[];
    sequence: number;
}
interface BundleMapLeafletProps {
    places: BundleMapPlace[];
    routes: ProjectedRoute[];
    selectedEntityId: string | null;
    onSelectEntity: (entityId: string) => void;
    linkedEntityId?: string | null;
    onLinkEntity?: (entityId: string | null) => void;
}
const TILE_URL = 'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}';
const TILE_SUBDOMAINS = ['1', '2', '3', '4'];
const TILE_ATTRIBUTION = '&copy; <a href="https://amap.com/">高德地图</a>';
const FALLBACK_COLORS = [
    '#007AFF', '#34C759', '#FF9500', '#FF3B30', '#AF52DE',
    '#5856D6', '#FF2D55', '#00C7BE', '#FFD60A', '#64D2FF',
];
function colorForIndex(index: number): string {
    if (typeof window === 'undefined')
        return FALLBACK_COLORS[index % FALLBACK_COLORS.length];
    const token = window.getComputedStyle(document.documentElement)
        .getPropertyValue(`--chart-day-${(index % FALLBACK_COLORS.length) + 1}`)
        .trim();
    return token || FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}
interface RouteLines {
    route: ProjectedRoute;
    segments: Array<[
        number,
        number
    ][]>;
}
function useRouteLines(routes: ProjectedRoute[]): RouteLines[] {
    return React.useMemo(() => routes.map((route) => ({ route, segments: routeLines(route) })), [routes]);
}
const coordinate = (endpoint: TransportEndpoint) => pointOnTileDatum(endpoint);
const placePoint = pointOnTileDatum;
function routeLines(route: ProjectedRoute): Array<[
    number,
    number
][]> {
    if (route.route_status !== 'ready')
        return [];
    return route.segments.flatMap((segment) => {
        const from = coordinate(segment.from_endpoint);
        const to = coordinate(segment.to_endpoint);
        return from && to ? [[from, to]] : [];
    });
}
type PinState = 'selected' | 'linked' | 'idle';
const PIN_STATE_STYLE: Record<PinState, (color: string) => {
    transform: string;
    boxShadow: string;
}> = {
    selected: (color) => ({
        transform: 'scale(1.14)',
        boxShadow: `0 0 0 4px ${color}55,0 4px 14px rgba(0,0,0,.24)`,
    }),
    linked: (color) => ({
        transform: 'scale(1.22)',
        boxShadow: `0 0 0 3px ${color}44,0 4px 12px rgba(0,0,0,.24)`,
    }),
    idle: () => ({ transform: 'scale(1)', boxShadow: '0 3px 10px rgba(0,0,0,.22)' }),
};
function placeIcon(place: BundleMapPlace, color: string): L.DivIcon {
    const idle = PIN_STATE_STYLE.idle(color);
    return L.divIcon({
        className: '',
        html: `<span data-bundle-map-marker="${place.sequence}" data-bundle-map-entity="${place.entity_ref.entity_id}" data-pin-color="${color}" style="width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:${color};color:#fff;font:700 12px/1 -apple-system,BlinkMacSystemFont,sans-serif;border:3px solid #fff;box-shadow:${idle.boxShadow};transform:${idle.transform};transition:transform var(--dur-fast,120ms) var(--ease-standard,ease)">${place.sequence}</span>`,
        iconSize: [30, 30],
        iconAnchor: [15, 15],
        popupAnchor: [0, -17],
    });
}
function applyPinState(pin: HTMLElement, state: PinState): void {
    const { transform, boxShadow } = PIN_STATE_STYLE[state](pin.dataset.pinColor || FALLBACK_COLORS[0]);
    pin.style.transform = transform;
    pin.style.boxShadow = boxShadow;
    if (state === 'linked')
        pin.dataset.linked = 'on';
    else
        delete pin.dataset.linked;
}
interface Pin {
    place: BundleMapPlace;
    position: [
        number,
        number
    ];
    icon: L.DivIcon;
}
function usePins(places: BundleMapPlace[]): Pin[] {
    const cache = React.useRef(new Map<string, L.DivIcon>()).current;
    return React.useMemo(() => places.flatMap((place) => {
        const position = placePoint(place);
        if (!position)
            return [];
        const color = colorForIndex(Math.max((place.days[0] ?? 1) - 1, 0));
        const key = `${place.entity_ref.entity_id}|${place.sequence}|${color}`;
        let icon = cache.get(key);
        if (!icon) {
            icon = placeIcon(place, color);
            cache.set(key, icon);
        }
        return [{ place, position, icon }];
    }), [cache, places]);
}
const IN_VIEW_MARGIN = -0.2;
const CLOSE_ENOUGH_ZOOM = 14;
const FOCUS_ZOOM = 15;
function MapViewport({ places, lines, selectedEntityId, }: Pick<BundleMapLeafletProps, 'places' | 'selectedEntityId'> & {
    lines: RouteLines[];
}) {
    const map = useMap();
    const lastTarget = React.useRef('');
    const reducedMotion = useReducedMotion();
    React.useEffect(() => {
        const selectedPlace = places.find((place) => place.entity_ref.entity_id === selectedEntityId);
        const selectedPoint = selectedPlace ? placePoint(selectedPlace) : null;
        if (selectedPoint) {
            const key = `place:${selectedPlace!.entity_ref.entity_id}`;
            if (lastTarget.current === key)
                return;
            lastTarget.current = key;
            const target = L.latLng(selectedPoint);
            if (map.getBounds().pad(IN_VIEW_MARGIN).contains(target))
                return;
            if (map.getZoom() >= CLOSE_ENOUGH_ZOOM)
                map.panTo(target, { animate: !reducedMotion });
            else if (reducedMotion)
                map.setView(target, FOCUS_ZOOM);
            else
                map.flyTo(target, FOCUS_ZOOM, { duration: 0.35 });
            return;
        }
        const selectedRoute = lines.find((line) => line.route.entity_ref.entity_id === selectedEntityId);
        const selectedPoints = selectedRoute ? selectedRoute.segments.flat() : [];
        if (selectedPoints.length > 0) {
            const key = `route:${selectedRoute!.route.entity_ref.entity_id}`;
            if (lastTarget.current === key)
                return;
            lastTarget.current = key;
            const bounds = L.latLngBounds(selectedPoints);
            if (map.getBounds().pad(IN_VIEW_MARGIN).contains(bounds))
                return;
            map.fitBounds(bounds, { padding: [36, 36], animate: !reducedMotion });
            return;
        }
        const allPoints: [
            number,
            number
        ][] = [
            ...places.flatMap((place) => { const point = placePoint(place); return point ? [point] : []; }),
            ...lines.flatMap((line) => line.segments.flat()),
        ];
        if (allPoints.length === 0)
            return;
        const key = `all:${allPoints.map((point) => point.join(',')).join('|')}`;
        if (lastTarget.current === key)
            return;
        lastTarget.current = key;
        if (allPoints.length === 1)
            map.setView(allPoints[0], 13);
        else
            map.fitBounds(L.latLngBounds(allPoints), { padding: [32, 32], animate: !reducedMotion });
    }, [map, places, lines, selectedEntityId, reducedMotion]);
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
export const BundleMapLeaflet: React.FC<BundleMapLeafletProps> = ({ places, routes, selectedEntityId, onSelectEntity, linkedEntityId = null, onLinkEntity, }) => {
    const [basemap, setBasemap] = React.useState<BasemapState>('loading');
    const tileErrors = React.useRef(0);
    const pinRoot = React.useRef<HTMLDivElement>(null);
    const guardTeardown = React.useCallback((map: L.Map | null) => {
        if (!map)
            return;
        const instance = map as unknown as {
            _animatingZoom: boolean;
            _teardownGuarded?: true;
        };
        if (instance._teardownGuarded)
            return;
        instance._teardownGuarded = true;
        const removeMap = map.remove.bind(map);
        map.remove = () => {
            instance._animatingZoom = false;
            map.stop();
            return removeMap();
        };
    }, []);
    const link = (entityId: string | null) => (event: L.LeafletMouseEvent) => {
        if ((event.originalEvent as PointerEvent | undefined)?.pointerType === 'touch')
            return;
        onLinkEntity?.(entityId);
    };
    const lines = useRouteLines(routes);
    const pins = usePins(places);
    React.useEffect(() => {
        const root = pinRoot.current;
        if (!root)
            return;
        root.querySelectorAll<HTMLElement>('[data-bundle-map-entity]').forEach((pin) => {
            const entityId = pin.dataset.bundleMapEntity;
            applyPinState(pin, entityId === selectedEntityId ? 'selected' : entityId === linkedEntityId ? 'linked' : 'idle');
        });
    }, [pins, selectedEntityId, linkedEntityId]);
    const anchor = React.useRef<[
        number,
        number
    ] | null>(null);
    const firstPoint = pins[0]?.position ?? lines.flatMap((line) => line.segments.flat())[0] ?? null;
    if (firstPoint)
        anchor.current = firstPoint;
    if (!anchor.current)
        return null;
    return (<div ref={pinRoot} className="relative h-full w-full" data-testid="bundle-leaflet-map" data-basemap-state={basemap}>
      {BASEMAP_NOTICE[basemap] && (<p data-testid="bundle-map-basemap-state" role={basemap === 'degraded' ? 'status' : undefined} className="pointer-events-none absolute left-1/2 top-3 z-[1000] max-w-[92%] -translate-x-1/2 truncate rounded-label bg-panel/90 px-2.5 py-1 text-[11px] font-medium text-ink-secondary shadow-sm backdrop-blur">
          {BASEMAP_NOTICE[basemap]}
        </p>)}
    <MapContainer ref={guardTeardown} center={anchor.current} zoom={12} zoomControl attributionControl preferCanvas={false} className="h-full w-full">

      <TileLayer url={TILE_URL} subdomains={TILE_SUBDOMAINS} attribution={TILE_ATTRIBUTION} maxZoom={18} eventHandlers={{
            loading: () => { tileErrors.current = 0; },
            load: () => setBasemap(tileErrors.current > 0 ? 'degraded' : 'ready'),
            tileerror: () => { tileErrors.current += 1; setBasemap('degraded'); },
        }}/>
      <MapViewport places={places} lines={lines} selectedEntityId={selectedEntityId}/>

      {lines.map(({ route, segments }, routeIndex) => {
            const selected = route.entity_ref.entity_id === selectedEntityId;
            const linked = route.entity_ref.entity_id === linkedEntityId;
            return segments.map((line, segmentIndex) => (<Polyline key={`${route.entity_ref.entity_id}:${segmentIndex}`} positions={line} pathOptions={{
                    color: colorForIndex(routeIndex),
                    weight: selected ? 7 : linked ? 5.5 : 3.5,
                    opacity: selected ? 0.95 : linked ? 0.95 : selectedEntityId ? 0.3 : 0.68,
                }} eventHandlers={{
                    click: () => onSelectEntity(route.entity_ref.entity_id),
                    mouseover: link(route.entity_ref.entity_id),
                    mouseout: link(null),
                }}/>));
        })}

      {pins.map(({ place, position, icon }) => {
            const entityId = place.entity_ref.entity_id;
            return (<Marker key={entityId} position={position} icon={icon} zIndexOffset={entityId === linkedEntityId ? 1000 : entityId === selectedEntityId ? 800 : 0} eventHandlers={{
                    click: () => onSelectEntity(entityId),
                    mouseover: link(entityId),
                    mouseout: link(null),
                }} keyboard title={place.name}>
            <Popup>
              <div className="max-w-52 break-words text-xs">
                <strong>{place.sequence}. {place.name}</strong>
                {place.days.length > 0 && <p className="mt-1">第 {place.days.join('、')} 天</p>}
              </div>
            </Popup>
          </Marker>);
        })}
    </MapContainer>
    </div>);
};
