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
    if (family === 'scheduled' || family === 'transit') {
        readouts.push({
            key: 'transfer',
            label: '换乘',
            value: leg.transfer_count > 0 ? `${leg.transfer_count} 次换乘` : '直达',
        });
    }
    if (family !== 'self') {
        const cost = moneyLabel(leg.total_cost_cny);
        if (cost)
            readouts.push({ key: 'cost', label: '费用', value: cost });
    }
    return readouts;
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
export function legLineChain(leg: PublicTransportLeg): string[] {
    if (leg.route_status !== 'ready')
        return [];
    return leg.segments.map((segment: TransportSegment) => (
        segment.line_name
        || segment.service_number
        || TRANSPORT_MODE_LABELS[transportSegmentDisplayMode(leg.selected_mode, segment.mode)]
    ));
}
