import { ChevronDown } from "lucide-react";
import { cn } from "../../../../lib/utils";
import { READOUT_LABEL } from "../../../../lib/typography";
import { TransportProviderNote } from "./TransportProviderNote";
import { type PublicTransportLeg } from "../../types/itinerary";
import { type TransportEndpoint, type TransportMode, type TransportSegment } from "../../types/entities";
import { BOOKING_LABELS, TRANSPORT_MODE_LABELS } from "../../model/deliveryLabels";
import { TRANSPORT_FAMILY_NOUNS, TRANSPORT_MODE_ICONS, clockLabel, distanceLabel, durationLabel, legReadouts, legService, legSummary, showsEndpointCode, transitDisplayMode, transitLineChain, transitModeLabel, transitStations, transportFamily, transportModeStyle, transportSegmentDisplayMode, type Readout, type TransitLineChain, type TransitLineStep, type TransitRide, type TransportFamily } from "../../model/transportPresentation";
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
function SegmentRow({ segment, index, selectedMode }: {
    segment: TransportSegment;
    index: number;
    selectedMode: TransportMode;
}) {
    const mode = transportSegmentDisplayMode(selectedMode, segment.mode);
    const Icon = TRANSPORT_MODE_ICONS[mode];
    return (<li className="flex min-w-0 gap-2.5 py-2 first:pt-1 last:pb-1">
      <span style={transportModeStyle(mode)} className="transport-mode-icon flex h-6 w-6 shrink-0 items-center justify-center rounded-card" aria-hidden>
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
            TRANSPORT_MODE_LABELS[mode],
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
      <button type="button" data-testid="transport-segments-toggle" aria-expanded={open} aria-controls={disclosureId} onClick={(event) => {
            event.stopPropagation();
            setOpen((current) => !current);
        }} className="-ml-2 mt-1 inline-flex min-h-9 items-center gap-1 rounded-card px-2 text-[11px] font-semibold text-ink-secondary transition-colors hover:bg-highlight hover:text-ink">
        {open ? '收起路线步骤' : `展开 ${leg.segments.length} 个路线步骤`}
        <ChevronDown size={13} aria-hidden className={cn('transition-transform', open && 'rotate-180')}/>
      </button>
      {open && (<ol id={disclosureId} className="divide-y divide-stroke/60" data-testid="transport-segments">
          {leg.segments.map((segment, index) => <SegmentRow key={segment.segment_id} segment={segment} index={index} selectedMode={leg.selected_mode}/>)}
        </ol>)}
    </>);
}
function RouteState({ leg }: {
    leg: PublicTransportLeg;
}) {
    const text = routeStateText(leg);
    if (!text)
        return null;
    return (<p role="status" className="mt-1.5 rounded-card bg-surface px-2.5 py-1.5 text-xs leading-5 text-ink-secondary">
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
      <span className="transport-mode-text mx-1.5 font-normal" aria-hidden>→</span>
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
function LegSummaryRow({ leg }: {
    leg: PublicTransportLeg;
}) {
    const summary = legSummary(leg);
    if (!summary.duration && !summary.cost)
        return null;
    return (<dl data-testid="transport-summary" className="mt-2 flex min-w-0 flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-t border-stroke/60 pt-2">
      {summary.duration && (<div data-summary="duration">
          <dt className="sr-only">时长</dt>
          <dd className="font-mono text-sm font-semibold tabular-nums text-ink">{summary.duration}</dd>
        </div>)}
      {summary.cost && (<div data-summary="cost" className="ml-auto">
          <dt className="sr-only">费用</dt>
          <dd className="font-mono text-sm font-semibold tabular-nums text-ink">{summary.cost}</dd>
        </div>)}
    </dl>);
}
function TicketEndpoint({ endpoint, mode, align, }: {
    endpoint: TransportEndpoint;
    mode: TransportMode;
    align: 'left' | 'right';
}) {
    const code = showsEndpointCode(mode) ? endpoint.station_code : null;
    return (<div className={cn('min-w-0 flex-1', align === 'right' && 'text-right')}>
      <p className="break-words text-base font-semibold leading-tight text-ink">{endpoint.name}</p>
      {code && (<p className="mt-1 font-mono text-[11px] font-medium leading-4 tracking-[0.06em] text-ink-secondary">
          {code}
        </p>)}
    </div>);
}
function ConnectorLine() {
    return <span className="transport-mode-dash mt-2.5 h-px w-6 shrink-0 border-t border-dashed sm:w-10" aria-hidden/>;
}
function TransitStationLine({ leg }: {
    leg: PublicTransportLeg;
}) {
    const stations = transitStations(leg);
    if (!stations.from && !stations.to)
        return null;
    return (<p data-testid="transport-stations" className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[13px] font-semibold text-ink">
      {stations.from && <span className="min-w-0 break-words">{stations.from}</span>}
      {stations.from && stations.to && <span className="transport-mode-text shrink-0 font-normal" aria-hidden>→</span>}
      {stations.to && <span className="min-w-0 break-words">{stations.to}</span>}
    </p>);
}
function TransitReadoutRow({ leg }: {
    leg: PublicTransportLeg;
}) {
    const summary = legSummary(leg);
    if (!summary.duration && !summary.cost)
        return null;
    return (<dl data-testid="transport-summary" className="ml-auto flex shrink-0 items-baseline gap-x-3 font-mono text-xs tabular-nums">
      {summary.duration && (<div data-summary="duration" className="flex items-baseline">
          <dt className="sr-only">时长</dt>
          <dd className="font-semibold text-ink">{summary.duration}</dd>
        </div>)}
      {summary.cost && (<div data-summary="cost" className="flex items-baseline">
          <dt className="sr-only">费用</dt>
          <dd className="font-semibold text-ink">{summary.cost}</dd>
        </div>)}
    </dl>);
}
function TransitLineIdentity({ step }: {
    step: TransitLineStep;
}) {
    return (<span className="inline-flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <span data-testid="transit-line-label" className="min-w-0 break-words text-[13px] font-semibold text-ink">{step.label}</span>
      {step.direction && (<span data-testid="transit-direction" className="min-w-0 break-words text-[11px] font-medium text-ink-secondary">往{step.direction}</span>)}
    </span>);
}
function TransitChainToggle({ chain, open, onToggle, disclosureId }: {
    chain: TransitLineChain;
    open: boolean;
    onToggle: () => void;
    disclosureId: string;
}) {
    return (<button type="button" data-testid="transit-line-chain" aria-expanded={open} aria-controls={disclosureId} onClick={(event) => {
            event.stopPropagation();
            onToggle();
        }} className="-mx-1 inline-flex min-h-8 min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 rounded-card px-1 text-left text-[13px] font-semibold text-ink transition-colors hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
      {chain.steps.map((step, index) => (<React.Fragment key={step.key}>
          {index > 0 && <span className="transport-mode-text shrink-0 font-normal" aria-hidden>→</span>}
          <span className="min-w-0 break-words">{step.label}</span>
        </React.Fragment>))}
      <ChevronDown size={13} aria-hidden className={cn('shrink-0 text-ink-muted transition-transform', open && 'rotate-180')}/>
      <span className="sr-only">{open ? '收起乘车段' : '展开乘车段'}</span>
    </button>);
}
function TransitRideRow({ ride }: {
    ride: TransitRide;
}) {
    const Icon = TRANSPORT_MODE_ICONS[ride.mode];
    const segment = ride.segment;
    const facts = [
        durationLabel(segment.duration_minutes),
        distanceLabel(segment.distance_meters),
        segment.operator_name,
    ].filter((value): value is string => Boolean(value));
    return (<li className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <span style={transportModeStyle(ride.mode)} className="transport-mode-icon flex h-5 w-5 shrink-0 items-center justify-center rounded-card" aria-hidden>
        <Icon size={11}/>
      </span>
      <span className="min-w-0 break-words text-xs font-semibold text-ink">{ride.rowLabel}</span>
      {ride.direction && <span className="min-w-0 break-words text-[11px] text-ink-secondary">往{ride.direction}</span>}
      <span className="min-w-0 break-words text-[11px] text-ink-secondary">{segment.from_endpoint.name} → {segment.to_endpoint.name}</span>
      <span className="ml-auto flex shrink-0 flex-wrap items-baseline gap-x-2 font-mono text-[11px] tabular-nums text-ink-muted">
        <TimeWindow departure={segment.departure_at} arrival={segment.arrival_at} className="text-[11px]"/>
        {facts.length > 0 && <span>{facts.join(' · ')}</span>}
      </span>
    </li>);
}
function TransitRideList({ chain, id, open }: {
    chain: TransitLineChain;
    id: string;
    open: boolean;
}) {
    return (<ol id={id} data-testid="transport-rides" hidden={!open} className="mt-1.5 space-y-1 border-t border-stroke/60 pt-1.5">
      {chain.rides.map((ride) => <TransitRideRow key={ride.key} ride={ride}/>)}
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
    const displayMode = leg.selected_mode;
    const modeLabel = TRANSPORT_MODE_LABELS[leg.selected_mode];
    const Icon = TRANSPORT_MODE_ICONS[displayMode];
    const variant = leg.transport_class === 'long_distance'
        ? 'long-distance'
        : leg.transport_class === 'public_transit' ? 'public-transit' : 'flexible';
    const providerNote = leg.transport_class === 'long_distance' && Boolean(sandboxNote);
    const service = family === 'scheduled' ? legService(leg) : null;
    const serviceLabel = service?.serviceNumber ?? service?.lineName ?? null;
    const showNoun = family !== 'scheduled';
    return (<article data-testid={`transport-card-${leg.transport_leg_id}`} data-transport-variant={variant} data-transport-family={family} data-transport-mode={displayMode} style={transportModeStyle(displayMode)} className={cn('my-2 min-w-0 overflow-hidden rounded-card border border-stroke bg-panel', compact ? 'p-2' : 'p-2.5')}>
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <p className="inline-flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="transport-mode-icon flex h-6 w-6 shrink-0 items-center justify-center rounded-card">
            <Icon size={13} aria-hidden/>
          </span>
          <span className="min-w-0 break-words text-[13px] font-semibold text-ink">
            {modeLabel}
          </span>
          {serviceLabel && (<span data-service={service?.serviceNumber ? 'number' : 'line'} className="min-w-0 break-words font-mono text-[13px] font-semibold tracking-[0.04em] text-ink">
              {serviceLabel}
            </span>)}
          {service?.operator && (<span data-service="operator" className="min-w-0 break-words text-[11px] font-medium text-ink-muted">
              {service.operator}
            </span>)}
          {showNoun && (<span className={cn(READOUT_LABEL, 'shrink-0 text-ink-muted')}>
              {TRANSPORT_FAMILY_NOUNS[family]}
            </span>)}
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
    sandboxNote?: string | null;
}
function SupportingContent({ leg }: TransportLegCardProps) {
    return (<>
      <RouteState leg={leg}/>
      <SegmentDisclosure leg={leg}/>
         </>);
}
function ScheduledTicket({ leg, sandboxNote = null }: TransportLegCardProps) {
    const ready = leg.route_status === 'ready';
    return (<CardShell leg={leg} family="scheduled" badge={<LegBadge leg={leg}/>} aside={ready ? <TimeWindow departure={leg.departure_at} arrival={leg.arrival_at} className="text-[11px]"/> : null} sandboxNote={sandboxNote}>
      {ready && (<>
          <div className="mt-2 flex min-w-0 items-start gap-2">
            <TicketEndpoint endpoint={leg.from_endpoint} mode={leg.selected_mode} align="left"/>
            <ConnectorLine/>
            <TicketEndpoint endpoint={leg.to_endpoint} mode={leg.selected_mode} align="right"/>
          </div>
          <LegSummaryRow leg={leg}/>
        </>)}
      <SupportingContent leg={leg}/>
    </CardShell>);
}
function TransitCard({ leg }: TransportLegCardProps) {
    const ready = leg.route_status === 'ready';
    const chain = transitLineChain(leg);
    const displayMode = transitDisplayMode(leg);
    const Icon = TRANSPORT_MODE_ICONS[displayMode];
    const variant = leg.transport_class === 'long_distance'
        ? 'long-distance'
        : leg.transport_class === 'public_transit' ? 'public-transit' : 'flexible';
    const [ridesOpen, setRidesOpen] = React.useState(false);
    const ridesId = `transport-rides-${leg.transport_leg_id}`;
    const fallbackLabel = transitModeLabel(leg) ?? TRANSPORT_MODE_LABELS[leg.selected_mode];
    const identity = chain.steps.length === 0
        ? (<span className="min-w-0 break-words text-[13px] font-semibold text-ink">{fallbackLabel}</span>)
        : chain.expandable
            ? (<TransitChainToggle chain={chain} open={ridesOpen} onToggle={() => setRidesOpen((current) => !current)} disclosureId={ridesId}/>)
            : <TransitLineIdentity step={chain.steps[0]}/>;
    return (<article data-testid={`transport-card-${leg.transport_leg_id}`} data-transport-variant={variant} data-transport-family="transit" data-transport-mode={displayMode} style={transportModeStyle(displayMode)} className="my-2 min-w-0 overflow-hidden rounded-card border border-stroke bg-panel p-2.5">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="inline-flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="transport-mode-icon flex h-6 w-6 shrink-0 items-center justify-center rounded-card">
            <Icon size={13} aria-hidden/>
          </span>
          {ready ? identity : (<span className="min-w-0 break-words text-[13px] font-semibold text-ink">{fallbackLabel}</span>)}
          <LegBadge leg={leg}/>
        </div>
        {ready && <TimeWindow departure={leg.departure_at} arrival={leg.arrival_at} className="shrink-0 text-[11px]"/>}
      </div>
      {ready && (<div className="mt-1 flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <TransitStationLine leg={leg}/>
          <TransitReadoutRow leg={leg}/>
        </div>)}
      {ready && chain.expandable && <TransitRideList chain={chain} id={ridesId} open={ridesOpen}/>}
      <RouteState leg={leg}/>
    </article>);
}
function RoadCard({ leg }: TransportLegCardProps) {
    const ready = leg.route_status === 'ready';
    return (<CardShell leg={leg} family="road" badge={<LegBadge leg={leg}/>} aside={ready ? <TimeWindow departure={leg.departure_at} arrival={leg.arrival_at} className="text-[11px]"/> : null}>
      {ready && (<>
          <RouteLine leg={leg} className="mt-2"/>
          <ReadoutRow readouts={legReadouts(leg)} layout="stacked"/>
        </>)}
      <SupportingContent leg={leg}/>
    </CardShell>);
}
function SelfCard({ leg }: TransportLegCardProps) {
    const ready = leg.route_status === 'ready';
    return (<CardShell leg={leg} family="self" compact badge={<LegBadge leg={leg}/>}>
      {ready && (<>
          <RouteLine leg={leg} className="mt-2"/>
          <ReadoutRow readouts={legReadouts(leg)} layout="inline"/>
        </>)}
      <SupportingContent leg={leg}/>
    </CardShell>);
}
function OtherCard({ leg }: TransportLegCardProps) {
    const ready = leg.route_status === 'ready';
    return (<CardShell leg={leg} family="other" badge={<LegBadge leg={leg}/>}>
      {ready && (<>
          <RouteLine leg={leg} className="mt-2"/>
          <ReadoutRow readouts={legReadouts(leg)} layout="inline"/>
        </>)}
      <SupportingContent leg={leg}/>
    </CardShell>);
}
function MicroConnector({ leg }: TransportLegCardProps) {
    const Icon = TRANSPORT_MODE_ICONS[leg.selected_mode];
    const facts = [durationLabel(leg.duration_minutes), distanceLabel(leg.distance_meters)]
        .filter((value): value is string => Boolean(value))
        .join(' · ');
    return (<article data-testid={`transport-card-${leg.transport_leg_id}`} data-transport-variant="micro" data-transport-family="self" data-transport-mode={leg.selected_mode} style={transportModeStyle(leg.selected_mode)} className="min-w-0 py-1.5">
      <div className="transport-mode-outline flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 rounded-card border border-dashed bg-panel px-2.5 py-1.5 text-xs text-ink-secondary">
        <Icon size={13} className="transport-mode-text shrink-0" aria-hidden/>
        <strong className="min-w-0 break-words font-semibold text-ink">{leg.from_endpoint.name} → {leg.to_endpoint.name}</strong>
        {facts && <span className="text-ink-muted">{facts}</span>}
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
