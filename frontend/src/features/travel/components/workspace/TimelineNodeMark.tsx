import { MapPin, type LucideIcon } from "lucide-react";
import { type DayTimelineNodeVM } from "../../model/itineraryPresentation";
import { cn } from "../../../../lib/utils";
import { TRIP_DOMAIN_PRESENTATION, type TripDomain } from "../../model/tripDomains";
import { TRANSPORT_MODE_ICONS, transportModeStyle } from "../../model/transportPresentation";
export function nodeDomain(node: DayTimelineNodeVM): TripDomain | null {
    return node.entityKind === 'custom' ? null : node.entityKind;
}
export function nodeIcon(node: DayTimelineNodeVM): LucideIcon {
    if (node.transportMode)
        return TRANSPORT_MODE_ICONS[node.transportMode];
    const domain = nodeDomain(node);
    return domain ? TRIP_DOMAIN_PRESENTATION[domain].icon : MapPin;
}
const CUSTOM_MARK = { dot: 'bg-ink-muted ring-ink-muted/15', glyph: 'text-panel' } as const;
export function nodeMark(node: DayTimelineNodeVM): {
    dot: string;
    glyph: string;
} {
    const domain = nodeDomain(node);
    return domain ? TRIP_DOMAIN_PRESENTATION[domain] : CUSTOM_MARK;
}
export function TimelineNodeMark({ node, className, ringed = true, }: {
    node: DayTimelineNodeVM;
    className?: string;
    ringed?: boolean;
}) {
    const mark = nodeMark(node);
    const Icon = nodeIcon(node);
    const mode = node.transportMode;
    const style = mode ? {
        ...transportModeStyle(mode),
        backgroundColor: 'var(--transport-mode-color)',
        boxShadow: ringed ? '0 0 0 4px color-mix(in srgb, var(--transport-mode-color) 15%, transparent)' : undefined,
    } : undefined;
    return (<span data-timeline-domain={nodeDomain(node) ?? 'custom'} data-transport-mode={mode ?? undefined} style={style} className={cn('flex size-4 shrink-0 items-center justify-center rounded-full', ringed && !mode && 'ring-4', !mode && mark.dot, className)} aria-hidden>
      <Icon size={10} className={mark.glyph} strokeWidth={2.5}/>
    </span>);
}
