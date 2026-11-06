import { Bike, BusFront, CarFront, Footprints, Plane, Ship, TrainFront, TramFront, type LucideIcon } from "lucide-react";
import { type CSSProperties } from "react";
import { type PublicTransportLeg } from "../types/itinerary";
import { type TransportMode, type TransportSegment } from "../types/entities";
import { TRANSPORT_MODE_LABELS } from "./deliveryLabels";
export type TransportFamily = 'scheduled' | 'transit' | 'road' | 'self' | 'other';
export const TRANSPORT_MODE_COLORS: Record<TransportMode, string> = {
    flight: '#6C63CE',
    high_speed_rail: '#C64B45',
    train: '#8B5E3C',
    coach: '#A76E12',
    ferry: '#168C96',
    metro: '#2166C1',
    bus: '#2F7D5A',
    tram: '#9C4FA3',
    taxi: '#A77B00',
    ride_hailing: '#C26A1B',
    drive: '#D6513C',
    bike: '#608B2F',
    walk: '#5F746E',
    other: '#64748B',
};
export function transportModeColor(mode: TransportMode): string {
    return TRANSPORT_MODE_COLORS[mode];
}
export function transportModeStyle(mode: TransportMode): CSSProperties {
    return { '--transport-mode-color': transportModeColor(mode) } as CSSProperties;
}
export function transportSegmentDisplayMode(
    selectedMode: TransportMode,
    segmentMode: TransportMode,
): TransportMode {
    return segmentMode === 'drive' && (selectedMode === 'taxi' || selectedMode === 'ride_hailing')
        ? selectedMode
        : segmentMode;
}
function transitSegmentModes(leg: PublicTransportLeg): TransportMode[] {
    return leg.segments
        .map((segment) => transportSegmentDisplayMode(leg.selected_mode, segment.mode))
        .filter((mode) => mode !== 'walk' && mode !== 'bike');
}
export function transitRideModes(leg: PublicTransportLeg): TransportMode[] {
    return Array.from(new Set(transitSegmentModes(leg)));
}
/** 混合公交不能用首个乘坐段的模式冒充整段方式。 */
export function transitDisplayMode(leg: PublicTransportLeg): TransportMode {
    return transitRideModes(leg)[0] ?? leg.selected_mode;
}
export function transitModeLabel(leg: PublicTransportLeg): string | null {
    const modes = transitRideModes(leg);
    return modes.length > 0 ? modes.map((mode) => TRANSPORT_MODE_LABELS[mode]).join(' / ') : null;
}
export function transitStationModes(leg: PublicTransportLeg): {
    from: TransportMode | null;
    to: TransportMode | null;
} {
    const modes = transitSegmentModes(leg);
    return {
        from: modes[0] ?? null,
        to: modes[modes.length - 1] ?? null,
    };
}
export const TRANSPORT_FAMILY_BY_MODE: Record<TransportMode, TransportFamily> = {
    flight: 'scheduled',
    high_speed_rail: 'scheduled',
    train: 'scheduled',
    coach: 'scheduled',
    ferry: 'scheduled',
    metro: 'transit',
    bus: 'transit',
    tram: 'transit',
    taxi: 'road',
    ride_hailing: 'road',
    drive: 'road',
    bike: 'self',
    walk: 'self',
    other: 'other',
};
export const TRANSPORT_MODE_ICONS: Record<TransportMode, LucideIcon> = {
    flight: Plane,
    high_speed_rail: TrainFront,
    train: TrainFront,
    coach: BusFront,
    ferry: Ship,
    metro: TrainFront,
    bus: BusFront,
    tram: TramFront,
    taxi: CarFront,
    ride_hailing: CarFront,
    drive: CarFront,
    bike: Bike,
    walk: Footprints,
    other: BusFront,
};
export const TRANSPORT_FAMILY_NOUNS: Record<TransportFamily, string> = {
    scheduled: '班次',
    transit: '市内公共交通',
    road: '车程',
    self: '自行前往',
    other: '交通安排',
};
export function transportFamily(mode: TransportMode): TransportFamily {
    return TRANSPORT_FAMILY_BY_MODE[mode];
}
export function durationLabel(minutes: number | null): string | null {
    if (minutes == null)
        return null;
    if (minutes < 60)
        return `${minutes} 分钟`;
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    return remainder ? `${hours} 小时 ${remainder} 分钟` : `${hours} 小时`;
}
export function distanceLabel(meters: number | null): string | null {
    if (meters == null)
        return null;
    if (meters < 1000)
        return `${meters} 米`;
    return `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(meters / 1000)} 公里`;
}
export function moneyLabel(value: number | null): string | null {
    if (value == null)
        return null;
    return new Intl.NumberFormat('zh-CN', {
        style: 'currency',
        currency: 'CNY',
        maximumFractionDigits: 0,
    }).format(value);
}
export function clockLabel(value: string | null): string | null {
    if (!value)
        return null;
    return value.match(/T(\d{2}:\d{2})/)?.[1] ?? value;
}
export interface Readout {
    key: string;
    label: string;
    value: string;
}
export function legReadouts(leg: PublicTransportLeg): Readout[] {
    if (leg.route_status !== 'ready')
        return [];
    const family = transportFamily(leg.selected_mode);
    const readouts: Readout[] = [];
    const duration = durationLabel(leg.duration_minutes);
    if (duration)
        readouts.push({ key: 'duration', label: '时长', value: duration });
    if (family === 'road' || family === 'self' || family === 'other') {
        const distance = distanceLabel(leg.distance_meters);
        if (distance)
            readouts.push({ key: 'distance', label: '里程', value: distance });
    }
    if (family !== 'self') {
        const cost = moneyLabel(leg.total_cost_cny);
        if (cost)
            readouts.push({ key: 'cost', label: '费用', value: cost });
    }
    return readouts;
}
export interface LegSummary {
    duration: string | null;
    cost: string | null;
}
/** 行程卡片底部只保留值与单位：左侧时长，右侧费用；换乘由公共交通线路链表达，不再重复计数。 */
export function legSummary(leg: PublicTransportLeg): LegSummary {
    if (leg.route_status !== 'ready')
        return { duration: null, cost: null };
    return {
        duration: durationLabel(leg.duration_minutes),
        cost: moneyLabel(leg.total_cost_cny),
    };
}
/**
 * 只有纯地铁分段里的真实线路变化才算地铁换乘，步行进出站与混合公交都不借用通用计数。
 * 同一线路被拆成多段、或仅运营商变化时不算换乘；线路身份缺失时也不臆测换乘。
 */
export function confirmedMetroTransferCount(leg: PublicTransportLeg): number {
    if (leg.route_status !== 'ready' || leg.selected_mode !== 'metro')
        return 0;
    const modes = leg.segments.map((segment) => transportSegmentDisplayMode(leg.selected_mode, segment.mode));
    if (!modes.includes('metro'))
        return 0;
    if (modes.some((mode) => mode !== 'metro' && mode !== 'walk'))
        return 0;
    const metroSegments = leg.segments.filter(
        (segment) => transportSegmentDisplayMode(leg.selected_mode, segment.mode) === 'metro',
    );
    let transfers = 0;
    let previousLine: string | null = null;
    for (const segment of metroSegments) {
        const line = segment.line_name?.trim() || null;
        if (!line) {
            previousLine = null;
            continue;
        }
        if (previousLine !== null && previousLine !== line)
            transfers += 1;
        previousLine = line;
    }
    return transfers;
}
/** 主行只使用路线数据中的上车站与下车站字段；缺少站点时，不用路线端点或地点名称补齐。 */
export function transitStations(leg: PublicTransportLeg): {
    from: string | null;
    to: string | null;
} {
    if (leg.route_status !== 'ready')
        return { from: null, to: null };
    return {
        from: leg.boarding_stop?.name?.trim() || null,
        to: leg.alighting_stop?.name?.trim() || null,
    };
}

export interface TransitRide {
    key: string;
    segment: TransportSegment;
    mode: TransportMode;
    /** 首屏使用的线路标签，省略线路名末尾的端点括注。 */
    label: string;
    /** 展开行使用的完整线路身份。 */
    rowLabel: string;
    /** 该段乘车去往的已证实站点；没有证据时为 null。 */
    direction: string | null;
}
export interface TransitLineStep {
    key: string;
    label: string;
    mode: TransportMode;
    direction: string | null;
    rides: TransitRide[];
}
export interface TransitLineChain {
    rides: TransitRide[];
    steps: TransitLineStep[];
    /** 只有可证实的线路或方式变化才产生线路链与展开入口。 */
    expandable: boolean;
    transferCount: number;
}

function trimmedText(value: string | null | undefined): string | null {
    const text = value?.trim();
    return text ? text : null;
}

/** 线路名末尾的端点括注在首屏省略，完整名称仍保留在展开行。 */
function compactLineText(value: string): string {
    return value.replace(/\s*[（(][^（）()]*[）)]\s*$/u, '').trim() || value;
}

function rideArrivalStop(leg: PublicTransportLeg, rides: readonly TransitRide[], index: number): string | null {
    const next = rides[index + 1];
    if (next)
        return trimmedText(next.segment.from_endpoint.name);
    return trimmedText(leg.alighting_stop?.name);
}

/** 公共交通只把乘车段当作路线步骤；步行与骑行是接驳，不算乘车路径。 */
export function transitRides(leg: PublicTransportLeg): TransitRide[] {
    if (leg.route_status !== 'ready')
        return [];
    const rides = leg.segments
        .map((segment, index) => ({ segment, index, mode: transportSegmentDisplayMode(leg.selected_mode, segment.mode) }))
        .filter(({ mode }) => mode !== 'walk' && mode !== 'bike')
        .map(({ segment, index, mode }) => ({
            key: segment.segment_id || `ride-${index}`,
            segment,
            mode,
            label: trimmedText(segment.service_number) ?? trimmedText(segment.line_name) ?? TRANSPORT_MODE_LABELS[mode],
            rowLabel: trimmedText(segment.line_name) ?? trimmedText(segment.service_number) ?? TRANSPORT_MODE_LABELS[mode],
            direction: null,
        }));
    return rides.map((ride, index) => ({
        ...ride,
        label: ride.label === ride.rowLabel ? compactLineText(ride.label) : ride.label,
        direction: rideArrivalStop(leg, rides, index),
    }));
}

function rideLineName(ride: TransitRide): string | null {
    return trimmedText(ride.segment.line_name);
}

/** 同线拆段或线路身份缺失时不推断换乘，连续乘车段合并为一个线路项。 */
function sharesLineStep(previous: TransitLineStep, ride: TransitRide): boolean {
    const previousRide = previous.rides[previous.rides.length - 1];
    if (previousRide.mode !== ride.mode)
        return false;
    const previousLine = rideLineName(previousRide);
    const line = rideLineName(ride);
    if (previousLine === null || line === null)
        return true;
    return previousLine === line;
}

function stepLabel(rides: readonly TransitRide[]): string {
    const services = rides.map((ride) => trimmedText(ride.segment.service_number));
    if (services[0] && services.every((value) => value === services[0]))
        return compactLineText(services[0]);
    const lines = rides.map((ride) => trimmedText(ride.segment.line_name));
    if (lines[0] && lines.every((value) => value === lines[0]))
        return compactLineText(lines[0]);
    return TRANSPORT_MODE_LABELS[rides[0].mode];
}

/** 首屏线路链：线路A → 线路B，箭头表示换乘或方式衔接。 */
export function transitLineChain(leg: PublicTransportLeg): TransitLineChain {
    const rides = transitRides(leg);
    const steps: TransitLineStep[] = [];
    for (const ride of rides) {
        const previous = steps[steps.length - 1];
        if (previous && sharesLineStep(previous, ride)) {
            previous.rides.push(ride);
            previous.direction = ride.direction;
            continue;
        }
        steps.push({
            key: ride.key,
            label: ride.label,
            mode: ride.mode,
            direction: ride.direction,
            rides: [ride],
        });
    }
    const labeled = steps.map((step) => ({ ...step, label: stepLabel(step.rides) }));
    return {
        rides,
        steps: labeled,
        expandable: labeled.length > 1,
        transferCount: Math.max(0, labeled.length - 1),
    };
}

/** 整卡地图入口的可访问名称：保留线路、方向与站点，不只写“在地图中查看”。 */
export function transportMapCardLabel(leg: PublicTransportLeg): string {
    const parts: string[] = [];
    const family = transportFamily(leg.selected_mode);
    if (family === 'transit') {
        const chain = transitLineChain(leg);
        if (chain.steps.length > 1) {
            parts.push(chain.steps.map((step) => step.label).join(' 换乘 '));
        }
        else if (chain.steps.length === 1) {
            parts.push(chain.steps[0].label);
            if (chain.steps[0].direction)
                parts.push(`往${chain.steps[0].direction}`);
        }
        else {
            parts.push(transitModeLabel(leg) ?? TRANSPORT_MODE_LABELS[leg.selected_mode]);
        }
        const stations = transitStations(leg);
        if (stations.from && stations.to)
            parts.push(`${stations.from}到${stations.to}`);
    }
    else {
        const service = legService(leg);
        parts.push(service?.serviceNumber ?? service?.lineName ?? TRANSPORT_MODE_LABELS[leg.selected_mode]);
        parts.push(`${leg.from_endpoint.name}到${leg.to_endpoint.name}`);
    }
    const summary = legSummary(leg);
    if (summary.duration)
        parts.push(summary.duration);
    if (summary.cost)
        parts.push(summary.cost);
    return `${parts.filter(Boolean).join('，')}。在地图中查看`;
}
/** 铁路站码对用户没有意义；机场三字码仍是识别航站的有用信息。 */
export function showsEndpointCode(mode: TransportMode): boolean {
    return mode === 'flight';
}
/** 公共交通、道路与自行前往、其他交通都可用整卡进入地图；高铁与飞机保持无路线入口。 */
export function transportMapEntryVisible(leg: PublicTransportLeg): boolean {
    return leg.selected_mode !== 'high_speed_rail' && leg.selected_mode !== 'flight';
}
export interface LegService {
    serviceNumber: string | null;
    lineName: string | null;
    operator: string | null;
}
export function legService(leg: PublicTransportLeg): LegService | null {
    if (leg.route_status !== 'ready')
        return null;
    const segment = leg.segments.find((entry) => entry.service_number || entry.line_name);
    if (!segment)
        return null;
    return {
        serviceNumber: segment.service_number,
        lineName: segment.line_name,
        operator: segment.operator_name,
    };
}
