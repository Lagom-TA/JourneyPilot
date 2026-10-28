import { AnimatePresence, m } from 'motion/react';
import { ChevronDown, MapPinned } from 'lucide-react';
import React from 'react';
import { duration, easing, staggerContainer, staggerItem } from '../../../../lib/motion';
import { cn } from '../../../../lib/utils';
import { PresenceFrame } from '../../../../components/ui/PresenceSurface';
import { selectDayTimeline, type DaySummaryVM, type DayTimelineNodeVM } from '../../model/itineraryPresentation';
import { waypointSequenceFor, type WaypointPlacement } from '../../model/waypointOrder';
import { type PublicDeliveryBundle } from '../../types/delivery';
import {
  type PublicCustomBlock,
  type PublicDiningStop,
  type PublicLodgingStay,
  type PublicTransportLeg,
  type PublicVisitStop,
} from '../../types/itinerary';
import { CustomBlockRow, DiningStopCard, LodgingStayCard, VisitStopCard } from './TravelEntityCards';
import { TransportLegCard } from './TransportLegCard';
import { DayHeader } from './DayHeader';
import { TimelineNodeMark } from './TimelineNodeMark';

export type TimelineEntity = PublicVisitStop | PublicDiningStop | PublicLodgingStay | PublicTransportLeg | PublicCustomBlock;
type DayPlan = PublicDeliveryBundle['workspace']['itinerary']['day_plans'][number];

export interface CardMapSelection {
  entityId: string;
  occurrenceKey: string;
  day: number;
  entityType: TimelineEntity['type'];
}

interface ItineraryCardFlowProps {
  bundle: PublicDeliveryBundle;
  days: readonly DayPlan[];
  summaries: readonly DaySummaryVM[];
  entities: ReadonlyMap<string, TimelineEntity>;
  waypointOrder: ReadonlyMap<string, WaypointPlacement>;
  drawableRouteIds: ReadonlySet<string>;
  linkedEntityId: string | null;
  selectedEntityId: string | null;
  selectedOccurrenceKey: string | null;
  onLinkEntity: (entityId: string | null) => void;
  onSelectEntity: (selection: CardMapSelection) => void;
}

export function TimelineEntityDetails({ bundle, entity }: { bundle: PublicDeliveryBundle; entity: TimelineEntity }) {
  if (entity.type === 'transport_leg') {
    return <TransportLegCard leg={entity} sandboxNote={bundle.provider_environment.sandbox_note} />;
  }
  if (entity.type === 'visit_stop') return <VisitStopCard stop={entity} />;
  if (entity.type === 'dining_stop') return <DiningStopCard stop={entity} />;
  if (entity.type === 'lodging_stay') return <LodgingStayCard stay={entity} />;
  return <CustomBlockRow block={entity} />;
}

const ENTITY_LABELS: Record<DayTimelineNodeVM['entityKind'], string> = {
  visit: '景点与体验',
  dining: '餐饮',
  lodging: '住宿',
  transport: '交通',
  custom: '自定义安排',
};

function occurrenceLabel(node: DayTimelineNodeVM): string {
  if (node.entityKind === 'lodging') {
    if (node.role === 'arrival') return '住宿 · 入住';
    if (node.role === 'departure') return '住宿 · 退房';
  }
  if (node.entityKind === 'transport') {
    if (node.role === 'arrival') return '交通 · 抵达';
    if (node.role === 'departure') return '交通 · 出发';
  }
  return ENTITY_LABELS[node.entityKind];
}

interface OccurrenceCardProps {
  bundle: PublicDeliveryBundle;
  day: number;
  node: DayTimelineNodeVM;
  entity: TimelineEntity | null;
  waypointOrder: ReadonlyMap<string, WaypointPlacement>;
  drawableRouteIds: ReadonlySet<string>;
  linked: boolean;
  selected: boolean;
  selectedEntity: boolean;
  onLinkEntity: (entityId: string | null) => void;
  onSelectEntity: (selection: CardMapSelection) => void;
}

function OccurrenceCard({
  bundle,
  day,
  node,
  entity,
  waypointOrder,
  drawableRouteIds,
  linked,
  selected,
  selectedEntity,
  onLinkEntity,
  onSelectEntity,
}: OccurrenceCardProps) {
  const [detailsOpen, setDetailsOpen] = React.useState(false);
  const waypoint = waypointSequenceFor(waypointOrder, node.entityKind, node.entityId);
  const transport = entity?.type === 'transport_leg';
  const custom = entity?.type === 'custom_block';
  const mappable = transport ? drawableRouteIds.has(node.entityId) : !custom && waypoint != null;
  const detailId = `journey-occurrence-detail-${node.key}`;
  const selectOnMap = () => {
    if (!mappable) return;
    onSelectEntity({
      entityId: node.entityId,
      occurrenceKey: node.key,
      day,
      entityType: entity?.type ?? 'custom_block',
    });
  };

  return (
    <m.li
      layout="position"
      variants={staggerItem}
      className={cn('journey-occurrence', transport && 'is-transport', custom && 'is-custom')}
      data-itinerary-occurrence={node.key}
      data-entity-id={node.entityId}
      data-linked={linked ? 'on' : undefined}
      data-selected={selected ? 'on' : undefined}
      data-entity-selected={selectedEntity ? 'on' : undefined}
      onPointerEnter={(event) => {
        if (mappable && event.pointerType === 'mouse') onLinkEntity(node.entityId);
      }}
      onPointerLeave={(event) => {
        if (mappable && event.pointerType === 'mouse') onLinkEntity(null);
      }}
      onFocusCapture={() => {
        if (mappable) onLinkEntity(node.entityId);
      }}
      onBlurCapture={(event) => {
        if (mappable && !event.currentTarget.contains(event.relatedTarget as Node | null)) onLinkEntity(null);
      }}
    >
      <article className="journey-place-card">
        <div className="journey-card-heading">
          <span className="journey-card-mark">
            <TimelineNodeMark node={node} />
            {waypoint != null && <span className="journey-card-waypoint">{waypoint}</span>}
          </span>
          <p>{occurrenceLabel(node)}</p>
          {node.timeLabel && <time>{node.timeLabel}</time>}
        </div>

        {transport && entity ? (
          <div className="journey-transport-card">
            <TransportLegCard leg={entity} sandboxNote={bundle.provider_environment.sandbox_note} />
          </div>
        ) : (
          <div className="journey-card-copy">
            <h3>{node.title}</h3>
            {node.summary && <p>{node.summary}</p>}
            {(node.durationLabel || node.priceLabel) && (
              <div className="journey-card-readouts">
                {node.durationLabel && <span>{node.durationLabel}</span>}
                {node.priceLabel && <span>{node.priceLabel}</span>}
              </div>
            )}
          </div>
        )}

        {(mappable || (entity && !transport)) && (
          <div className="journey-card-actions">
            {mappable && (
              <button type="button" data-map-focus-trigger onClick={selectOnMap}>
                <MapPinned size={14} aria-hidden />{transport ? '查看路线' : '在地图查看'}
              </button>
            )}
            {entity && !transport && (
              <button
                type="button"
                className="journey-card-details-toggle"
                aria-expanded={detailsOpen}
                aria-controls={detailId}
                onClick={() => setDetailsOpen((open) => !open)}
              >
                {detailsOpen ? '收起详情' : '查看详情'}
                <ChevronDown size={13} aria-hidden className={cn('transition-transform', detailsOpen && 'rotate-180')} />
              </button>
            )}
          </div>
        )}

        <AnimatePresence initial={false}>
          {detailsOpen && entity && !transport && (
            <PresenceFrame
              id={detailId}
              className="journey-card-details"
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0, transition: { duration: duration.base, ease: easing.decelerate } }}
              exit={{ opacity: 0, y: -4, transition: { duration: duration.fast, ease: easing.accelerate } }}
            >
              <TimelineEntityDetails bundle={bundle} entity={entity} />
            </PresenceFrame>
          )}
        </AnimatePresence>
      </article>
    </m.li>
  );
}

export function ItineraryCardFlow({
  bundle,
  days,
  summaries,
  entities,
  waypointOrder,
  drawableRouteIds,
  linkedEntityId,
  selectedEntityId,
  selectedOccurrenceKey,
  onLinkEntity,
  onSelectEntity,
}: ItineraryCardFlowProps) {
  const summaryById = React.useMemo(() => new Map(summaries.map((summary) => [summary.dayId, summary])), [summaries]);

  return (
    <div className="journey-card-days" data-testid="itinerary-card-flow">
      {days.map((day) => {
        const summary = summaryById.get(day.day_id);
        const timeline = selectDayTimeline(bundle, day.day_id);
        return (
          <section key={day.day_id} className="journey-day-section" aria-labelledby={`delivery-day-${day.day_id}`}>
            <DayHeader
              dayId={day.day_id}
              day={day.day}
              dateLabel={summary?.dateLabel ?? null}
              weekdayLabel={summary?.weekdayLabel ?? null}
              destinationLabel={summary?.destinationLabel ?? null}
              theme={day.theme}
              weather={summary?.weather ?? null}
            />
            <m.ol
              className="journey-card-flow"
              aria-label={`第 ${day.day} 天行程卡片`}
              variants={staggerContainer(timeline.length)}
              initial="hidden"
              animate="visible"
            >
              {timeline.map((node) => {
                const entry = day.timeline.find((item) => item.entry_id === node.key);
                const entity = entry ? entities.get(entry.entity_id) ?? null : null;
                return (
                  <OccurrenceCard
                    key={node.key}
                    bundle={bundle}
                    day={day.day}
                    node={node}
                    entity={entity}
                    waypointOrder={waypointOrder}
                    drawableRouteIds={drawableRouteIds}
                    linked={node.entityId === linkedEntityId}
                    selected={node.key === selectedOccurrenceKey}
                    selectedEntity={node.entityId === selectedEntityId}
                    onLinkEntity={onLinkEntity}
                    onSelectEntity={onSelectEntity}
                  />
                );
              })}
            </m.ol>
          </section>
        );
      })}
    </div>
  );
}
