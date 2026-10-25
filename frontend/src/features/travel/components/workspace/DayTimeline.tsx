import { m } from "motion/react";
import { ChevronDown } from "lucide-react";
import { type DayTimelineNodeVM } from "../../model/itineraryPresentation";
import { cn } from "../../../../lib/utils";
import { TRIP_DOMAIN_PRESENTATION } from "../../model/tripDomains";
import { waypointSequenceFor, type WaypointPlacement } from "../../model/waypointOrder";
import { staggerContainer, staggerItem } from "../../../../lib/motion";
import { READOUT_LABEL } from "../../../../lib/typography";
import { TimelineNodeMark, nodeDomain } from "./TimelineNodeMark";
import React from 'react';
const CUSTOM_ROLE_LABELS: Record<DayTimelineNodeVM['role'], string> = {
    place: '自定义安排',
    movement: '自定义移动',
    arrival: '抵达',
    departure: '离开',
};
const LODGING_EDGE_LABELS: Partial<Record<DayTimelineNodeVM['role'], string>> = {
    arrival: '入住',
    departure: '退房',
};
const TRANSPORT_EDGE_LABELS: Partial<Record<DayTimelineNodeVM['role'], string>> = {
    arrival: '抵达',
    departure: '出发',
};
function nodeEdgeLabel(node: DayTimelineNodeVM): string | undefined {
    const domain = nodeDomain(node);
    if (domain === 'lodging')
        return LODGING_EDGE_LABELS[node.role];
    if (domain === 'transport')
        return TRANSPORT_EDGE_LABELS[node.role];
    return undefined;
}
function nodeTypeLabel(node: DayTimelineNodeVM): string {
    const domain = nodeDomain(node);
    if (!domain)
        return CUSTOM_ROLE_LABELS[node.role];
    const noun = TRIP_DOMAIN_PRESENTATION[domain].noun;
    const edge = nodeEdgeLabel(node);
    return edge ? `${noun} · ${edge}` : noun;
}
export interface DayTimelineProps {
    nodes: readonly DayTimelineNodeVM[];
    renderDetails?: (node: DayTimelineNodeVM) => React.ReactNode;
    renderSupplement?: (node: DayTimelineNodeVM) => React.ReactNode;
    waypointOrder?: ReadonlyMap<string, WaypointPlacement>;
    staggerEntrance?: boolean;
    linkedEntityId?: string | null;
    onLinkEntity?: (entityId: string | null) => void;
}
const WaypointMark: React.FC<{
    sequence: number;
}> = ({ sequence }) => (<span data-testid={`day-timeline-waypoint-${sequence}`} data-waypoint={sequence} className="inline-flex size-[17px] shrink-0 items-center justify-center rounded-full border border-chart/55 font-mono text-[11px] font-semibold tabular-nums leading-none text-chart">
    {sequence}
  </span>);
export function DayTimeline({ nodes, renderDetails, renderSupplement, waypointOrder, staggerEntrance = false, linkedEntityId = null, onLinkEntity, }: DayTimelineProps) {
    const [openNodeKey, setOpenNodeKey] = React.useState<string | null>(null);
    if (nodes.length === 0)
        return null;
    const orchestration = staggerEntrance
        ? { variants: staggerContainer(nodes.length), initial: 'hidden' as const, animate: 'visible' as const }
        : {};
    return (<m.ol data-testid="day-timeline" data-stagger-entrance={staggerEntrance ? 'on' : 'off'} aria-label="当天时间路线" className="min-w-0" {...orchestration}>
      {nodes.map((node, index) => {
            const details = renderDetails?.(node);
            const supplement = renderSupplement?.(node);
            const inlineCard = Boolean(details) && nodeDomain(node) === 'transport';
            const open = openNodeKey === node.key;
            const hasContinuation = index < nodes.length - 1;
            const detailId = `day-timeline-detail-${node.key}`;
            const waypoint = waypointOrder
                ? waypointSequenceFor(waypointOrder, node.entityKind, node.entityId)
                : null;
            const linkable = Boolean(onLinkEntity && node.entityId);
            const linked = Boolean(node.entityId) && node.entityId === linkedEntityId;
            return (<m.li key={node.key} data-testid={`day-timeline-node-${node.key}`} data-timeline-role={node.role} data-linked={linked ? 'on' : undefined} className="grid min-w-0 grid-cols-[5.5rem_minmax(0,1fr)] gap-x-9" variants={staggerEntrance ? staggerItem : undefined} onPointerEnter={linkable ? (event) => {
                    if (event.pointerType === 'mouse')
                        onLinkEntity!(node.entityId!);
                } : undefined} onPointerLeave={linkable ? (event) => {
                    if (event.pointerType === 'mouse')
                        onLinkEntity!(null);
                } : undefined}>
            <div className="pt-0.5 text-right">
              {node.timeLabel && <time className="block break-words text-xs font-semibold tabular-nums text-ink-secondary">{node.timeLabel}</time>}
            </div>

            <div className={cn('relative min-w-0', hasContinuation && 'pb-6')}>
              {hasContinuation && <span className="absolute -left-[1.3125rem] top-5 bottom-0 w-px bg-stroke" aria-hidden/>}
              <TimelineNodeMark node={node} className="absolute -left-[1.75rem] top-0.5"/>

              <div className={cn('relative min-w-0', node.role === 'movement' && !inlineCard ? 'pt-0.5' : '')}>

                <div aria-hidden data-testid={`day-timeline-linked-ground-${node.key}`} className={cn('pointer-events-none absolute -inset-x-2 -inset-y-1 rounded-card bg-highlight', 'transition-opacity duration-fast ease-standard', linked ? 'opacity-100' : 'opacity-0')}/>
                <div className="relative min-w-0">
                  {inlineCard ? (nodeEdgeLabel(node) && (<p className={cn(READOUT_LABEL, 'text-ink-muted')}>{nodeTypeLabel(node)}</p>)) : (<>
                      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">

                        {waypoint !== null && <WaypointMark sequence={waypoint}/>}

                        <p className={cn(READOUT_LABEL, 'text-ink-muted')}>{nodeTypeLabel(node)}</p>

                        {node.durationLabel && <span className="text-xs text-ink-secondary">{node.durationLabel}</span>}
                        {node.priceLabel && <span className="text-xs text-ink-secondary">{node.priceLabel}</span>}
                      </div>
                      <h3 className={cn('mt-0.5 break-words font-semibold text-ink', node.role === 'movement' ? 'text-sm' : 'text-base')}>
                        {node.title}
                      </h3>
                      {node.summary && <p className="mt-1 max-w-[68ch] break-words text-sm leading-6 text-ink-secondary">{node.summary}</p>}
                    </>)}
                  {supplement && <div className="min-w-0">{supplement}</div>}

                  {inlineCard && <div data-testid={detailId} className="min-w-0">{details}</div>}
                  {details && !inlineCard && (<>
                      <button type="button" data-testid={`day-timeline-details-${node.key}`} aria-expanded={open} aria-controls={detailId} onClick={() => setOpenNodeKey((current) => current === node.key ? null : node.key)} className="mt-1.5 inline-flex min-h-9 items-center gap-1 rounded-card px-2 text-xs font-semibold text-ink-secondary transition-colors hover:bg-highlight hover:text-ink">
                        {open ? '收起详情' : '查看详情'}
                        <ChevronDown size={14} aria-hidden className={cn('transition-transform', open && 'rotate-180')}/>
                      </button>
                      {open && (<div id={detailId} data-testid={detailId} className="mt-2 min-w-0 border-t border-stroke/60 pt-2.5">
                          {details}
                        </div>)}
                    </>)}
                </div>
              </div>
            </div>
          </m.li>);
        })}
    </m.ol>);
}
