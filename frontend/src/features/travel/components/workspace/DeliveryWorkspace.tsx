import { AnimatePresence, useReducedMotion } from 'motion/react';
import type { Variants } from 'motion/react';
import { ArrowLeft, BookOpen, CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Layers3, Map as MapIcon, MessageCircle, Sun, X } from 'lucide-react';
import { useApp } from '../../../../app/state/AppContext';
import { useIsMobileViewport } from '../../../../hooks/useMediaQuery';
import { CanvasMotion } from '../../../../components/ui/CanvasMotion';
import { PresenceFrame, PresenceSection } from '../../../../components/ui/PresenceSurface';
import { ConversationThread } from '../../../chat/components/ConversationThread';
import { buildWaypointOrder, type WaypointPlacement } from '../../model/waypointOrder';
import { buildBundleMapPlaces, isLocatedBundleMapPlace, locatedBundlePlaceIds, type BundleMapPlace } from '../../model/mapPlaces';
import { selectCurrentReportDocument, selectDaySummaries, selectDayTimeline, type DaySummaryVM, type DayTimelineNodeVM } from '../../model/itineraryPresentation';
import { resolveWorkspaceSceneTransition, type WorkspaceScene } from '../../model/workspaceTransition';
import { formatTripCostSummary } from '../../model/costPresentation';
import { routeLines } from '../../model/mapModel';
import { tripSegments, unresolvedForDay } from '../../model/itineraryNavigation';
import { type ControlledTripIdentity } from '../../types/planner';
import { type PublicDeliveryBundle } from '../../types/delivery';
import { type PublicWeatherAdjustment } from '../../types/weather';
import { type MapProjection } from '../../types/report';
import { BundleMapLeafletLazy } from './BundleMapLeafletLazy';
import { DayTimeline } from './DayTimeline';
import { TripOverview } from './TripOverview';
import { WeatherSuggestions } from './WeatherSuggestions';
import { FullReportView, PdfDownloadButton } from './FullReportView';
import { GenerationJourneyPanel } from './GenerationJourneyPanel';
import { TripRouteNav } from './TripRouteNav';
import { DeliveryMobileSheet } from './DeliveryMobileSheet';
import { UnresolvedReadout } from './UnresolvedReadout';
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

function MapDayNav({ days, activeDay, onSelect, showOverview = true, compact = false }: {
  days: DayPlan[];
  activeDay: number | null;
  onSelect: (day: number | null) => void;
  showOverview?: boolean;
  compact?: boolean;
}) {
  if (compact) {
    const index = days.findIndex((day) => day.day === activeDay);
    return (
      <nav data-testid="itinerary-day-nav" aria-label="按天查看行程" className="journey-day-nav is-compact">
        <button type="button" aria-label="前一天" disabled={index <= 0} onClick={() => onSelect(days[index - 1].day)}><ChevronLeft size={15} /></button>
        <select aria-label="选择行程日期" value={activeDay ?? ''} onChange={(event) => onSelect(Number(event.target.value))}>
          {days.map((day) => <option key={day.day_id} value={day.day}>第 {day.day} 天</option>)}
        </select>
        <button type="button" aria-label="后一天" disabled={index < 0 || index >= days.length - 1} onClick={() => onSelect(days[index + 1].day)}><ChevronRight size={15} /></button>
      </nav>
    );
  }
  return (
    <nav data-testid="itinerary-day-nav" aria-label="按天查看行程" className="journey-day-nav">
      {showOverview && <button type="button" aria-pressed={activeDay == null} onClick={() => onSelect(null)} className={cn(activeDay == null && 'is-active')}>全程</button>}
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
          : <div className="reading-pending" role={bundle.report_projection.status === 'failed' ? 'alert' : 'status'}><BookOpen size={25} /><h1>{bundle.report_projection.status === 'failed' ? '阅读版暂时无法加载' : '阅读版正在整理'}</h1><p>地图与日程已经可以查看。</p></div>}
      </div>
    </section>
  );
}

export const DeliveryWorkspace: React.FC<DeliveryWorkspaceProps> = ({ bundle }) => {
  const { state, dispatch } = useApp();
  const isMobile = useIsMobileViewport();
  const reducedMotion = useReducedMotion();
  const [activeDay, setActiveDay] = React.useState<number | null>(null);
  const [activeSegmentId, setActiveSegmentId] = React.useState<string | null>(null);
  const [sidebarMode, setSidebarMode] = React.useState<'itinerary' | 'conversation'>('itinerary');
  const [conversationDraft, setConversationDraft] = React.useState('');
  const [conversationRunId, setConversationRunId] = React.useState<string | null>(null);
  const [selectedEntityId, setSelectedEntityId] = React.useState<string | null>(null);
  const [selectedOccurrenceKey, setSelectedOccurrenceKey] = React.useState<string | null>(null);
  const [linkedEntityId, setLinkedEntityId] = React.useState<string | null>(null);
  const [layersOpen, setLayersOpen] = React.useState(false);
  const [showRoutes, setShowRoutes] = React.useState(true);
  const [hiddenLayers, setHiddenLayers] = React.useState<PlaceLayer[]>([]);
  const placeReturnFocusRef = React.useRef<{ entityId: string; occurrenceKey: string | null } | null>(null);
  const conversationReturnFocusRef = React.useRef<string | null>(null);
  const contentScrollRef = React.useRef<HTMLDivElement>(null);
  const floatingPanelRef = React.useRef<HTMLDivElement>(null);
  const [panelOffset, setPanelOffset] = React.useState(0);
  const [mapBottomOffset, setMapBottomOffset] = React.useState(0);
  const mapRegionRef = React.useRef<HTMLDivElement>(null);
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
    conversationReturnFocusRef.current = event.currentTarget.dataset.conversationTrigger ?? 'navigation';
    setConversationDraft('');
    setConversationRunId(null);
    setSidebarMode('conversation');
  }, []);

  const discussWeather = React.useCallback((suggestion: PublicWeatherAdjustment, event: React.MouseEvent<HTMLButtonElement>) => {
    conversationReturnFocusRef.current = event.currentTarget.dataset.conversationTrigger ?? 'navigation';
    setConversationDraft(`请根据 ${suggestion.date} 的天气建议调整行程：${suggestion.summary}。请结合最新天气和当天安排重新规划受影响的部分。`);
    setConversationRunId(bundle?.manifest.run_id ?? null);
    dispatch({ type: 'SET_DELIVERABLE_VIEW', payload: 'interactive_itinerary' });
    setSidebarMode('conversation');
  }, [bundle?.manifest.run_id, dispatch]);

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

  const closeMobileSheet = React.useCallback(() => {
    dispatch({ type: 'SET_MOBILE_CANVAS_OPEN', payload: false });
    window.requestAnimationFrame(() => document.querySelector<HTMLElement>('[data-testid="canvas-pill"]')?.focus({ preventScroll: true }));
  }, [dispatch]);

  const entities = React.useMemo(() => bundle ? buildEntityIndex(bundle) : new Map<string, TimelineEntity>(), [bundle]);
  const daySummaries = React.useMemo(() => bundle ? selectDaySummaries(bundle) : [], [bundle]);
  const segments = React.useMemo(() => tripSegments(daySummaries), [daySummaries]);
  const activeSegment = segments.find((segment) => segment.id === activeSegmentId) ?? null;
  const overviewSummaries = activeSegment?.days ?? daySummaries;
  const segmentDays = React.useMemo(() => activeSegment ? new Set(activeSegment.days.map((day) => day.day)) : null, [activeSegment]);
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

  React.useLayoutEffect(() => {
    if (!bundle || isMobile) {
      setPanelOffset(0);
      return;
    }
    const panel = floatingPanelRef.current;
    if (!panel) return;
    const update = () => {
      const next = Math.round(panel.getBoundingClientRect().right + 20);
      setPanelOffset((current) => current === next ? current : next);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(panel);
    window.addEventListener('resize', update);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', update);
    };
  }, [bundle, isMobile]);

  React.useLayoutEffect(() => {
    const region = mapRegionRef.current;
    if (!isMobile || !state.mobileCanvasOpen || !region) { setMapBottomOffset(0); return; }
    const update = () => setMapBottomOffset(Math.round(region.clientHeight * .55));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(region);
    return () => observer.disconnect();
  }, [isMobile, state.mobileCanvasOpen]);

  React.useEffect(() => {
    setActiveDay(null);
    setActiveSegmentId(null);
    setSidebarMode('itinerary');
    setSelectedEntityId(null);
    setSelectedOccurrenceKey(null);
    setLinkedEntityId(null);
    setLayersOpen(false);
    setShowRoutes(true);
    setHiddenLayers([]);
    overviewScrollTop.current = 0;
    returnFocusDayId.current = null;
  }, [state.currentSessionId, bundle?.manifest.run_id]);

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
    overviewScrollTop.current = contentScrollRef.current?.scrollTop ?? 0;
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
      contentScrollRef.current?.scrollTo({ top: overviewScrollTop.current });
      summaryCardRefs.current.get(dayId)?.focus();
      returnFocusDayId.current = null;
    });
  }, [activeDay]);

  const mappedPlaces = React.useMemo<BundleMapPlace[]>(() => {
    if (!bundle) return [];
    return buildBundleMapPlaces(bundle, waypointOrder);
  }, [bundle, waypointOrder]);
  const projectedRoutes = React.useMemo(() => bundle?.map_projection.content.routes ?? [], [bundle]);
  const visiblePlaces = React.useMemo(() => mappedPlaces.filter((place) => (
    !hiddenLayers.includes(place.entity_ref.entity_type as PlaceLayer)
    && (displayedDay == null || place.days.includes(displayedDay))
    && (displayedDay != null || !segmentDays || place.days.some((day) => segmentDays.has(day)))
  )), [displayedDay, hiddenLayers, mappedPlaces, segmentDays]);
  const visibleRoutes = React.useMemo(() => {
    if (!showRoutes) return [];
    return projectedRoutes.filter((route) => {
      const days = daysByEntity.get(route.entity_ref.entity_id);
      return displayedDay != null ? days?.has(displayedDay) : !segmentDays || [...(days ?? [])].some((day) => segmentDays.has(day));
    });
  }, [daysByEntity, displayedDay, projectedRoutes, segmentDays, showRoutes]);
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

  const identityTitle = identity?.destinations.length
    ? `${identity.destinations.map((place) => place.name).join('＋')} ${tripDays(identity) || bundle?.workspace.itinerary.duration_days || ''} 日`
    : null;
  const title = bundle?.workspace.itinerary.title ?? identityTitle ?? '我的旅行';
  const dateRange = bundle
    ? daySummaries.length > 0
      ? [daySummaries[0].dateLabel, daySummaries[daySummaries.length - 1].dateLabel].filter(Boolean).join(' — ')
      : null
    : identity?.start_date && identity.end_date ? `${identity.start_date} — ${identity.end_date}` : null;
  const dateLabel = dateRange && identity?.dates_assumed ? `${dateRange}（暂定）` : dateRange;
  const metaLabel = bundle
    ? [
      identity?.destinations.map((place) => place.name).join('＋'),
      `${bundle.workspace.itinerary.duration_days} 天`,
      dateLabel,
    ].filter(Boolean).join(' · ')
    : dateLabel;

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
    if (isMobile) dispatch({ type: 'SET_MOBILE_CANVAS_OPEN', payload: false });
  }, [closePlaceDetail, dispatch, isMobile, selectedEntityId]);

  const openReading = React.useCallback(() => {
    dispatch({ type: 'SET_DELIVERABLE_VIEW', payload: 'full_report' });
    dispatch({ type: 'SET_MOBILE_CANVAS_OPEN', payload: false });
  }, [dispatch]);

  const toggleToday = React.useCallback(() => {
    setSidebarMode('itinerary');
    dispatch({ type: 'SET_DELIVERABLE_VIEW', payload: view === 'today' ? 'interactive_itinerary' : 'today' });
  }, [dispatch, view]);

  const selectSegment = (segmentId: string | null) => {
    setActiveSegmentId(segmentId);
    setSidebarMode('itinerary');
    setActiveDay(null);
    setSelectedEntityId(null);
    setSelectedOccurrenceKey(null);
    setLinkedEntityId(null);
    overviewScrollTop.current = 0;
    returnFocusDayId.current = null;
    contentScrollRef.current?.scrollTo({ top: 0 });
  };

  const navigation = bundle && (
    <aside className="journey-sidebar journey-navigation" aria-label={view === 'today' ? '旅中今天安排' : '旅行导航'}>
      <header className="journey-sidebar-header">
        <button type="button" className="journey-back-trips" onClick={() => dispatch({ type: 'SET_ACTIVE_VIEW', payload: 'trips' })}><ArrowLeft size={14} />我的行程</button>
        <div className="journey-title-row">
          <h1 title={title}>{title}</h1>
          {state.currentTripRunReadOnly && <span>历史结果 · 只读</span>}
        </div>
        {metaLabel && <p>{metaLabel}</p>}
        <div className="journey-view-actions">
          <button type="button" className="journey-view-action" onClick={openReading}><BookOpen size={14} />阅读版</button>
          <button type="button" className={cn('journey-view-action', view === 'today' && 'is-active')} onClick={toggleToday}><Sun size={14} />{view === 'today' ? '返回全程' : '旅中查看'}</button>
          {view === 'interactive_itinerary' && !state.currentTripRunReadOnly && !conversationOpen && (
            <button type="button" data-conversation-trigger="navigation" className="journey-view-action" onClick={openConversation}><MessageCircle size={14} />调整</button>
          )}
        </div>
      </header>
    </aside>
  );

  const contentBody = conversationOpen ? (
    <div className="journey-conversation-view" onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); closeConversation(); } }}>
      <header>
        <button type="button" onClick={closeConversation}><ArrowLeft size={14} />返回日程</button>
        <h2>调整这趟旅行</h2>
      </header>
      {(state.planApprovalGate || state.understandingQuestions) ? <GenerationJourneyPanel /> : (
        <ConversationThread
          key={state.conversationEpoch}
          embedded
          initialInput={conversationDraft}
          targetRunId={conversationRunId}
          onInputSent={() => setConversationDraft('')}
        />
      )}
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
      <WeatherSuggestions suggestions={bundle?.workspace.weather_adjustments.filter((item) => item.date === selectedDay.date) ?? []} readOnly={state.currentTripRunReadOnly} onDiscuss={discussWeather} />
      <TodayNextCard node={nextNode} actualToday={actualToday} />
      <UnresolvedReadout items={bundle && selectedDay ? unresolvedForDay(bundle, selectedDay.day_id) : []} />
      <DayTimeline nodes={selectedTimeline} waypointOrder={waypointOrder} linkedEntityId={linkedEntityId} onLinkEntity={setLinkedEntityId} />
      {selectedDay.estimated_cost_cny != null && <footer>当日约 <strong>¥{selectedDay.estimated_cost_cny.toLocaleString('zh-CN')}</strong></footer>}
    </div>
  ) : bundle ? (
    <>
      <WeatherSuggestions suggestions={bundle.workspace.weather_adjustments.filter((item) => activeDay == null || item.date === selectedDay?.date)} readOnly={state.currentTripRunReadOnly} onDiscuss={discussWeather} />
      {activeDay == null && (
        <TripOverview
          itinerary={bundle.workspace.itinerary}
          summaries={overviewSummaries}
          costCoverageStatement={formatTripCostSummary(bundle.report_projection.document?.cost_summary)}
          onOpenDay={openDay}
          registerDayCard={registerDayCard}
          showHeader={false}
          compact
          activeDay={activeDay}
        />
      )}
      {activeDay == null && <UnresolvedReadout items={bundle.workspace.itinerary.unresolved} all />}
      {activeDay != null && (
        <div className="journey-day-navigation">
          <button type="button" data-testid="day-overview-back" onClick={restoreOverview} className="journey-back-overview"><ArrowLeft size={15} />返回全程</button>
          <MapDayNav days={itinerary?.day_plans ?? []} activeDay={activeDay} onSelect={selectDay} showOverview={false} compact={isMobile} />
        </div>
      )}
      {activeDay != null && <ItineraryCardFlow
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
      />}
    </>
  ) : null;

  const content = bundle && (
    <section className="journey-content" aria-label={conversationOpen ? '调整旅行会话' : '行程卡片'}>
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
    <div ref={mapRegionRef} className="journey-map-region" data-testid="itinerary-map-region">
      {hasMapData ? (
        <BundleMapLeafletLazy
          places={visiblePlaces}
          routes={visibleRoutes}
          selectedEntityId={selectedEntityId}
          onSelectEntity={handleMapSelect}
          linkedEntityId={linkedEntityId}
          onLinkEntity={setLinkedEntityId}
          overlayOffset={isMobile ? 0 : panelOffset}
          bottomOffset={isMobile ? mapBottomOffset : view === 'today' ? 0 : 96}
        />
      ) : (
        <div className="journey-map-empty"><MapIcon size={28} /><p>这趟行程暂无可定位的地点或路线</p></div>
      )}
      {hasMapData && !hasVisibleData && <div className="journey-map-empty is-floating"><MapIcon size={20} /><p>当前范围暂无可定位的地点或路线</p></div>}

      <div className="journey-map-top-controls">
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

      {bundle && view === 'interactive_itinerary' && (
        <TripRouteNav segments={segments} activeSegmentId={activeDay == null ? activeSegmentId : segments.find((segment) => segment.days.some((day) => day.day === activeDay))?.id ?? null} onSelect={selectSegment} />
      )}
      {isMobile && !state.mobileCanvasOpen && state.currentTripRunReadOnly && <span className="journey-readonly-map-label">历史结果 · 只读</span>}

      <AnimatePresence mode="wait" initial={false} onExitComplete={restorePlaceFocus}>
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
              className={cn('delivery-workspace', !bundle && 'is-generating', view === 'today' && 'is-today', activeDay == null && !conversationOpen && view !== 'today' && 'is-overview', (activeDay != null || conversationOpen || view === 'today') && 'is-detail')}
              style={{ '--journey-map-overlay': `${panelOffset}px` } as React.CSSProperties}
              aria-label="旅行地图工作区"
            >
              {bundle
                ? mapRegion
                : state.currentTripRunId
                  ? <div className="generation-workspace"><GenerationJourneyPanel /></div>
                  : <div className="generation-workspace generation-workspace-conversation"><ConversationThread key={state.conversationEpoch} embedded /></div>}
              {bundle && !isMobile && <PresenceFrame ref={floatingPanelRef} className="journey-floating-panel" initial={{ opacity: 0, x: reducedMotion ? 0 : -18 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: reducedMotion ? 0 : duration.page, ease: easing.decelerate }}>{navigation}{content}</PresenceFrame>}
              {isMobile && bundle && (
                <DeliveryMobileSheet open={state.mobileCanvasOpen} onClose={closeMobileSheet}>
                  {navigation}{content}
                </DeliveryMobileSheet>
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
