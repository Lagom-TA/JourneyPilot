import { type ConsumerNotice } from "./consumerNotices";
import { weatherIconForLabel, type WeatherIconKind } from "./weatherViewModel";
import { type EvidenceBasis, type PublicCustomBlock, type PublicDiningStop, type PublicLodgingStay, type PublicStructuredItineraryV2, type PublicTransportLeg, type PublicVisitStop } from "../types/itinerary";
import { type PublicDeliveryBundle } from "../types/delivery";
import { type PublicReportBlock, type TripReportProjection } from "../types/report";
import { type TransportMode } from "../types/entities";
export type ItineraryPresentationBundle = Pick<PublicDeliveryBundle, 'manifest' | 'report_projection'>;
export interface DayWeatherVM {
    dataKind: 'forecast' | 'seasonal_baseline';
    dataState: 'current' | 'historical';
    observedAt: string | null;
    icon: WeatherIconKind;
    conditionLabel: string | null;
    temperatureLabel: string | null;
    precipitationProbabilityPct: number | null;
    windSpeedKph: number | null;
}
export interface DayTimelineNodeVM {
    key: string;
    entityId: string;
    entityKind: PublicReportBlock['entity_kind'];
    projectionRole: PublicReportBlock['projection_role'];
    transportMode: TransportMode | null;
    role: 'place' | 'movement' | 'arrival' | 'departure';
    timeLabel: string | null;
    title: string;
    summary: string | null;
    durationLabel: string | null;
    priceLabel: string | null;
}
export type DaySummaryNodeVM = DayTimelineNodeVM;
export interface DaySummaryVM {
    dayId: string;
    day: number;
    dateLabel: string | null;
    weekdayLabel: string | null;
    destinationLabel: string | null;
    theme: string;
    weather: DayWeatherVM | null;
    nodes: DaySummaryNodeVM[];
    hiddenNodeCount: number;
    notice: ConsumerNotice | null;
}
export type TimelineEntity = PublicVisitStop | PublicDiningStop | PublicLodgingStay | PublicTransportLeg | PublicCustomBlock;
type CurrentReportDocument = NonNullable<TripReportProjection['document']>;
type ReportDay = CurrentReportDocument['days'][number];
const MAX_SUMMARY_NODES = 5;
function cleanText(value: string | null | undefined): string | null {
    const text = value?.trim();
    return text ? text : null;
}
function parseDateParts(value: string | null): {
    year: number;
    month: number;
    day: number;
} | null {
    if (!value)
        return null;
    const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match)
        return null;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const parsed = new Date(Date.UTC(year, month - 1, day));
    if (parsed.getUTCFullYear() !== year
        || parsed.getUTCMonth() !== month - 1
        || parsed.getUTCDate() !== day)
        return null;
    return { year, month, day };
}
function dateAtUtcMidnight(value: string | null): Date | null {
    const parts = parseDateParts(value);
    return parts ? new Date(Date.UTC(parts.year, parts.month - 1, parts.day)) : null;
}
export function formatLocalDate(value: string | null): string | null {
    const date = dateAtUtcMidnight(value);
    if (!date)
        return null;
    return new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'UTC',
        month: 'long',
        day: 'numeric',
    }).format(date);
}
export function formatLocalWeekday(value: string | null): string | null {
    const date = dateAtUtcMidnight(value);
    if (!date)
        return null;
    return new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'UTC',
        weekday: 'short',
    }).format(date);
}
export function formatTemperatureRange(highC: number | null, lowC: number | null): string | null {
    const format = (value: number | null) => (value != null && Number.isFinite(value) ? `${Math.round(value)}°` : null);
    const high = format(highC);
    const low = format(lowC);
    if (high && low)
        return `${high} / ${low}`;
    return high ?? low;
}
export function evidenceBasisForEntity(entity: TimelineEntity): EvidenceBasis | null {
    if (entity.type === 'custom_block')
        return null;
    if (entity.type === 'transport_leg' && entity.is_micro_transport)
        return null;
    return entity.evidence_basis;
}
export function evidenceBasisForReportBlock(block: PublicReportBlock, itinerary: PublicStructuredItineraryV2): EvidenceBasis | null {
    if (block.entity_kind === 'custom')
        return null;
    if (block.entity_kind === 'transport') {
        const leg = itinerary.transport_legs.find((candidate) => (candidate.transport_leg_id === block.entity_ref.entity_id));
        if (leg?.is_micro_transport)
            return null;
    }
    return block.evidence_basis;
}
export function selectPrimaryLongDistanceMode(itinerary: PublicStructuredItineraryV2): PublicTransportLeg['selected_mode'] | null {
    const tally = new Map<PublicTransportLeg['selected_mode'], {
        legs: number;
        minutes: number;
        order: number;
    }>();
    for (const leg of itinerary.transport_legs) {
        if (leg.transport_class !== 'long_distance')
            continue;
        const current = tally.get(leg.selected_mode) ?? { legs: 0, minutes: 0, order: tally.size };
        tally.set(leg.selected_mode, {
            legs: current.legs + 1,
            minutes: current.minutes + (leg.duration_minutes ?? 0),
            order: current.order,
        });
    }
    return [...tally.entries()].sort(([, left], [, right]) => (right.legs - left.legs || right.minutes - left.minutes || left.order - right.order))[0]?.[0] ?? null;
}
function nodeFromBlock(block: PublicReportBlock): DayTimelineNodeVM {
    const details = block.details;
    return {
        key: details.entry_id,
        entityId: block.entity_ref.entity_id,
        entityKind: block.entity_kind,
        projectionRole: block.projection_role,
        transportMode: details.transport_mode,
        role: details.node_role,
        timeLabel: details.time_label,
        title: details.display_title,
        summary: cleanText(details.node_summary),
        durationLabel: details.duration_label,
        priceLabel: details.price_label,
    };
}
export function selectCurrentReportDocument(bundle: ItineraryPresentationBundle): CurrentReportDocument | null {
    const report = bundle.report_projection;
    const manifest = bundle.manifest;
    if (report.status !== 'ready'
        || !report.document
        || report.source_workspace_revision !== manifest.workspace_revision
        || report.source_fact_data_revision !== manifest.fact_data_revision
        || report.source_weather_data_revision !== manifest.weather_data_revision)
        return null;
    return report.document;
}
function weatherForDay(day: ReportDay, document: CurrentReportDocument): DayWeatherVM | null {
    if (!day.date)
        return null;
    const weather = document.weather.find((candidate) => (candidate.destination_id === day.destination_id && candidate.date === day.date));
    if (!weather || weather.data_kind === 'unavailable')
        return null;
    return {
        dataKind: weather.data_kind,
        dataState: weather.weather_data_state,
        observedAt: weather.observed_at,
        icon: weatherIconForLabel(weather.condition_label),
        conditionLabel: cleanText(weather.condition_label),
        temperatureLabel: formatTemperatureRange(weather.high_c, weather.low_c),
        precipitationProbabilityPct: weather.precipitation_probability_pct,
        windSpeedKph: weather.wind_speed_kph,
    };
}
function noticeForDay(dayId: string, notices: readonly ConsumerNotice[]): ConsumerNotice | null {
    const dayNotices = [...new Map(notices
            .filter((notice) => notice.scope === 'day' && notice.dayId === dayId)
            .map((notice) => [notice.key, notice])).values()];
    return dayNotices.sort((left, right) => {
        const severity = (notice: ConsumerNotice) => notice.severity === 'blocking' ? 0 : 1;
        return severity(left) - severity(right);
    })[0] ?? null;
}
function summaryPriority(node: DayTimelineNodeVM): number {
    if (node.role === 'arrival' || node.role === 'departure')
        return 0;
    if (node.timeLabel && node.entityKind !== 'custom')
        return 1;
    if (node.entityKind === 'visit')
        return 2;
    if (node.entityKind === 'transport')
        return 3;
    return 4;
}
function summaryNodes(nodes: readonly DayTimelineNodeVM[]): DaySummaryNodeVM[] {
    return nodes
        .map((node, index) => ({ node, index, priority: summaryPriority(node) }))
        .sort((left, right) => left.priority - right.priority || left.index - right.index)
        .slice(0, MAX_SUMMARY_NODES)
        .sort((left, right) => left.index - right.index)
        .map(({ node }) => node);
}
export function selectDayTimeline(bundle: ItineraryPresentationBundle, dayId: string): DayTimelineNodeVM[] {
    const document = selectCurrentReportDocument(bundle);
    const day = document?.days.find((candidate) => candidate.day_id === dayId);
    return day ? day.blocks.map(nodeFromBlock) : [];
}
export function selectDaySummaries(bundle: ItineraryPresentationBundle, notices: readonly ConsumerNotice[] = []): DaySummaryVM[] {
    const document = selectCurrentReportDocument(bundle);
    if (!document)
        return [];
    return document.days.map((day) => {
        const timeline = day.blocks.map(nodeFromBlock);
        const nodes = summaryNodes(timeline);
        return {
            dayId: day.day_id,
            day: day.day,
            dateLabel: formatLocalDate(day.date),
            weekdayLabel: formatLocalWeekday(day.date),
            destinationLabel: cleanText(day.destination_name),
            theme: day.theme,
            weather: weatherForDay(day, document),
            nodes,
            hiddenNodeCount: timeline.length - nodes.length,
            notice: noticeForDay(day.day_id, notices),
        };
    });
}
