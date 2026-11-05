import { m, useReducedMotion } from 'motion/react';
import { ArrowRight, ChevronDown } from 'lucide-react';
import { getTripPlannerConfiguration } from '../../api/planner';
import { getDefaultOrigin } from '../../../settings/api/defaultOrigin';
import { describeRequestFailure, type RequestFailure } from '../../../../lib/requestFailureMessage';
import { RequestFailureNotice } from '../../../../components/ui/RequestFailureNotice';
import { SegmentedTabs, type SegmentedTab } from '../../../../components/ui/SegmentedTabs';
import { cn } from '../../../../lib/utils';
import { duration, easing } from '../../../../lib/motion';
import { type ControlledTripIdentity, type PlaceIdentity, type TripPlannerConfiguration } from '../../types/planner';
import { Button } from '../../../../components/ui/Button';
import { Skeleton } from '../../../../components/ui/Skeleton';
import { useApp } from '../../../../app/state/AppContext';
import { useSendMessage } from '../../../../app/session/useSendMessage';
import { ActivePresetContext } from '../../../presets/components/ActivePresetContext';
import { DateRangePicker } from './DateRangePicker';
import { PlaceField } from './PlaceField';
import { TravelerPicker } from './TravelerPicker';
import { DestinationTokenField, MAX_DESTINATIONS, type DestinationAddState } from './DestinationTokenField';
import type { AtlasScene } from './TravelAtlasScenes';
import React from 'react';

type PlannerMode = 'natural' | 'structured';

export interface PlannerInspiration {
  id: number;
  text: string;
  scene: AtlasScene;
}

const PLANNER_TABS: ReadonlyArray<SegmentedTab<PlannerMode>> = [
  { id: 'natural', label: '一句话规划', testId: 'planner-natural-tab' },
  { id: 'structured', label: '按条件规划', testId: 'planner-structured-tab' },
];

const CHIP = 'min-h-10 rounded-label border border-transparent px-2.5 text-[13px] transition-colors duration-fast ease-standard';
const CHIP_ON = 'border-accent/20 bg-accent-soft font-medium text-accent';
const CHIP_OFF = 'bg-surface/70 text-ink-secondary hover:bg-accent-soft/60 hover:text-ink';

function parseTripBudget(raw: string): { value: number | null; error: string | null } {
  const normalized = raw.replace(/[,，\s]/g, '');
  if (!normalized) return { value: null, error: null };
  const value = Number(normalized);
  if (!Number.isFinite(value) || value <= 0) {
    return { value: null, error: '金额无效' };
  }
  return { value, error: null };
}

function factsFromNaturalText(text: string, config: TripPlannerConfiguration) {
  const origin = text.match(/从([^，,。\s]{2,12})(?:出发|走)/)?.[1] || '';
  const destination = text.match(/(?:去|前往)([^，,。\s]{2,12}?)(?:旅行|旅游|玩|待|住|，|,|。|$)/)?.[1] || '';
  const exactDates = text.match(/(20\d{2}-\d{2}-\d{2}).*?(20\d{2}-\d{2}-\d{2})/);
  const adultMatch = text.match(/(\d+)\s*(?:位|个)?成人/);
  const childMatch = text.match(/(\d+)\s*(?:位|个)?(?:儿童|孩子|小孩)/);
  const hasChild = /孩子|小孩|宝宝|亲子/.test(text);
  const elderly = /爸妈|父母|老人|长辈/.test(text);
  const fallback = config.primary_styles.find((option) => option.is_default)!;
  const inferred = config.primary_styles.find((option) => option.inference_keywords.some((keyword) => text.includes(keyword)));
  return {
    origin,
    destination,
    start: exactDates?.[1] || '',
    end: exactDates?.[2] || '',
    adults: Number(adultMatch?.[1] || config.default_adults),
    children: Number(childMatch?.[1] || (hasChild ? Math.max(1, config.default_children) : config.default_children)),
    elderly,
    primary: inferred?.label || fallback.label,
  } as const;
}

function endDateForDuration(start: string, days: number): string {
  if (!start) return '';
  const date = new Date(`${start}T00:00:00`);
  date.setDate(date.getDate() + days - 1);
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

export const TripPlanner: React.FC<{
  guidedText?: string;
  compact?: boolean;
  initialDestinations?: PlaceIdentity[];
  inspiration?: PlannerInspiration | null;

  homeFlowActive?: boolean;
  homePendingLabel?: string;
  homeError?: string;
  onHomePlanSubmitted?: () => void;
}> = ({
  guidedText = '',
  compact = false,
  initialDestinations = [],
  inspiration = null,
  homeFlowActive = false,
  homePendingLabel = '',
  homeError = '',
  onHomePlanSubmitted,
}) => {
  const { state } = useApp();
  const { sendMessage } = useSendMessage();
  const reducedMotion = useReducedMotion();
  const naturalInputRef = React.useRef<HTMLTextAreaElement>(null);
  const budgetInputRef = React.useRef<HTMLInputElement>(null);
  const originTouchedRef = React.useRef(false);
  const plannerRef = React.useRef<HTMLElement>(null);
  const [mode, setMode] = React.useState<PlannerMode>(compact ? 'structured' : 'natural');
  const modeRef = React.useRef(mode);
  modeRef.current = mode;
  const inspirationModeRef = React.useRef<PlannerMode>(mode);
  const appliedStructuredInspirationRef = React.useRef<number | null>(null);
  const tabsId = React.useId();
  const [config, setConfig] = React.useState<TripPlannerConfiguration | null>(null);
  const [configError, setConfigError] = React.useState<RequestFailure | null>(null);
  const [origin, setOrigin] = React.useState<PlaceIdentity | null>(null);
  const [originQuery, setOriginQuery] = React.useState<string | null>(null);
  const initialDestinationValues = initialDestinations.slice(0, MAX_DESTINATIONS);
  const [destinations, setDestinations] = React.useState<Array<PlaceIdentity | null>>(
    initialDestinationValues.length ? initialDestinationValues : [null],
  );
  const [destinationQueries, setDestinationQueries] = React.useState<string[]>(
    initialDestinationValues.length ? initialDestinationValues.map((place) => place.name) : [''],
  );
  const [startDate, setStartDate] = React.useState('');
  const [endDate, setEndDate] = React.useState('');
  const [adults, setAdults] = React.useState(0);
  const [children, setChildren] = React.useState(0);
  const [elderly, setElderly] = React.useState(false);
  const [primary, setPrimary] = React.useState('');
  const [primaryTouched, setPrimaryTouched] = React.useState(false);
  const [interests, setInterests] = React.useState<string[]>([]);
  const [more, setMore] = React.useState(false);
  const [budget, setBudget] = React.useState('');
  const [budgetInvalid, setBudgetInvalid] = React.useState(false);
  const [naturalText, setNaturalText] = React.useState(guidedText);
  const [error, setError] = React.useState('');
  const [destinationAddOpen, setDestinationAddOpen] = React.useState(false);
  const confirmedDestinations = destinations.filter((place): place is PlaceIdentity => Boolean(place)).length;
  const destinationCollapsed = confirmedDestinations > 0
    && confirmedDestinations < MAX_DESTINATIONS
    && !destinationAddOpen;
  const handleDestinationAddState = React.useCallback((state: DestinationAddState) => {
    setDestinationAddOpen(state === 'open');
  }, []);

  const resizeNaturalInput = React.useCallback(() => {
    const input = naturalInputRef.current;
    if (!input || modeRef.current !== 'natural' || input.clientWidth === 0) return;
    input.style.height = 'auto';
    input.style.height = `${input.scrollHeight}px`;
  }, []);

  React.useLayoutEffect(() => {
    resizeNaturalInput();
  }, [mode, naturalText, resizeNaturalInput]);

  React.useLayoutEffect(() => {
    const input = naturalInputRef.current;
    if (mode !== 'natural' || !input) return undefined;
    let previousWidth = 0;
    let frame = 0;
    const observer = new ResizeObserver(([entry]) => {
      const width = entry.contentRect.width;
      if (width === 0 || width === previousWidth) return;
      previousWidth = width;
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(resizeNaturalInput);
    });
    observer.observe(input);
    document.fonts.addEventListener('loadingdone', resizeNaturalInput);
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(frame);
      document.fonts.removeEventListener('loadingdone', resizeNaturalInput);
    };
  }, [mode, resizeNaturalInput]);

  const focusNaturalInput = React.useCallback(() => {
    const input = naturalInputRef.current;
    if (!input) return;
    input.focus({ preventScroll: true });
    input.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'nearest', inline: 'nearest' });
  }, [reducedMotion]);

  React.useEffect(() => {
    if (!inspiration) return;
    inspirationModeRef.current = modeRef.current;
    setError('');
    if (modeRef.current === 'structured') return;
    setNaturalText(inspiration.text);
    const frame = window.requestAnimationFrame(focusNaturalInput);
    return () => window.cancelAnimationFrame(frame);
  }, [focusNaturalInput, inspiration]);

  React.useEffect(() => {
    if (
      !inspiration
      || inspirationModeRef.current !== 'structured'
      || !config
      || appliedStructuredInspirationRef.current === inspiration.id
    ) return;
    appliedStructuredInspirationRef.current = inspiration.id;
    const { scene } = inspiration;
    originTouchedRef.current = true;
    setOrigin(scene.origin);
    setOriginQuery(null);
    setDestinations([...scene.destinations]);
    setDestinationQueries(scene.destinations.map((place) => place.name));
    setAdults(scene.adults);
    setChildren(0);
    setElderly(false);
    setPrimary(scene.primary);
    setPrimaryTouched(true);
    setInterests([]);
    setBudget(`${scene.budgetCny}`);
    setBudgetInvalid(false);
    if (startDate) setEndDate(endDateForDuration(startDate, scene.days));
    setError('');
    if (mode === 'structured') {
      window.requestAnimationFrame(() => {
        const planner = plannerRef.current;
        planner?.querySelector<HTMLButtonElement>('[data-testid="date-range-trigger"]')?.focus({ preventScroll: true });
        planner?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'nearest', inline: 'nearest' });
      });
    }
  }, [config, inspiration, mode, reducedMotion, startDate]);

  const extracted = React.useMemo(
    () => (config ? factsFromNaturalText(guidedText, config) : null),
    [config, guidedText],
  );
  const hasStructuredInput = Boolean(origin || (originQuery ?? extracted?.origin ?? '').trim()
    || confirmedDestinations || destinationQueries.some((query) => query.trim()) || startDate || guidedText.trim());

  const loadConfiguration = React.useCallback(async () => {
    setConfigError(null);
    try {
      const next = await getTripPlannerConfiguration();
      setConfig(next);
      const facts = factsFromNaturalText(guidedText, next);
      setStartDate(facts.start);
      setEndDate(facts.end);
      setAdults(facts.adults);
      setChildren(facts.children);
      setElderly(facts.elderly || next.default_elderly_companions);
      setPrimary(facts.primary);
    } catch (reason) {
      setConfigError(describeRequestFailure(reason, '读取', '旅行规划选项'));
    }
  }, [guidedText]);

  React.useEffect(() => {
    void loadConfiguration();
  }, [loadConfiguration]);

  React.useEffect(() => {
    let active = true;
    getDefaultOrigin().then((place) => {
      if (active && !originTouchedRef.current && !extracted?.origin) setOrigin(place);
    }).catch(() => {});
    return () => {
      active = false;
    };
  }, [extracted?.origin]);

  const submitStructured = async () => {
    setError('');
    const selectedDestinations = destinations.filter((item): item is PlaceIdentity => Boolean(item));
    const pendingDestinations = destinationQueries.slice(selectedDestinations.length).map((item) => item.trim()).filter(Boolean);
    const pendingOrigin = !origin ? (originQuery ?? extracted?.origin ?? '').trim() : '';
    if (!origin && !pendingOrigin && selectedDestinations.length === 0 && pendingDestinations.length === 0 && !startDate && !guidedText.trim()) {
      setError('先填一点想法或条件，再开始规划。');
      return;
    }
    const parsedBudget = parseTripBudget(budget);
    if (parsedBudget.error) {
      setBudgetInvalid(true);
      budgetInputRef.current?.focus();
      return;
    }
    const identity: ControlledTripIdentity = {
      origin,
      destinations: selectedDestinations,
      start_date: startDate || null,
      end_date: endDate || null,
      dates_assumed: false,
      party: { total: adults ? adults + children : null, adults: adults || null, children, elderly_companions: elderly, accessibility_required: null },
      style: primaryTouched || interests.length > 0
        ? { primary, secondary_interests: interests, source: primaryTouched ? 'current' : 'suggested' }
        : null,
    };
    const numericBudget = parsedBudget.value;
    const facts: string[] = [];
    if (origin) facts.push(`出发地：${origin.name}`);
    else if (pendingOrigin) facts.push(`出发地（待核实）：${pendingOrigin}`);
    if (selectedDestinations.length > 0) facts.push(`目的地：${selectedDestinations.map((item) => item.name).join('、')}`);
    if (pendingDestinations.length > 0) facts.push(`目的地（待核实）：${pendingDestinations.join('、')}`);
    if (startDate && endDate) facts.push(`日期：${startDate} 至 ${endDate}`);
    else if (startDate) facts.push(`开始日期：${startDate}`);
    else if (endDate) facts.push(`结束日期：${endDate}`);
    if (adults) facts.push(`同行：${adults} 位成人${children ? `、${children} 位儿童` : ''}${elderly ? '、长辈同行' : ''}`);
    if (primaryTouched) facts.push(`风格：${primary}${interests.length ? `（${interests.join('、')}）` : ''}`);
    else if (interests.length) facts.push(`兴趣：${interests.join('、')}`);
    if (numericBudget !== null) facts.push(`总预算约 ${numericBudget.toLocaleString('zh-CN')} 元`);
    const summary = [guidedText.trim(), `按条件规划——${facts.join('；')}`].filter(Boolean).join('\n');
    onHomePlanSubmitted?.();
    await sendMessage(summary, {
      route: 'trip_planning',
      newTrip: true,
      controlledTripIdentity: identity,
      assistantPendingLabel: '正在整理旅行信息',
    });
  };

  const submitNatural = async () => {
    const text = naturalText.trim();
    if (!text || state.isStreaming) return;
    setError('');
    onHomePlanSubmitted?.();
    // 不指定路径：普通问题走轻量回答，规划想法由模型判断后进入工作台理解。
    await sendMessage(text, {
      newTrip: true,
      assistantPendingLabel: '正在理解你的旅行想法',
    });
  };

  const plannerTabs = React.useMemo(() => PLANNER_TABS.map((tab) => ({
    ...tab,
    domId: `${tabsId}-${tab.id}-tab`,
    panelId: `${tabsId}-${tab.id}-panel`,
  })), [tabsId]);

  const tabs = (
    <SegmentedTabs
      aria-label="旅行规划方式"
      tabs={plannerTabs}
      value={mode}
      onChange={(next) => {
        setMode(next);
        setError('');
      }}
      className="planner-mode-tabs"
    />
  );

  if (mode === 'structured' && configError) {
    return (
      <section className={cn('planner-card', compact && 'planner-card-compact')} data-mode={mode} aria-label="旅行规划卡">
        {tabs}
        <div
          className="planner-config-state"
          role="tabpanel"
          id={`${tabsId}-${mode}-panel`}
          aria-labelledby={`${tabsId}-${mode}-tab`}
        >
          <RequestFailureNotice
            title="暂时读不到规划选项"
            failure={configError}
            onRetry={() => void loadConfiguration()}
            className="planner-config-notice"
          />
        </div>
      </section>
    );
  }

  if (mode === 'structured' && (!config || !extracted)) {
    return (
      <section className={cn('planner-card', compact && 'planner-card-compact')} data-mode={mode} aria-label="旅行规划卡">
        {tabs}
        <div
          className="planner-config-state"
          role="tabpanel"
          id={`${tabsId}-${mode}-panel`}
          aria-labelledby={`${tabsId}-${mode}-tab`}
          aria-label="正在读取旅行规划配置"
        >
          <div className="planner-loading-content">
            {[0, 1, 2].map((row) => (
              <div key={row} className="flex flex-col gap-2">
                <Skeleton radius="label" className="h-3 w-20" />
                <Skeleton radius="label" className="h-11 w-full" />
              </div>
            ))}
          </div>
        </div>
      </section>
    );
  }

  return (
    <m.section
      ref={plannerRef}
      layout={homeFlowActive && !reducedMotion}
      className={cn('planner-card', compact && 'planner-card-compact')}
      data-mode={mode}
      aria-label="旅行规划卡"
    >
      <div className="planner-standard-flow">
        {compact ? <p className="planner-compact-label">确认旅行信息</p> : tabs}
        {!compact && <ActivePresetContext />}
        <div className="planner-panels">
          <m.div
            role="tabpanel"
            id={`${tabsId}-natural-panel`}
            aria-labelledby={`${tabsId}-natural-tab`}
            hidden={mode !== 'natural'}
            className={cn('planner-panel planner-panel-natural', mode === 'natural' ? 'is-active' : 'is-inactive')}
            initial={false}
            animate={{ opacity: mode === 'natural' ? 1 : 0, y: mode === 'natural' ? 0 : -4 }}
            transition={{ duration: reducedMotion ? 0 : duration.base, ease: easing.decelerate }}
          >
            <div className="planner-natural-input">
              <textarea
                ref={naturalInputRef}
                id="natural-trip-brief"
                data-testid="natural-trip-input"
                aria-label="一句话描述旅行"
                value={naturalText}
                maxLength={500}
                onChange={(event) => setNaturalText(event.target.value)}
                onKeyDown={(event) => {
                  if (!event.nativeEvent.isComposing && (event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                    event.preventDefault();
                    void submitNatural();
                  }
                }}
                rows={3}
                disabled={state.isStreaming}
                placeholder="从北京去成都和重庆，7 天，轻松一点。"
              />
              {naturalText.length >= 400 && <span className="planner-character-count">{naturalText.length}/500</span>}
            </div>
          </m.div>
          <m.div
            role="tabpanel"
            id={`${tabsId}-structured-panel`}
            aria-labelledby={`${tabsId}-structured-tab`}
            hidden={mode !== 'structured'}
            className={cn(
              'planner-panel planner-panel-structured',
              mode === 'structured' ? 'is-active' : 'is-inactive',
              destinationCollapsed && 'is-destination-collapsed',
            )}
            initial={false}
            animate={{ opacity: mode === 'structured' ? 1 : 0, y: mode === 'structured' ? 0 : 4 }}
            transition={{ duration: reducedMotion ? 0 : duration.base, ease: easing.decelerate }}
          >
            {config && extracted && (
              <>
                <div className="planner-route-fields">
                  <PlaceField role="origin" value={origin} onChange={(place) => { originTouchedRef.current = true; setOrigin(place); }} onQueryChange={(query) => { originTouchedRef.current = true; setOriginQuery(query); }} label="出发地" initialQuery={extracted.origin} />
                  <div className="planner-destination-field-wrap">
                    <span className="planner-field-label">目的地</span>
                    <DestinationTokenField
                      values={destinations}
                      queries={destinationQueries}
                      onAddStateChange={handleDestinationAddState}
                      onChange={(nextValues, nextQueries) => {
                        setDestinations(nextValues);
                        setDestinationQueries(nextQueries);
                        setError('');
                      }}
                    />
                  </div>
                </div>

                <div className="planner-condition-fields">
                  <div className="planner-date-field">
                    <span className="planner-field-label">日期</span>
                    <DateRangePicker
                      start={startDate}
                      end={endDate}
                      hideLabel
                      condensed
                      onChange={(nextStart, nextEnd) => { setStartDate(nextStart); setEndDate(nextEnd); setError(''); }}
                    />
                  </div>
                  <TravelerPicker adults={adults} childrenCount={children} onChange={(nextAdults, nextChildren) => { setAdults(nextAdults); setChildren(nextChildren); }} />
                  <div className={cn('planner-budget-field', budgetInvalid && 'is-invalid')}>
                    <label htmlFor="planner-budget" className="planner-field-label">总预算 <span className="planner-optional">可选</span></label>
                    <div className="planner-budget-input">
                      <span aria-hidden>¥</span>
                      <input
                        ref={budgetInputRef}
                        id="planner-budget"
                        inputMode="decimal"
                        type="text"
                        value={budget}
                        onChange={(event) => { setBudget(event.target.value); setBudgetInvalid(false); }}
                        onBlur={() => setBudgetInvalid(Boolean(parseTripBudget(budget).error))}
                        placeholder="不限"
                        aria-label="预算（可选）"
                        aria-invalid={budgetInvalid || undefined}
                        aria-describedby={budgetInvalid ? 'planner-budget-error' : undefined}
                      />
                    </div>
                    {budgetInvalid && <span id="planner-budget-error" className="planner-field-error" role="alert">金额无效</span>}
                  </div>
                  <div className="planner-style-field">
                    <label htmlFor="planner-style" className="planner-field-label">旅行风格</label>
                    <div className="planner-select-control">
                      <select id="planner-style" aria-label="旅行风格" value={primary} onChange={(event) => { setPrimary(event.target.value); setPrimaryTouched(true); }}>
                        {config.primary_styles.map((style) => <option key={style.id} value={style.label}>{style.label}</option>)}
                      </select>
                      <ChevronDown size={15} aria-hidden />
                    </div>
                  </div>
                </div>

                <div className="planner-preference-block">
                  <button type="button" aria-expanded={more} className="planner-more-preferences" onClick={() => setMore(!more)}>更多偏好 <ChevronDown size={13} aria-hidden /></button>
                  {more && (
                    <div className="planner-more-preferences-options">
                      <button type="button" aria-pressed={elderly} onClick={() => setElderly(!elderly)} className={cn(CHIP, elderly ? CHIP_ON : CHIP_OFF)}>长辈同行</button>
                      {config.secondary_interests.map((interest) => (
                        <button key={interest.id} type="button" aria-pressed={interests.includes(interest.label)} disabled={!interests.includes(interest.label) && interests.length >= config.max_secondary_interests} onClick={() => setInterests((items) => items.includes(interest.label) ? items.filter((item) => item !== interest.label) : [...items, interest.label])} className={cn(CHIP, interests.includes(interest.label) ? CHIP_ON : CHIP_OFF, 'disabled:opacity-40')}>{interest.label}</button>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </m.div>
        </div>
        {(mode === 'natural' || Boolean(config && extracted)) && (
          <div className="planner-action-area">
            {error && <p className="planner-error" role="alert">{error}</p>}
            <Button
              size="lg"
              className="planner-main-action"
              disabled={state.isStreaming || (mode === 'natural' ? !naturalText.trim() : !hasStructuredInput)}
              onClick={() => { if (mode === 'natural') void submitNatural(); else void submitStructured(); }}
            >
              {state.isStreaming ? '正在整理…' : '开始规划'} <ArrowRight size={17} aria-hidden />
            </Button>
          </div>
        )}
        {homeFlowActive && (homeError || homePendingLabel) && (
          <div className={cn('planner-home-flow-status', homeError && 'is-error')} role={homeError ? 'alert' : 'status'} aria-live="polite">
            {homeError ? (
              <>
                <strong>这次还没有开始规划</strong>
                <span>{homeError}</span>
              </>
            ) : (
              <>
                <span className="planner-pending-dot" aria-hidden />
                <span>{homePendingLabel || '正在理解你的旅行想法'}</span>
              </>
            )}
          </div>
        )}
      </div>
    </m.section>
  );
};
