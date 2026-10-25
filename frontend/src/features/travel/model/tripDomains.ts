import { BedDouble, Landmark, Route, Utensils, type LucideIcon } from "lucide-react";
import { type SelectionSlotType } from "../types/itinerary";
export type TripDomain = SelectionSlotType;
export interface TripDomainPresentation {
    icon: LucideIcon;
    noun: string;
    heading: string;
    plan: string;
    dot: string;
    glyph: string;
}
export const TRIP_DOMAIN_PRESENTATION: Record<TripDomain, TripDomainPresentation> = {
    visit: {
        icon: Landmark,
        noun: '景点',
        heading: '景点选择',
        plan: '景点方案',
        dot: 'bg-vermilion ring-vermilion/15',
        glyph: 'text-panel',
    },
    transport: {
        icon: Route,
        noun: '交通',
        heading: '交通选择',
        plan: '交通方案',
        dot: 'bg-chart ring-chart/15',
        glyph: 'text-panel',
    },
    dining: {
        icon: Utensils,
        noun: '用餐',
        heading: '用餐选择',
        plan: '用餐方案',
        dot: 'bg-ink ring-ink/15',
        glyph: 'text-panel',
    },
    lodging: {
        icon: BedDouble,
        noun: '住宿',
        heading: '住宿选择',
        plan: '住宿方案',
        dot: 'bg-panel ring-ink/15 border-[1.5px] border-ink',
        glyph: 'text-ink',
    },
};
const FULL_WIDTH_COLON = '：';
export function splitLabelledFact(fact: string): {
    label: string | null;
    value: string;
} {
    const at = fact.indexOf(FULL_WIDTH_COLON);
    if (at <= 0 || at === fact.length - FULL_WIDTH_COLON.length) {
        return { label: null, value: fact };
    }
    return {
        label: fact.slice(0, at).trim(),
        value: fact.slice(at + FULL_WIDTH_COLON.length).trim(),
    };
}
