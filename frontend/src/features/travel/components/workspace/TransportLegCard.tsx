import { ChevronDown, type LucideIcon } from "lucide-react";
import { cn } from "../../../../lib/utils";
import { READOUT_LABEL } from "../../../../lib/typography";
import { TransportProviderNote } from "./TransportProviderNote";
import { IntentExplanationList } from "./IntentExplanationList";
import { type PublicTransportLeg } from "../../types/itinerary";
import { type TransportEndpoint, type TransportSegment } from "../../types/entities";
import { BOOKING_LABELS, TRANSPORT_MODE_LABELS } from "../../model/deliveryLabels";
import { TRANSPORT_FAMILY_NOUNS, TRANSPORT_MODE_ICONS, clockLabel, distanceLabel, durationLabel, legLineChain, legReadouts, legService, transportFamily, type Readout, type TransportFamily } from "../../model/transportPresentation";
import React from 'react';
function MetaLine({ values }: {
    values: Array<string | null>;
}) {
    const visible = values.filter((value): value is string => Boolean(value));
    if (visible.length === 0)
        return null;
    return <p className="break-words text-[11px] leading-5 text-ink-muted">{visible.join(' · ')}</p>;
}
function routeStateText(leg: PublicTransportLeg): string | null {
    if (leg.route_status === 'pending')
        return '路线正在更新。';
    if (leg.route_status === 'unavailable')
        return '路线暂时不可用。';
    return null;
}
function SegmentRow({ segment, index }: {
    segment: TransportSegment;
    index: number;
}) {
    const Icon = TRANSPORT_MODE_ICONS[segment.mode];
    return (<li className="flex min-w-0 gap-2.5 py-2 first:pt-1 last:pb-1">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-card bg-surface text-ink-secondary" aria-hidden>
        <Icon size={12}/>
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3">
          <p className="min-w-0 break-words text-xs font-semibold text-ink">
            {index + 1}. {segment.from_endpoint.name} → {segment.to_endpoint.name}
          </p>
          <TimeWindow departure={segment.departure_at} arrival={segment.arrival_at} className="shrink-0 text-[11px]"/>
        </div>
        <MetaLine values={[
            TRANSPORT_MODE_LABELS[segment.mode],
            segment.line_name,
            segment.service_number,
            segment.operator_name,
            durationLabel(segment.duration_minutes),
            distanceLabel(segment.distance_meters),
        ]}/>
      </div>
    </li>);
}
function SegmentDisclosure({ leg }: {
    leg: PublicTransportLeg;
}) {
    const [open, setOpen] = React.useState(false);
    if (leg.route_status !== 'ready' || leg.segments.length <= 1)
        return null;
    const disclosureId = `transport-segments-${leg.transport_leg_id}`;
    return (<>
      <button type="button" data-testid="transport-segments-toggle" aria-expanded={open} aria-controls={disclosureId} onClick={() => setOpen((current) => !current)} className="-ml-2 mt-1 inline-flex min-h-9 items-center gap-1 rounded-card px-2 text-[11px] font-semibold text-ink-secondary transition-colors hover:bg-highlight hover:text-ink">
        {open ? '收起换乘步骤' : `展开 ${leg.segments.length} 段换乘`}
        <ChevronDown size={13} aria-hidden className={cn('transition-transform', open && 'rotate-180')}/>
      </button>
      {open && (<ol id={disclosureId} className="divide-y divide-stroke/60" data-testid="transport-segments">
          {leg.segments.map((segment, index) => <SegmentRow key={segment.segment_id} segment={segment} index={index}/>)}
        </ol>)}
    </>);
}
function RouteState({ leg }: {
    leg: PublicTransportLeg;
}) {
    const text = routeStateText(leg);
    if (!text)
        return null;
    return (<p role="status" className="mt-2 rounded-card bg-surface px-2.5 py-1.5 text-xs leading-5 text-ink-secondary">
      {text}
    </p>);
}
function TimeWindow({ departure, arrival, className, }: {
    departure: string | null;
    arrival: string | null;
    className?: string;
}) {
    const from = clockLabel(departure);
    const to = clockLabel(arrival);
    if (!from && !to)
        return null;
    return (<time className={cn('font-mono tabular-nums text-ink-secondary', className)}>
      {from && to ? `${from}–${to}` : (from ?? to)}
    </time>);
}
function RouteLine({ leg, className }: {
    leg: PublicTransportLeg;
    className?: string;
}) {
    return (<p className={cn('min-w-0 break-words text-[13px] font-semibold text-ink', className)}>
      {leg.from_endpoint.name}
      <span className="mx-1.5 font-normal text-chart" aria-hidden>→</span>
      {leg.to_endpoint.name}
    </p>);
}
function ReadoutRow({ readouts, layout }: {
    readouts: Readout[];
    layout: 'inline' | 'stacked';
}) {
    if (readouts.length === 0)
        return null;
    const stacked = layout === 'stacked';
    return (<dl className={cn('mt-2 flex min-w-0 flex-wrap border-t border-stroke/60 pt-2', stacked ? 'gap-x-6 gap-y-1.5' : 'items-baseline gap-x-4 gap-y-1')}>
      {readouts.map((readout) => (<div key={readout.key} data-readout={readout.key} className={cn('min-w-0', stacked ? '' : 'flex items-baseline gap-1.5')}>
          <dt className={cn(READOUT_LABEL, 'shrink-0 text-ink-muted')}>
            {readout.label}
          </dt>
          <dd className={cn('min-w-0 break-words text-ink', stacked ? 'mt-0.5 text-sm font-semibold' : 'text-xs font-medium')}>
            {readout.value}
          </dd>
        </div>))}
    </dl>);
}
function ServiceStub({ leg }: {
    leg: PublicTransportLeg;
}) {
    const service = legService(leg);
    if (!service)
        return null;
    return (<p data-testid="transport-service" className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 font-mono text-[11px] text-ink-secondary">
      {service.serviceNumber && (<span data-service="number" className="font-semibold tracking-[0.06em] text-ink">{service.serviceNumber}</span>)}
      {service.lineName && <span data-service="line">{service.lineName}</span>}
      {service.operator && <span data-service="operator">{service.operator}</span>}
    </p>);
}
function TicketEndpoint({ endpoint, clock, align, }: {
    endpoint: TransportEndpoint;
    clock: string | null;
    align: 'left' | 'right';
}) {
    const code = endpoint.station_code;
    return (<div className={cn('min-w-0 flex-1', align === 'right' && 'text-right')}>
      <p className="break-words text-base font-semibold leading-tight text-ink">{endpoint.name}</p>
      {clock && (<p className="mt-1 font-mono text-sm tabular-nums text-ink-secondary">{clock}</p>)}

      {code && (<p className="mt-0.5 font-mono text-[11px] font-medium leading-4 tracking-[0.06em] text-ink-secondary">
          {code}
        </p>)}
    </div>);
}
function TransitSpan({ Icon }: {
    Icon: LucideIcon;
}) {
    return (<span className="flex shrink-0 items-center gap-1 self-start pt-1.5 text-chart" aria-hidden>
      <span className="h-px w-3 border-t border-dashed border-chart/50 sm:w-5"/>
      <Icon size={13}/>
      <span className="h-px w-3 border-t border-dashed border-chart/50 sm:w-5"/>
    </span>);
}
function LineChain({ leg }: {
    leg: PublicTransportLeg;
}) {
    const chain = legLineChain(leg);
    if (chain.length <= 1)
        return null;
    return (<ol data-testid="transport-line-chain" className="mt-2 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1">
      {chain.map((name, index) => (<li key={`${name}-${index}`} className="flex min-w-0 items-center gap-1.5">
          {index > 0 && <span className="shrink-0 text-ink-muted" aria-hidden>›</span>}
          <span className="min-w-0 break-words rounded-label border border-chart/25 bg-chart/[0.06] px-1.5 py-0.5 text-[11px] font-medium text-chart">
            {name}
          </span>
        </li>))}
    </ol>);
}
function CardShell({ leg, family, badge, aside = null, sandboxNote = null, compact = false, children, }: {
    leg: PublicTransportLeg;
    family: TransportFamily;
    badge?: React.ReactNode;
    aside?: React.ReactNode;
    sandboxNote?: string | null;
    compact?: boolean;
    children: React.ReactNode;
}) {
    const Icon = TRANSPORT_MODE_ICONS[leg.selected_mode];
    const variant = leg.transport_class === 'long_distance'
        ? 'long-distance'
        : leg.transport_class === 'public_transit' ? 'public-transit' : 'flexible';
    const providerNote = leg.transport_class === 'long_distance' && Boolean(sandboxNote);
    return (<article data-testid={`transport-card-${leg.transport_leg_id}`} data-transport-variant={variant} data-transport-family={family} className={cn('my-2 min-w-0 overflow-hidden rounded-card border border-stroke bg-panel', compact ? 'p-2' : 'p-2.5')}>
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <p className="inline-flex min-w-0 items-center gap-2">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-card bg-chart/10 text-chart">
            <Icon size={13} aria-hidden/>
          </span>
          <span className="min-w-0 break-words text-[13px] font-semibold text-ink">
            {TRANSPORT_MODE_LABELS[leg.selected_mode]}
          </span>
          <span className={cn(READOUT_LABEL, 'shrink-0 text-ink-muted')}>
            {TRANSPORT_FAMILY_NOUNS[family]}
          </span>
        </p>
        <span className="flex min-w-0 shrink-0 items-center gap-2">
          {aside}
          {badge}
          {providerNote && <TransportProviderNote detail={sandboxNote!}/>}
        </span>
      </div>
      {children}
    </article>);
}
function Badge({ children }: {
    children: React.ReactNode;
}) {
    return (<span className="shrink-0 rounded-label bg-surface px-2 py-0.5 text-[11px] font-medium text-ink-secondary">{children}</span>);
}
function LegBadge({ leg }: {
    leg: PublicTransportLeg;
}) {
    if (leg.route_status !== 'ready')
        return null;
    if (leg.transport_class === 'long_distance') {
        if (leg.booking_status === 'unknown')
            return null;
        return <Badge>{BOOKING_LABELS[leg.booking_status]}</Badge>;
    }
    if (leg.mode_preference.locked_mode)
        return <Badge>方式已锁定</Badge>;
    return null;
}
interface TransportLegCardProps {
    leg: PublicTransportLeg;
    sourceMarkers?: React.ReactNode;
    sandboxNote?: string | null;
}
function SupportingContent({ leg, sourceMarkers }: TransportLegCardProps) {
    return (<>
      <RouteState leg={leg}/>
      <SegmentDisclosure leg={leg}/>
      <IntentExplanationList items={leg.intent_explanations}/>
      {sourceMarkers}
    </>);
}
function ScheduledTicket({ leg, sourceMarkers, sandboxNote = null }: TransportLegCardProps) {
    const Icon = TRANSPORT_MODE_ICONS[leg.selected_mode];
    const ready = leg.route_status === 'ready';
    return (<CardShell leg={leg} family="scheduled" badge={<LegBadge leg={leg}/>} aside={ready ? <ServiceStub leg={leg}/> : null} sandboxNote={sandboxNote}>
      {ready && (<>
          <div className="mt-2 flex min-w-0 items-start gap-2">
            <TicketEndpoint endpoint={leg.from_endpoint} clock={clockLabel(leg.departure_at)} align="left"/>
            <TransitSpan Icon={Icon}/>
            <TicketEndpoint endpoint={leg.to_endpoint} clock={clockLabel(leg.arrival_at)} align="right"/>
          </div>
          <ReadoutRow readouts={legReadouts(leg)} layout="inline"/>
        </>)}
      <SupportingContent leg={leg} sourceMarkers={sourceMarkers}/>
    </CardShell>);
}
function TransitCard({ leg, sourceMarkers }: TransportLegCardProps) {
    const ready = leg.route_status === 'ready';
    return (<CardShell leg={leg} family="transit" badge={<LegBadge leg={leg}/>} aside={ready ? <TimeWindow departure={leg.departure_at} arrival={leg.arrival_at} className="text-[11px]"/> : null}>
      {ready && (<>
          <RouteLine leg={leg} className="mt-2"/>
          <LineChain leg={leg}/>
          <ReadoutRow readouts={legReadouts(leg)} layout="inline"/>
        </>)}
      <SupportingContent leg={leg} sourceMarkers={sourceMarkers}/>
    </CardShell>);
}
function RoadCard({ leg, sourceMarkers }: TransportLegCardProps) {
    const ready = leg.route_status === 'ready';
    return (<CardShell leg={leg} family="road" badge={<LegBadge leg={leg}/>} aside={ready ? <TimeWindow departure={leg.departure_at} arrival={leg.arrival_at} className="text-[11px]"/> : null}>
      {ready && (<>
          <RouteLine leg={leg} className="mt-2"/>
          <ReadoutRow readouts={legReadouts(leg)} layout="stacked"/>
        </>)}
      <SupportingContent leg={leg} sourceMarkers={sourceMarkers}/>
    </CardShell>);
}
function SelfCard({ leg, sourceMarkers }: TransportLegCardProps) {
    const ready = leg.route_status === 'ready';
    return (<CardShell leg={leg} family="self" compact badge={<LegBadge leg={leg}/>}>
      {ready && (<>
          <RouteLine leg={leg} className="mt-2"/>
          <ReadoutRow readouts={legReadouts(leg)} layout="inline"/>
        </>)}
      <SupportingContent leg={leg} sourceMarkers={sourceMarkers}/>
    </CardShell>);
}
function OtherCard({ leg, sourceMarkers }: TransportLegCardProps) {
    const ready = leg.route_status === 'ready';
    return (<CardShell leg={leg} family="other" badge={<LegBadge leg={leg}/>}>
      {ready && (<>
          <RouteLine leg={leg} className="mt-2"/>
          <ReadoutRow readouts={legReadouts(leg)} layout="inline"/>
        </>)}
      <SupportingContent leg={leg} sourceMarkers={sourceMarkers}/>
    </CardShell>);
}
function MicroConnector({ leg, sourceMarkers }: TransportLegCardProps) {
    const Icon = TRANSPORT_MODE_ICONS[leg.selected_mode];
    const facts = [durationLabel(leg.duration_minutes), distanceLabel(leg.distance_meters)]
        .filter((value): value is string => Boolean(value))
        .join(' · ');
    return (<article data-testid={`transport-card-${leg.transport_leg_id}`} data-transport-variant="micro" data-transport-family="self" className="min-w-0 py-1.5">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 rounded-card border border-dashed border-chart/40 bg-panel px-2.5 py-1.5 text-xs text-ink-secondary">
        <Icon size={13} className="shrink-0 text-chart" aria-hidden/>
        <strong className="min-w-0 break-words font-semibold text-ink">{leg.from_endpoint.name} → {leg.to_endpoint.name}</strong>
        {facts && <span className="text-ink-muted">{facts}</span>}
        {sourceMarkers}
      </div>
    </article>);
}
export const TransportLegCard: React.FC<TransportLegCardProps> = (props) => {
    if (props.leg.is_micro_transport)
        return <MicroConnector {...props}/>;
    switch (transportFamily(props.leg.selected_mode)) {
        case 'scheduled': return <ScheduledTicket {...props}/>;
        case 'transit': return <TransitCard {...props}/>;
        case 'road': return <RoadCard {...props}/>;
        case 'self': return <SelfCard {...props}/>;
        case 'other': return <OtherCard {...props}/>;
    }
};
