import { type PublicTransportLeg } from "../types/itinerary";
import { type TransportMode } from "../types/entities";
export const TRANSPORT_MODE_LABELS: Record<TransportMode, string> = {
    flight: '飞机',
    high_speed_rail: '高铁',
    train: '火车',
    coach: '长途巴士',
    ferry: '轮渡',
    metro: '地铁',
    bus: '公交',
    tram: '有轨电车',
    taxi: '出租车',
    ride_hailing: '网约车',
    drive: '自驾',
    bike: '骑行',
    walk: '步行',
    other: '其它交通',
};
export const BOOKING_LABELS: Record<PublicTransportLeg['booking_status'], string> = {
    not_required: '无需预订',
    recommended: '建议提前预订',
    required: '需要提前预订',
    booked: '需自行确认',
    unknown: '暂无预订信息',
};
export function bookingLabel(value: string | null): string | null {
    if (!value)
        return null;
    return BOOKING_LABELS[value as PublicTransportLeg['booking_status']] ?? null;
}
export const WEATHER_OBSERVED_SUFFIX = '观测';
export const WEATHER_HISTORICAL_LABEL = '历史天气数据';
export function weatherFreshnessText(dataState: 'current' | 'historical', observedAt: string | null): string | null {
    if (dataState === 'historical')
        return WEATHER_HISTORICAL_LABEL;
    const match = observedAt?.match(/^\d{4}-(\d{2})-(\d{2})T(\d{2}:\d{2})/);
    if (!match)
        return null;
    return `${match[1]}-${match[2]} ${match[3]} ${WEATHER_OBSERVED_SUFFIX}`;
}
