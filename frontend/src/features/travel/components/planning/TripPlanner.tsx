import { m, useReducedMotion } from 'motion/react';
import { ArrowRight, Minus, Plus, Users } from 'lucide-react';
import { getTripPlannerConfiguration } from '../../api/planner';
import { getDefaultOrigin, setDefaultOrigin } from '../../../settings/api/defaultOrigin';
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
import { DateRangePicker } from './DateRangePicker';
import { PlaceField } from './PlaceField';
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
const VISIBLE_PRIMARY_STYLES = 4;
const NATURAL_DETAILS = ['轻松一点', '当地美食', '人文体验', '爸妈同行'] as const;

function parseTripBudget(raw: string): { value: number | null; error: string | null } {
  const normalized = raw.replace(/[,，\s]/g, '');
  if (!normalized) return { value: null, error: null };
  const value = Number(normalized);
  if (!Number.isFinite(value) || value <= 0) {
    return { value: null, error: '总预算请输入大于 0 的金额' };
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
  const naturalPanelRef = React.useRef<HTMLDivElement>(null);
  const structuredPanelRef = React.useRef<HTMLDivElement>(null);
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
  const [naturalText, setNaturalText] = React.useState(guidedText);
  const [originReady, setOriginReady] = React.useState<boolean | null>(null);
  const [originSetup, setOriginSetup] = React.useState<PlaceIdentity | null>(null);
  const [error, setError] = React.useState('');
  const [destinationAddOpen, setDestinationAddOpen] = React.useState(false);
  const confirmedDestinations = destinations.filter((place): place is PlaceIdentity => Boolean(place)).length;
  const destinationCollapsed = confirmedDestinations > 0
    && confirmedDestinations < MAX_DESTINATIONS
    && !destinationAddOpen;
  const handleDestinationAddState = React.useCallback((state: DestinationAddState) => {
    setDestinationAddOpen(state === 'open');
  }, []);

  const focusNaturalInput = React.useCallback(() => {
    const input = naturalInputRef.current;
    if (!input) return;
    input.focus({ preventScroll: true });
    input.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'nearest', inline: 'nearest' });
  }, [reducedMotion]);

  React.useEffect(() => {
    naturalPanelRef.current?.toggleAttribute('inert', mode !== 'natural');
    structuredPanelRef.current?.toggleAttribute('inert', mode !== 'structured');
  }, [mode]);

  React.useEffect(() => {
    if (!inspiration) return;
    inspirationModeRef.current = modeRef.current;
    setNaturalText(inspiration.text);
    setError('');
    if (modeRef.current === 'structured') return;
    setMode('natural');
    const frame = window.requestAnimationFrame(focusNaturalInput);
    return () => window.cancelAnimationFrame(frame);
  }, [focusNaturalInput, inspiration]);

  React.useEffect(() => {
    if (
      !inspiration
      || inspirationModeRef.current !== 'structured'
      || !config
      || originReady === null
      || appliedStructuredInspirationRef.current === inspiration.id
    ) return;
    appliedStructuredInspirationRef.current = inspiration.id;
    const { scene } = inspiration;
    setOrigin(scene.origin);
    setOriginReady(true);
    setDestinations([...scene.destinations]);
    setDestinationQueries(scene.destinations.map((place) => place.name));
    setAdults(scene.adults);
    setChildren(0);
    setElderly(false);
    setPrimary(scene.primary);
    setPrimaryTouched(true);
    setInterests([]);
    setBudget(`${scene.budgetCny}`);
    if (startDate) setEndDate(endDateForDuration(startDate, scene.days));
    setError('');
    if (mode === 'structured') {
      window.requestAnimationFrame(() => {
        const planner = plannerRef.current;
        planner?.querySelector<HTMLButtonElement>('[data-testid="date-range-trigger"]')?.focus({ preventScroll: true });
        planner?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'nearest', inline: 'nearest' });
      });
    }
  }, [config, inspiration, mode, originReady, reducedMotion, startDate]);

  const extracted = React.useMemo(
    () => (config ? factsFromNaturalText(guidedText, config) : null),
    [config, guidedText],
  );

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
      if (!active) return;
      setOrigin(extracted?.origin ? null : place);
      setOriginReady(Boolean(place));
    }).catch(() => {
      if (active) setOriginReady(false);
    });
    return () => {
      active = false;
    };
  }, [extracted?.origin]);

  const submitStructured = async () => {
    setError('');
    const selectedDestinations = destinations.filter((item): item is PlaceIdentity => Boolean(item));
    if (!origin && selectedDestinations.length === 0 && !startDate && !guidedText.trim()) {
      setError('先填一点想法或条件，再开始规划。');
      return;
    }
    const parsedBudget = parseTripBudget(budget);
    if (parsedBudget.error) {
      setError(parsedBudget.error);
      return;
    }
    const identityComplete = Boolean(origin && selectedDestinations.length > 0 && startDate && endDate);
    const identity: ControlledTripIdentity | null = identityComplete && origin
      ? {
        origin,
        destinations: selectedDestinations,
        start_date: startDate!,
        end_date: endDate!,
        party: { adults, children, elderly_companions: elderly, accessibility_required: false },
        style: { primary, secondary_interests: interests, source: primaryTouched ? 'current' : 'suggested' },
      }
      : null;
    const numericBudget = parsedBudget.value;
    const facts: string[] = [];
    if (origin) facts.push(`出发地：${origin.name}`);
    if (selectedDestinations.length > 0) facts.push(`目的地：${selectedDestinations.map((item) => item.name).join('、')}`);
    if (startDate && endDate) facts.push(`日期：${startDate} 至 ${endDate}`);
    facts.push(`同行：${adults} 位成人${children ? `、${children} 位儿童` : ''}${elderly ? '、长辈同行' : ''}`);
    facts.push(`风格：${primary}${interests.length ? `（${interests.join('、')}）` : ''}`);
    if (numericBudget !== null) facts.push(`总预算约 ${numericBudget.toLocaleString('zh-CN')} 元`);
    const summary = [guidedText.trim(), `按条件规划——${facts.join('；')}`].filter(Boolean).join('\n');
    onHomePlanSubmitted?.();
    await sendMessage(summary, {
      route: 'trip_planning',
      ...(identity ? { controlledTripIdentity: identity } : {}),
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
      assistantPendingLabel: '正在理解你的旅行想法',
    });
  };

  const appendNaturalDetail = (detail: string) => {
    setNaturalText((current) => {
      const text = current.trim();
      if (!text) return `${detail}。`;
      if (text.includes(detail)) return current;
      return `${text}${/[。！？!?；;]$/.test(text) ? '' : '，'}${detail}`;
    });
    naturalInputRef.current?.focus({ preventScroll: true });
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

  if (configError) {
    return (
      <section className={cn('planner-card', compact && 'planner-card-compact')} aria-label="旅行规划卡">
        {tabs}
        <div
          className="planner-config-state"
          role="tabpanel"
          id={`${tabsId}-${mode}-panel`}
          aria-labelledby={`${tabsId}-${mode}-tab`}
        >
          <RequestFailureNotice
            title="暂时无法开始规划"
            failure={configError}
            onRetry={() => void loadConfiguration()}
            className="planner-config-notice"
          />
          <p className="planner-config-note">重试不会清空已经填写的内容</p>
        </div>
      </section>
    );
  }

  if (!config || !extracted) {
    return (
      <section className={cn('planner-card', compact && 'planner-card-compact')} aria-label="旅行规划卡">
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
      aria-label="旅行规划卡"
    >
      <div className="planner-standard-flow">
        {compact ? <p className="planner-compact-label">确认旅行信息</p> : tabs}
        <div className="planner-panels">
          <m.div
            role="tabpanel"
            id={`${tabsId}-natural-panel`}
            aria-labelledby={`${tabsId}-natural-tab`}
            ref={naturalPanelRef}
            aria-hidden={mode !== 'natural'}
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
                  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                    event.preventDefault();
                    void submitNatural();
                  }
                }}
                rows={4}
                placeholder={`例如：${config.inspiration_prompts[0] ?? '国庆假期想从北京去成都和重庆，7 天，轻松一点，喜欢城市文化和地方美食。'}`}
              />
              <span className="planner-character-count">{naturalText.length}/500</span>
            </div>
            <div className="planner-natural-tools">
              <section aria-labelledby={`${tabsId}-natural-details`}>
                <p id={`${tabsId}-natural-details`} className="planner-natural-label">补充偏好</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {NATURAL_DETAILS.map((detail) => (
                    <button
                      key={detail}
                      type="button"
                      className="planner-natural-chip"
                      onClick={() => appendNaturalDetail(detail)}
                    >
                      <Plus size={12} aria-hidden />{detail}
                    </button>
                  ))}
                </div>
              </section>
              {config.inspiration_prompts.length > 0 && (
                <section className="planner-natural-starters" aria-labelledby={`${tabsId}-natural-starters`}>
                  <p id={`${tabsId}-natural-starters`} className="planner-natural-label">也可以从一个想法开始</p>
                  <div className="mt-1.5 grid gap-1.5 sm:grid-cols-2">
                    {config.inspiration_prompts.slice(0, 2).map((prompt) => (
                      <button
                        key={prompt}
                        type="button"
                        className="planner-natural-starter"
                        onClick={() => {
                          setNaturalText(prompt);
                          naturalInputRef.current?.focus({ preventScroll: true });
                        }}
                      >
                        {prompt}
                      </button>
                    ))}
                  </div>
                </section>
              )}
            </div>
          </m.div>
          <m.div
            role="tabpanel"
            id={`${tabsId}-structured-panel`}
            aria-labelledby={`${tabsId}-structured-tab`}
            ref={structuredPanelRef}
            aria-hidden={mode !== 'structured'}
            className={cn(
              'planner-panel planner-panel-structured',
              mode === 'structured' ? 'is-active' : 'is-inactive',
              destinationCollapsed && 'is-destination-collapsed',
            )}
            initial={false}
            animate={{ opacity: mode === 'structured' ? 1 : 0, y: mode === 'structured' ? 0 : 4 }}
            transition={{ duration: reducedMotion ? 0 : duration.base, ease: easing.decelerate }}
          >
            {originReady === null ? (
              <div className="flex flex-col gap-4" aria-label="正在读取常用出发地">
                <Skeleton radius="label" className="h-11 w-full" />
                <Skeleton radius="label" className="h-11 w-full" />
              </div>
            ) : !originReady ? (
              <section aria-labelledby="origin-setup-title" className="planner-origin-setup">
                <p className="planner-field-label">先从熟悉的地方出发</p>
                <h2 id="origin-setup-title" className="mt-1 font-display text-xl font-semibold text-ink">选择你的常用出发地</h2>
                <p className="mt-1 text-[13px] text-ink-secondary">之后可以在「我的偏好」里改。</p>
                <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-end">
                  <PlaceField role="origin" value={originSetup} onChange={setOriginSetup} label="常用出发地" />
                  <Button
                    variant="secondary"
                    className="flex-shrink-0"
                    disabled={!originSetup}
                    onClick={async () => {
                      if (!originSetup) return;
                      const saved = await setDefaultOrigin(originSetup);
                      setOrigin(saved);
                      setOriginReady(true);
                    }}
                  >保存并继续</Button>
                </div>
                <button type="button" onClick={() => { setOrigin(null); setOriginReady(true); }} className="mt-4 min-h-9 text-[13px] font-medium text-ink-secondary underline-offset-4 hover:text-ink hover:underline">暂时不用默认值</button>
              </section>
            ) : (
              <>
                <div className="planner-route-fields">
                  <PlaceField role="origin" value={origin} onChange={setOrigin} label="从哪里出发" frequent={!extracted.origin} initialQuery={extracted.origin} />
                  <ArrowRight className="planner-route-arrow" size={16} aria-hidden />
                  <div className="planner-destination-field-wrap">
                    <span className="planner-field-label">去哪里</span>
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

                <div className="planner-form-grid">
                  <DateRangePicker
                    start={startDate}
                    end={endDate}
                    hideLabel
                    onChange={(nextStart, nextEnd) => { setStartDate(nextStart); setEndDate(nextEnd); setError(''); }}
                  />
                  <div className="planner-party" role="group" aria-label={`同行人数：${adults} 位成人，${children} 位儿童`}>
                    <Users size={16} className="shrink-0 text-accent" aria-hidden />
                    {([['成人', adults, setAdults, 1], ['儿童', children, setChildren, 0]] as const).map(([label, value, setter, min]) => (
                      <div key={label} className="flex items-center gap-0.5">
                        <span className="mr-0.5 text-[11px] text-ink-secondary">{label}</span>
                        <button type="button" aria-label={`减少${label}`} disabled={value <= min} onClick={() => setter(value - 1)} className="planner-stepper"><Minus size={12} /></button>
                        <span className="w-4 text-center font-mono text-[13px] tabular-nums">{value}</span>
                        <button type="button" aria-label={`增加${label}`} onClick={() => setter(value + 1)} className="planner-stepper"><Plus size={12} /></button>
                      </div>
                    ))}
                  </div>
                  <div className="planner-budget-field">
                    <label htmlFor="planner-budget" className="sr-only">预算（可选）</label>
                    <div className="planner-budget-input">
                      <span aria-hidden>¥</span>
                      <input id="planner-budget" inputMode="decimal" type="text" value={budget} onChange={(event) => setBudget(event.target.value)} placeholder="预算（可选）" aria-label="预算（可选）" />
                      <span aria-hidden>元</span>
                    </div>
                  </div>
                </div>

                <div className="planner-preference-block">
                  <div className="planner-preference-row">
                    <div className="planner-style-field">
                      <span className="planner-field-label">旅行偏好</span>
                      <div className="planner-style-options" role="group" aria-label="旅行风格">
                        {config.primary_styles.slice(0, VISIBLE_PRIMARY_STYLES).map((style) => (
                          <button key={style.id} type="button" aria-pressed={primary === style.label} onClick={() => { setPrimary(style.label); setPrimaryTouched(true); }} className={cn(CHIP, primary === style.label ? CHIP_ON : CHIP_OFF)}>{style.label}</button>
                        ))}
                        <button type="button" aria-expanded={more} className="planner-more-preferences" onClick={() => setMore(!more)}>更多偏好</button>
                      </div>
                    </div>
                  </div>
                  {more && (
                    <div className="planner-more-preferences-options">
                      {config.primary_styles.slice(VISIBLE_PRIMARY_STYLES).map((style) => (
                        <button key={style.id} type="button" aria-pressed={primary === style.label} onClick={() => { setPrimary(style.label); setPrimaryTouched(true); }} className={cn(CHIP, primary === style.label ? CHIP_ON : CHIP_OFF)}>{style.label}</button>
                      ))}
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
        {(mode === 'natural' || originReady === true) && (
          <div className="planner-action-area">
            {error && <p className="planner-error" role="alert">{error}</p>}
            <Button
              size="lg"
              className="planner-main-action"
              disabled={state.isStreaming || (mode === 'natural' && !naturalText.trim())}
              onClick={() => { if (mode === 'natural') void submitNatural(); else void submitStructured(); }}
            >
              开始规划 <ArrowRight size={17} aria-hidden />
            </Button>
          </div>
        )}
        {homeFlowActive && (homeError || homePendingLabel) && (
          <div className={cn('planner-home-flow-status', homeError && 'is-error')} role={homeError ? 'alert' : 'status'} aria-live="polite">
            {homeError ? (
              <>
                <strong>这次还没有开始规划</strong>
                <span>{homeError}</span>
                <small>修改上面的内容后可以再次开始规划。</small>
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
