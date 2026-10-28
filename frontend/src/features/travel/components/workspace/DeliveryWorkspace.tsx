import { AnimatePresence } from 'motion/react';
import type { Variants } from 'motion/react';
import { ArrowLeft, ArrowRight, BookOpen, CalendarDays, ChevronDown, Layers3, Map as MapIcon, MessageCircle, Sun, X } from 'lucide-react';
import { useApp } from '../../../../app/state/AppContext';
import { useIsMobileViewport } from '../../../../hooks/useMediaQuery';
import { Sheet } from '../../../../components/ui/Sheet';
import { CanvasMotion } from '../../../../components/ui/CanvasMotion';
import { PresenceFrame, PresenceSection } from '../../../../components/ui/PresenceSurface';
import { ConversationThread } from '../../../chat/components/ConversationThread';
import { buildWaypointOrder, type WaypointPlacement } from '../../model/waypointOrder';
import { buildBundleMapPlaces, isLocatedBundleMapPlace, locatedBundlePlaceIds, type BundleMapPlace } from '../../model/mapPlaces';
import { selectCurrentReportDocument, selectDaySummaries, selectDayTimeline, type DaySummaryVM, type DayTimelineNodeVM } from '../../model/itineraryPresentation';
import { resolveWorkspaceSceneTransition, type WorkspaceScene } from '../../model/workspaceTransition';
import { formatTripCostSummary } from '../../model/costPresentation';
import { routeLines } from '../../model/mapModel';
import { type ControlledTripIdentity } from '../../types/planner';
import { type PublicDeliveryBundle } from '../../types/delivery';
import { type MapProjection } from '../../types/report';
import { BundleMapLeafletLazy } from './BundleMapLeafletLazy';
import { DayTimeline } from './DayTimeline';
import { TripOverview } from './TripOverview';
import { FullReportView, PdfDownloadButton } from './FullReportView';
import { GenerationJourneyPanel } from './GenerationJourneyPanel';
import { ItineraryCardFlow, TimelineEntityDetails, type CardMapSelection, type TimelineEntity } from './ItineraryCardFlow';
import { cn } from '../../../../lib/utils';
import { duration, easing } from '../../../../lib/motion';
import React from 'react';

interface DeliveryWorkspaceProps {
  bundle: PublicDeliveryBundle | null;
  variant?: 'docked' | 'sheet';
}

type DayPlan = PublicDeliveryBundle['workspace']['itinerary']['day_plans'][number];
type PlaceLayer = 'visit_stop' | 'dining_stop' | 'lodging_stay';

const readingLayerVariants: Variants = {
  enter: { opacity: 0, x: 36 },
  visible: {
    opacity: 1,
    x: 0,
    transition: { duration: duration.detail, ease: easing.decelerate },
  },
  exit: {
    opacity: 0,
    x: 36,
    transition: { duration: duration.base, ease: easing.accelerate },
  },
};

const contentSceneVariants: Variants = {
  enter: (transition: { direction: number }) => ({
    opacity: 0,
    x: transition.direction * 24,
  }),
  visible: {
    opacity: 1,
    x: 0,
    transition: { duration: duration.page, ease: easing.decelerate },
  },
  exit: (transition: { direction: number }) => ({
    opacity: 0,
    x: transition.direction * -12,
    transition: { duration: duration.fast, ease: easing.accelerate },
  }),
};

const PLACE_LAYERS: Array<{ id: PlaceLayer; label: string }> = [
  { id: 'visit_stop', label: '景点与体验' },
  { id: 'dining_stop', label: '餐饮' },
  { id: 'lodging_stay', label: '住宿' },
];

function entityId(entity: TimelineEntity): string {
  if (entity.type === 'lodging_stay') return entity.stay_id;
  if (entity.type === 'transport_leg') return entity.transport_leg_id;
  return entity.item_id;
}

function buildEntityIndex(bundle: PublicDeliveryBundle): Map<string, TimelineEntity> {
  const itinerary = bundle.workspace.itinerary;
  const entities: TimelineEntity[] = [
    ...itinerary.visit_stops,
    ...itinerary.dining_stops,
    ...itinerary.lodging_stays,
    ...itinerary.transport_legs,
    ...itinerary.custom_blocks,
  ];
  return new Map(entities.map((entity) => [entityId(entity), entity]));
}

function identityPlaces(identity: ControlledTripIdentity): BundleMapPlace[] {
  const seen = new Set<string>();
  return [identity.origin, ...identity.destinations]
    .filter((place) => {
      const key = place.place_id || `${place.latitude},${place.longitude}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .map((place, index) => ({
      entity_ref: { entity_type: 'visit_stop', entity_id: `identity-${index}-${place.place_id}` },
      name: place.name,
      place_id: place.place_id,
      latitude: place.latitude,
      longitude: place.longitude,
      citation_ids: [],
      days: [],
      sequence: index + 1,
      markerId: `identity:${index}:${place.place_id}`,
      markerKind: 'identity',
      modes: [],
    }));
}

function routeIsDrawable(route: MapProjection['content']['routes'][number]): boolean {
  return routeLines(route).length > 0;
}

function localDateISO(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

function tripDays(identity: ControlledTripIdentity): number {
  if (!identity.start_date || !identity.end_date) return 0;
  return Math.floor((new Date(`${identity.end_date}T00:00:00`).getTime() - new Date(`${identity.start_date}T00:00:00`).getTime()) / 86400000) + 1;
}

function MapDayNav({ days, activeDay, onSelect }: {
  days: DayPlan[];
  activeDay: number | null;
  onSelect: (day: number | null) => void;
}) {
  return (
    <nav data-testid="itinerary-day-nav" aria-label="按天查看行程" className="journey-day-nav">
      <button type="button" aria-pressed={activeDay == null} onClick={() => onSelect(null)} className={cn(activeDay == null && 'is-active')}>全程</button>
      {days.map((day) => (
        <button key={day.day_id} type="button" aria-label={`第 ${day.day} 天`} aria-pressed={activeDay === day.day} onClick={() => onSelect(day.day)} className={cn(activeDay === day.day && 'is-active')}>
          D{day.day}
        </button>
      ))}
    </nav>
  );
}

function TodayNextCard({ node, actualToday }: { node: DayTimelineNodeVM | null; actualToday: boolean }) {
  if (!node) return null;
  return (
    <section className="today-next-card" aria-label="接下来的安排">
      <p>{actualToday ? '接下来' : '从这一天开始'}</p>
      <div>
        {node.timeLabel && <time>{node.timeLabel}</time>}
        <h2>{node.title}</h2>
      </div>
      {node.summary && <span>{node.summary}</span>}
    </section>
  );
}

function ReadingWorkspace({ bundle }: { bundle: PublicDeliveryBundle }) {
  const { dispatch } = useApp();
  const document = selectCurrentReportDocument(bundle);
  return (
    <section className="reading-workspace" aria-label="旅行阅读版">
      <header className="reading-toolbar">
        <button type="button" onClick={() => dispatch({ type: 'SET_DELIVERABLE_VIEW', payload: 'interactive_itinerary' })}><ArrowLeft size={15} />返回地图</button>
        <span>阅读版</span>
        <PdfDownloadButton bundle={bundle} compact />
      </header>
      <div className="reading-scroll">
        {document
          ? <FullReportView bundle={bundle} allowPdf={false} />
          : <div className="reading-pending" role="status"><BookOpen size={25} /><h1>阅读版正在整理</h1><p>地图与日程已经可以查看。</p></div>}
      </div>
    </section>
  );
}

export const DeliveryWorkspace: React.FC<DeliveryWorkspaceProps> = ({ bundle }) => {
  const { state, dispatch } = useApp();
  const isMobile = useIsMobileViewport();
  const [activeDay, setActiveDay] = React.useState<number | null>(null);
  const [sidebarMode, setSidebarMode] = React.useState<'itinerary' | 'conversation'>('itinerary');
  const [selectedEntityId, setSelectedEntityId] = React.useState<string | null>(null);
  const [selectedOccurrenceKey, setSelectedOccurrenceKey] = React.useState<string | null>(null);
  const [linkedEntityId, setLinkedEntityId] = React.useState<string | null>(null);
  const [layersOpen, setLayersOpen] = React.useState(false);
  const [showRoutes, setShowRoutes] = React.useState(true);
  const [hiddenLayers, setHiddenLayers] = React.useState<PlaceLayer[]>([]);
  const placeReturnFocusRef = React.useRef<{ entityId: string; occurrenceKey: string | null } | null>(null);
  const conversationReturnFocusRef = React.useRef<'navigation' | 'toolbar' | null>(null);
  const navigationScrollRef = React.useRef<HTMLDivElement>(null);
  const contentScrollRef = React.useRef<HTMLDivElement>(null);
  const summaryCardRefs = React.useRef(new Map<string, HTMLButtonElement>());
  const overviewScrollTop = React.useRef(0);
  const returnFocusDayId = React.useRef<string | null>(null);
  const identity = state.controlledTripIdentity;
  const itinerary = bundle?.workspace.itinerary ?? null;
  const view = state.deliverableView;
  const showReading = view === 'full_report' && bundle !== null;

  const restorePlaceFocus = React.useCallback(() => {
    const target = placeReturnFocusRef.current;
    if (!target) return;
    placeReturnFocusRef.current = null;
    window.requestAnimationFrame(() => {
      const occurrence = target.occurrenceKey
        ? [...document.querySelectorAll<HTMLElement>('[data-itinerary-occurrence]')]
          .find((node) => node.dataset.itineraryOccurrence === target.occurrenceKey)
        : null;
      const cardTrigger = occurrence?.querySelector<HTMLElement>('[data-map-focus-trigger]');
      if (cardTrigger) {
        cardTrigger.focus();
        return;
      }
      const marker = [...document.querySelectorAll<HTMLElement>('[data-bundle-map-entity]')]
        .find((node) => node.dataset.bundleMapEntity === target.entityId);
      const focusTarget = marker?.closest<HTMLElement>('.leaflet-marker-icon, button') ?? marker;
      focusTarget?.focus();
    });
  }, []);

  const closePlaceDetail = React.useCallback(() => {
    if (!selectedEntityId) return;
    placeReturnFocusRef.current = { entityId: selectedEntityId, occurrenceKey: selectedOccurrenceKey };
    setSelectedEntityId(null);
    setSelectedOccurrenceKey(null);
  }, [selectedEntityId, selectedOccurrenceKey]);

  const openConversation = React.useCallback((event: React.MouseEvent<HTMLButtonElement>) => {
    conversationReturnFocusRef.current = event.currentTarget.dataset.conversationTrigger === 'toolbar' ? 'toolbar' : 'navigation';
    setSidebarMode('conversation');
  }, []);

  const closeConversation = React.useCallback(() => {
    const source = conversationReturnFocusRef.current ?? 'navigation';
    setSidebarMode('itinerary');
    window.requestAnimationFrame(() => {
      const trigger = [...document.querySelectorAll<HTMLElement>('[data-conversation-trigger]')]
        .find((node) => node.dataset.conversationTrigger === source && node.offsetParent !== null);
      trigger?.focus();
      conversationReturnFocusRef.current = null;
    });
  }, []);

  const entities = React.useMemo(() => bundle ? buildEntityIndex(bundle) : new Map<string, TimelineEntity>(), [bundle]);
  const daySummaries = React.useMemo(() => bundle ? selectDaySummaries(bundle) : [], [bundle]);
  const daySummaryById = React.useMemo(() => new Map(daySummaries.map((summary) => [summary.dayId, summary])), [daySummaries]);
  const daysByEntity = React.useMemo(() => {
    const map = new Map<string, Set<number>>();
    for (const day of itinerary?.day_plans ?? []) {
      for (const entry of day.timeline) {
        const days = map.get(entry.entity_id) ?? new Set<number>();
        days.add(day.day);
        map.set(entry.entity_id, days);
      }
    }
    return map;
  }, [itinerary]);
  const waypointOrder = React.useMemo<ReadonlyMap<string, WaypointPlacement>>(() => (
    bundle ? buildWaypointOrder(bundle.workspace.itinerary, locatedBundlePlaceIds(bundle)) : new Map()
  ), [bundle]);

  const todayISO = React.useMemo(() => localDateISO(), []);
  const todayDay = React.useMemo(() => {
    const days = itinerary?.day_plans ?? [];
    return days.find((day) => day.date === todayISO)?.day ?? days[0]?.day ?? 1;
  }, [itinerary, todayISO]);
  const actualToday = Boolean(itinerary?.day_plans.some((day) => day.day === todayDay && day.date === todayISO));
  const displayedDay = view === 'today' ? todayDay : activeDay;
  const conversationOpen = sidebarMode === 'conversation' && !state.currentTripRunReadOnly && view === 'interactive_itinerary';
  const contentMode: WorkspaceScene['mode'] = conversationOpen ? 'conversation' : view === 'today' ? 'today' : 'cards';
  const contentScene = React.useMemo<WorkspaceScene>(() => ({ mode: contentMode, day: activeDay }), [activeDay, contentMode]);
  const previousSceneRef = React.useRef<WorkspaceScene>(contentScene);
  const sceneTransition = resolveWorkspaceSceneTransition(previousSceneRef.current, contentScene);
  React.useLayoutEffect(() => {
    previousSceneRef.current = contentScene;
  }, [contentScene]);

  React.useEffect(() => {
    setActiveDay(null);
    setSidebarMode('itinerary');
    setSelectedEntityId(null);
    setSelectedOccurrenceKey(null);
    setLinkedEntityId(null);
    setLayersOpen(false);
    setShowRoutes(true);
    setHiddenLayers([]);
    overviewScrollTop.current = 0;
    returnFocusDayId.current = null;
  }, [state.currentTripRunId]);

  React.useEffect(() => {
    const outsideDisplayedDay = (id: string | null) => (
      id != null && displayedDay != null && !daysByEntity.get(id)?.has(displayedDay)
    );
    if (outsideDisplayedDay(selectedEntityId)) {
      setSelectedEntityId(null);
      setSelectedOccurrenceKey(null);
    }
    if (outsideDisplayedDay(linkedEntityId)) setLinkedEntityId(null);
  }, [daysByEntity, displayedDay, linkedEntityId, selectedEntityId]);

  React.useEffect(() => {
    if (state.currentTripRunReadOnly) setSidebarMode('itinerary');
  }, [state.currentTripRunReadOnly]);

  React.useEffect(() => {
    if (!selectedEntityId) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closePlaceDetail();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [closePlaceDetail, selectedEntityId]);

  const registerDayCard = React.useCallback((dayId: string, node: HTMLButtonElement | null) => {
    if (node) summaryCardRefs.current.set(dayId, node);
    else summaryCardRefs.current.delete(dayId);
  }, []);

  const openDay = React.useCallback((summary: DaySummaryVM) => {
    overviewScrollTop.current = navigationScrollRef.current?.scrollTop ?? 0;
    returnFocusDayId.current = summary.dayId;
    setSidebarMode('itinerary');
    setActiveDay(summary.day);
  }, []);

  const restoreOverview = React.useCallback(() => {
    setSidebarMode('itinerary');
    setActiveDay(null);
  }, []);

  const selectDay = React.useCallback((day: number | null) => {
    if (day == null) {
      restoreOverview();
      return;
    }
    const summary = daySummaries.find((candidate) => candidate.day === day);
    if (summary) openDay(summary);
  }, [daySummaries, openDay, restoreOverview]);

  React.useEffect(() => {
    if (contentMode === 'cards') contentScrollRef.current?.scrollTo({ top: 0 });
  }, [activeDay, contentMode]);

  React.useEffect(() => {
    if (activeDay != null || !returnFocusDayId.current) return;
    const dayId = returnFocusDayId.current;
    window.requestAnimationFrame(() => {
      navigationScrollRef.current?.scrollTo({ top: overviewScrollTop.current });
      summaryCardRefs.current.get(dayId)?.focus();
      returnFocusDayId.current = null;
    });
  }, [activeDay]);

  const mappedPlaces = React.useMemo<BundleMapPlace[]>(() => {
    if (!bundle) return identity ? identityPlaces(identity) : [];
    return buildBundleMapPlaces(bundle, waypointOrder);
  }, [bundle, identity, waypointOrder]);
  const projectedRoutes = React.useMemo(() => bundle?.map_projection.content.routes ?? [], [bundle]);
  const visiblePlaces = React.useMemo(() => mappedPlaces.filter((place) => (
    !hiddenLayers.includes(place.entity_ref.entity_type as PlaceLayer)
    && (displayedDay == null || place.days.includes(displayedDay))
  )), [displayedDay, hiddenLayers, mappedPlaces]);
  const visibleRoutes = React.useMemo(() => {
    if (!showRoutes) return [];
    return projectedRoutes.filter((route) => displayedDay == null || daysByEntity.get(route.entity_ref.entity_id)?.has(displayedDay));
  }, [daysByEntity, displayedDay, projectedRoutes, showRoutes]);
  const drawableRouteIds = React.useMemo(() => new Set(
    projectedRoutes.filter(routeIsDrawable).map((route) => route.entity_ref.entity_id),
  ), [projectedRoutes]);

  const hasMapData = mappedPlaces.some(isLocatedBundleMapPlace)
    || projectedRoutes.some(routeIsDrawable);
  const hasVisibleData = visiblePlaces.some(isLocatedBundleMapPlace)
    || visibleRoutes.some(routeIsDrawable);
  const selectedEntity = selectedEntityId ? entities.get(selectedEntityId) ?? null : null;
  const selectedDay = itinerary?.day_plans.find((day) => day.day === displayedDay) ?? null;
  const selectedSummary = selectedDay ? daySummaryById.get(selectedDay.day_id) ?? null : null;
  const selectedTimeline = React.useMemo(() => (
    bundle && selectedDay ? selectDayTimeline(bundle, selectedDay.day_id) : []
  ), [bundle, selectedDay]);
  const nextNode = selectedTimeline.find((node) => node.role === 'place') ?? selectedTimeline[0] ?? null;
  const reportDocument = bundle ? selectCurrentReportDocument(bundle) : null;
  const daysToRender = activeDay == null ? itinerary?.day_plans ?? [] : selectedDay ? [selectedDay] : [];

  const identityTitle = identity
    ? `${identity.destinations.map((place) => place.name).join('＋')} ${tripDays(identity) || bundle?.workspace.itinerary.duration_days || ''} 日`
    : null;
  const title = identityTitle ?? bundle?.workspace.itinerary.title ?? '我的旅行';
  const dateLabel = bundle
    ? daySummaries.length > 0
      ? [daySummaries[0].dateLabel, daySummaries[daySummaries.length - 1].dateLabel].filter(Boolean).join(' — ')
      : null
    : identity ? `${identity.start_date} — ${identity.end_date}` : null;

  const handleCardSelect = React.useCallback((selection: CardMapSelection) => {
    if (selection.entityType === 'transport_leg') setShowRoutes(true);
    if (PLACE_LAYERS.some((layer) => layer.id === selection.entityType)) {
      setHiddenLayers((layers) => layers.filter((layer) => layer !== selection.entityType));
    }
    if (activeDay != null && activeDay !== selection.day) setActiveDay(selection.day);
    placeReturnFocusRef.current = null;
    setSelectedOccurrenceKey(selection.occurrenceKey);
    setSelectedEntityId(selection.entityId);
    setLinkedEntityId(null);
    if (isMobile) dispatch({ type: 'SET_MOBILE_CANVAS_OPEN', payload: false });
  }, [activeDay, dispatch, isMobile]);

  const handleMapSelect = React.useCallback((id: string) => {
    if (id === selectedEntityId) {
      closePlaceDetail();
      return;
    }
    placeReturnFocusRef.current = null;
    setSelectedOccurrenceKey(null);
    setSelectedEntityId(id);
  }, [closePlaceDetail, selectedEntityId]);

  const openReading = React.useCallback(() => {
    dispatch({ type: 'SET_DELIVERABLE_VIEW', payload: 'full_report' });
    dispatch({ type: 'SET_MOBILE_CANVAS_OPEN', payload: false });
  }, [dispatch]);

  const toggleToday = React.useCallback(() => {
    setSidebarMode('itinerary');
    dispatch({ type: 'SET_DELIVERABLE_VIEW', payload: view === 'today' ? 'interactive_itinerary' : 'today' });
  }, [dispatch, view]);

  const navigation = (
    <aside className="journey-sidebar journey-navigation" aria-label={view === 'today' ? '旅中今天安排' : '旅行导航'}>
      {!bundle ? <GenerationJourneyPanel /> : (
        <>
          <header className="journey-sidebar-header">
            <button type="button" className="journey-back-trips" onClick={() => dispatch({ type: 'SET_ACTIVE_VIEW', payload: 'trips' })}><ArrowLeft size={14} />我的行程</button>
            <div className="journey-title-row">
              <h1>{title}</h1>
              {state.currentTripRunReadOnly && <span>历史结果 · 只读</span>}
            </div>
            {dateLabel && <p>{dateLabel}</p>}
            <div className="journey-view-actions">
              <button type="button" className="journey-view-action" onClick={openReading}><BookOpen size={14} />阅读版</button>
              <PdfDownloadButton bundle={bundle} compact />
              <button type="button" className={cn('journey-view-action', view === 'today' && 'is-active')} onClick={toggleToday}><Sun size={14} />{view === 'today' ? '返回全程' : '旅中查看'}</button>
              {isMobile && view === 'interactive_itinerary' && !state.currentTripRunReadOnly && !conversationOpen && (
                <button type="button" data-conversation-trigger="navigation" className="journey-view-action" onClick={openConversation}><MessageCircle size={14} />调整</button>
              )}
            </div>
          </header>

          {isMobile ? (
            <div className="journey-mobile-day-nav"><MapDayNav days={bundle.workspace.itinerary.day_plans} activeDay={activeDay} onSelect={selectDay} /></div>
          ) : (
            <div ref={navigationScrollRef} className="journey-sidebar-scroll journey-navigation-scroll">
              <button type="button" className={cn('journey-all-days', activeDay == null && 'is-active')} aria-pressed={activeDay == null} onClick={restoreOverview}>
                <span>全程行程</span><span>{bundle.workspace.itinerary.duration_days} 天</span>
              </button>
              <TripOverview
                itinerary={bundle.workspace.itinerary}
                summaries={daySummaries}
                costCoverageStatement={formatTripCostSummary(bundle.report_projection.document?.cost_summary)}
                importantNotes={[]}
                onOpenDay={openDay}
                registerDayCard={registerDayCard}
                showHeader={false}
                compact
                activeDay={activeDay}
              />
            </div>
          )}

          {view === 'interactive_itinerary' && !state.currentTripRunReadOnly && !conversationOpen && !isMobile && (
            <button type="button" data-conversation-trigger="navigation" className="journey-adjust-entry" onClick={openConversation}>
              <MessageCircle size={16} /><span>告诉我想怎么改……</span><ArrowRight size={15} />
            </button>
          )}
          {state.currentTripRunReadOnly && <div className="journey-readonly-footer">这份生成记录仅供查看</div>}
        </>
      )}
    </aside>
  );

  const contentBody = conversationOpen ? (
    <div className="journey-conversation-view" onKeyDown={(event) => { if (event.key === 'Escape') closeConversation(); }}>
      <header>
        <button type="button" onClick={closeConversation}><ArrowLeft size={14} />返回日程</button>
        <h2>调整这趟旅行</h2>
        <p>告诉我你的想法，日程和地图会一起更新。</p>
      </header>
      <ConversationThread embedded />
    </div>
  ) : !reportDocument ? (
    <div className="journey-report-pending" role={bundle?.report_projection.status === 'failed' ? 'alert' : 'status'}>
      <CalendarDays size={24} />
      <h2>{bundle?.report_projection.status === 'failed' ? '行程暂时无法加载' : '行程正在同步到最新结果'}</h2>
    </div>
  ) : view === 'today' && selectedDay ? (
    <div className="today-companion-panel">
      <header>
        <p>{actualToday ? '今天' : '行程预览'} · {selectedSummary?.dateLabel ?? `第 ${todayDay} 天`}</p>
        <h2>{selectedSummary?.destinationLabel ?? selectedDay.theme}</h2>
        <span>{selectedDay.theme}</span>
      </header>
      <TodayNextCard node={nextNode} actualToday={actualToday} />
      <DayTimeline nodes={selectedTimeline} waypointOrder={waypointOrder} linkedEntityId={linkedEntityId} onLinkEntity={setLinkedEntityId} />
      {selectedDay.estimated_cost_cny != null && <footer>当日约 <strong>¥{selectedDay.estimated_cost_cny.toLocaleString('zh-CN')}</strong></footer>}
    </div>
  ) : bundle ? (
    <>
      {activeDay != null && <button type="button" data-testid="day-overview-back" onClick={restoreOverview} className="journey-back-overview"><ArrowLeft size={15} />返回全程</button>}
      <ItineraryCardFlow
        bundle={bundle}
        days={daysToRender}
        summaries={daySummaries}
        entities={entities}
        waypointOrder={waypointOrder}
        drawableRouteIds={drawableRouteIds}
        linkedEntityId={linkedEntityId}
        selectedEntityId={selectedEntityId}
        selectedOccurrenceKey={selectedOccurrenceKey}
        onLinkEntity={setLinkedEntityId}
        onSelectEntity={handleCardSelect}
      />
    </>
  ) : null;

  const content = bundle && (
    <section className="journey-content" aria-label={conversationOpen ? '调整旅行会话' : '行程卡片'}>
      <header className="journey-content-toolbar">
        <div><span>当前行程</span><strong>{title}</strong></div>
        <div>
          <button type="button" aria-label="阅读版" onClick={openReading}><BookOpen size={15} /></button>
          <PdfDownloadButton bundle={bundle} compact />
          <button type="button" aria-label={view === 'today' ? '返回全程' : '旅中查看'} onClick={toggleToday}><Sun size={15} /></button>
          {view === 'interactive_itinerary' && !state.currentTripRunReadOnly && <button type="button" data-conversation-trigger="toolbar" aria-label="调整这趟旅行" onClick={openConversation}><MessageCircle size={15} /></button>}
        </div>
      </header>
      <div className="journey-content-viewport">
        <AnimatePresence mode="popLayout" initial={false} custom={sceneTransition}>
          <PresenceFrame
            key={contentMode === 'cards' ? `cards-${activeDay ?? 'all'}` : contentMode}
            className="journey-content-scene"
            custom={sceneTransition}
            variants={contentSceneVariants}
            initial="enter"
            animate="visible"
            exit="exit"
          >
            <div ref={contentScrollRef} className="journey-content-scroll" data-testid="interactive-itinerary">
              {contentBody}
            </div>
          </PresenceFrame>
        </AnimatePresence>
      </div>
    </section>
  );

  const mapRegion = (
    <div className="journey-map-region" data-testid="itinerary-map-region">
      {hasMapData ? (
        <BundleMapLeafletLazy
          places={visiblePlaces}
          routes={visibleRoutes}
          selectedEntityId={selectedEntityId}
          onSelectEntity={handleMapSelect}
          linkedEntityId={linkedEntityId}
          onLinkEntity={setLinkedEntityId}
        />
      ) : (
        <div className="journey-map-empty"><MapIcon size={28} /><p>已确认的地点会显示在这里</p></div>
      )}
      {hasMapData && !hasVisibleData && <div className="journey-map-empty is-floating"><MapIcon size={20} /><p>这一天暂无可定位的地点或路线</p></div>}

      <div className="journey-map-top-controls">
        {bundle && view === 'interactive_itinerary' && <MapDayNav days={bundle.workspace.itinerary.day_plans} activeDay={activeDay} onSelect={selectDay} />}
        {bundle && (
          <div className="journey-layer-control">
            <button type="button" aria-expanded={layersOpen} onClick={() => setLayersOpen((open) => !open)}><Layers3 size={15} />图层<ChevronDown size={13} className={cn('transition-transform', layersOpen && 'rotate-180')} /></button>
            <AnimatePresence>
              {layersOpen && (
                <PresenceFrame
                  className="journey-layer-popover"
                  style={{ transformOrigin: 'top right' }}
                  initial={{ opacity: 0, y: -4, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1, transition: { duration: duration.base, ease: easing.decelerate } }}
                  exit={{ opacity: 0, y: -4, scale: 0.98, transition: { duration: duration.fast, ease: easing.accelerate } }}
                  onKeyDown={(event) => { if (event.key === 'Escape') setLayersOpen(false); }}
                >
                  <h2>地图图层</h2>
                  <label><input type="checkbox" checked={showRoutes} onChange={(event) => setShowRoutes(event.target.checked)} />旅行路线</label>
                  {PLACE_LAYERS.map((layer) => (
                    <label key={layer.id}><input type="checkbox" checked={!hiddenLayers.includes(layer.id)} onChange={() => setHiddenLayers((items) => items.includes(layer.id) ? items.filter((item) => item !== layer.id) : [...items, layer.id])} />{layer.label}</label>
                  ))}
                </PresenceFrame>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>

      <AnimatePresence mode="sync" initial={false} onExitComplete={restorePlaceFocus}>
        {bundle && selectedEntity && (
          <PresenceSection
            key={selectedEntityId}
            className="journey-place-detail"
            data-testid="map-place-detail"
            aria-label="地图地点详情"
            style={{ transformOrigin: 'bottom left' }}
            initial={{ opacity: 0, y: 8, scale: 0.99 }}
            animate={{ opacity: 1, y: 0, scale: 1, transition: { duration: duration.page, ease: easing.decelerate } }}
            exit={{ opacity: 0, y: 6, scale: 0.99, transition: { duration: duration.fast, ease: easing.accelerate } }}
          >
            <button type="button" aria-label="关闭地点详情" onClick={closePlaceDetail}><X size={16} /></button>
            <TimelineEntityDetails bundle={bundle} entity={selectedEntity} />
          </PresenceSection>
        )}
      </AnimatePresence>

      {isMobile && bundle && (
        <button
          type="button"
          data-testid="canvas-pill"
          aria-hidden={state.mobileCanvasOpen || undefined}
          tabIndex={state.mobileCanvasOpen ? -1 : 0}
          className={cn('journey-mobile-schedule transition-opacity duration-fast ease-standard', state.mobileCanvasOpen && 'pointer-events-none opacity-0')}
          onClick={() => dispatch({ type: 'SET_MOBILE_CANVAS_OPEN', payload: true })}
        >
          <BookOpen size={16} />{view === 'today' ? '查看今天安排' : activeDay == null ? '查看旅行日程' : `查看第 ${activeDay} 天日程`}
        </button>
      )}
    </div>
  );

  return (
    <CanvasMotion>
      <section className="delivery-workspace-shell">
        <div
          ref={(node) => node?.toggleAttribute('inert', showReading)}
          aria-hidden={showReading || undefined}
          className="delivery-interactive-layer"
        >
            <PresenceSection
              className={cn('delivery-workspace', !bundle && 'is-generating', state.planApprovalGate && 'is-reviewing', view === 'today' && 'is-today')}
              aria-label="旅行地图工作区"
            >
              {(!isMobile || !bundle) && navigation}
              {!isMobile && content}
              {(!isMobile || bundle) && mapRegion}
              {isMobile && bundle && (
                <Sheet open={state.mobileCanvasOpen} onClose={() => dispatch({ type: 'SET_MOBILE_CANVAS_OPEN', payload: false })} testId="canvas-sheet">
                  <div className="journey-mobile-panels">{navigation}{content}</div>
                </Sheet>
              )}
            </PresenceSection>
        </div>
        <AnimatePresence initial={false}>
          {showReading && bundle && (
            <PresenceFrame className="journey-reading-layer" variants={readingLayerVariants} initial="enter" animate="visible" exit="exit">
              <ReadingWorkspace bundle={bundle} />
            </PresenceFrame>
          )}
        </AnimatePresence>
      </section>
    </CanvasMotion>
  );
};
