import { m, useReducedMotion } from 'motion/react';
import { ArrowDown, ArrowRight, ArrowUp, MapPin, Minus, Plus, Users, X } from 'lucide-react';
import { getTripPlannerConfiguration } from '../../api/planner';
import { getDefaultOrigin, setDefaultOrigin } from '../../../settings/api/defaultOrigin';
import { createPlaceSearchRunner, type PlaceSearchCandidate } from '../../model/placeSearch';
import { describeRequestFailure, type RequestFailure } from '../../../../lib/requestFailureMessage';
import { RequestFailureNotice } from '../../../../components/ui/RequestFailureNotice';
import { SegmentedTabs, type SegmentedTab } from '../../../../components/ui/SegmentedTabs';
import { cn } from '../../../../lib/utils';
import { duration, easing } from '../../../../lib/motion';
import { type ControlledTripIdentity, type PlaceIdentity, type TripPlannerConfiguration } from '../../types/planner';
import { Button } from '../../../../components/ui/Button';
import { Field, FIELD_LABEL, FIELD_VALUE, RULED_FIELD } from '../../../../components/ui/Input';
import { Skeleton } from '../../../../components/ui/Skeleton';
import { useApp } from '../../../../app/state/AppContext';
import { useSendMessage } from '../../../../app/session/useSendMessage';
import { DateRangePicker } from './DateRangePicker';
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

const CHIP = 'min-h-10 rounded-label border border-transparent px-3 text-[13px] transition-colors duration-fast ease-standard';
const CHIP_ON = 'border-accent/20 bg-accent-soft font-medium text-accent';
const CHIP_OFF = 'bg-surface/70 text-ink-secondary hover:bg-accent-soft/60 hover:text-ink';
const VISIBLE_PRIMARY_STYLES = 4;
const NATURAL_DETAILS = ['轻松一点', '当地美食', '人文体验', '爸妈同行'] as const;

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

function tripDays(start: string, end: string): number {
  if (!start || !end) return 0;
  return Math.floor((new Date(`${end}T00:00:00`).getTime() - new Date(`${start}T00:00:00`).getTime()) / 86400000) + 1;
}

function endDateForDuration(start: string, days: number): string {
  if (!start) return '';
  const date = new Date(`${start}T00:00:00`);
  date.setDate(date.getDate() + days - 1);
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

export const PlaceField: React.FC<{
  role: 'origin' | 'destination';
  value: PlaceIdentity | null;
  onChange: (value: PlaceIdentity) => void;
  label: string;
  frequent?: boolean;
  initialQuery?: string;
  className?: string;
}> = ({ role, value, onChange, label, frequent, initialQuery = '', className }) => {
  const [query, setQuery] = React.useState(value?.name || initialQuery);
  const [candidates, setCandidates] = React.useState<PlaceSearchCandidate[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState('');
  const runner = React.useMemo(() => createPlaceSearchRunner(role), [role]);
  React.useEffect(() => () => runner.cancel(), [runner]);

  const search = React.useCallback(async (raw: string) => {
    const q = raw.trim();
    if (q.length < 2) return;
    await runner.run(q, { setLoading, setError, setCandidates });
  }, [runner]);

  React.useEffect(() => {
    if (value) setQuery(value.name);
  }, [value]);

  React.useEffect(() => {
    const q = query.trim();
    if (q.length < 2 || q === value?.name) {
      runner.cancel();
      setCandidates([]);
      setError('');
      setLoading(false);
      return;
    }
    const timer = window.setTimeout(() => void search(q), 280);
    return () => window.clearTimeout(timer);
  }, [query, value?.name, search, runner]);

  return (
    <div className={cn('relative min-w-0 flex-1', className)}>
      <label className={FIELD_LABEL}>{label}</label>
      <div className={RULED_FIELD}>
        <MapPin size={15} className="shrink-0 text-accent" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              void search(query);
            }
          }}
          className={cn('min-w-0 flex-1 bg-transparent py-2', FIELD_VALUE)}
          placeholder={role === 'origin' ? '城市、机场或火车站' : '城市或区域'}
          aria-label={label}
          autoComplete="off"
        />
        {frequent && value && <span className="rounded-label bg-chart/8 px-1.5 py-0.5 text-[11px] text-chart">常用</span>}
        {loading && <span className="text-[11px] text-ink-muted">搜索中…</span>}
      </div>

      {(candidates.length > 0 || error) && (
        <div className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-card border border-stroke bg-panel p-1 shadow-lg">
          {candidates.map(({ place }) => (
            <button
              key={place.place_id}
              type="button"
              onClick={() => {
                onChange(place);
                setCandidates([]);
                setError('');
              }}
              className="flex min-h-11 w-full items-start gap-2 rounded-label px-3 py-2 text-left transition-colors hover:bg-accent-soft"
            >
              <MapPin size={14} className="mt-0.5 shrink-0 text-accent" />
              <span className="min-w-0">
                <strong className="block truncate text-sm font-medium text-ink">{place.name}</strong>
                <span className="block truncate text-xs text-ink-secondary">{place.display_name}</span>
              </span>
            </button>
          ))}
          {error && <p role="status" className="px-3 py-2 text-xs text-error">{error}</p>}
        </div>
      )}
    </div>
  );
};

export const TripPlanner: React.FC<{
  guidedText?: string;
  compact?: boolean;
  initialDestinations?: PlaceIdentity[];
  inspiration?: PlannerInspiration | null;
}> = ({ guidedText = '', compact = false, initialDestinations = [], inspiration = null }) => {
  const { state, dispatch } = useApp();
  const { sendMessage } = useSendMessage();
  const reducedMotion = useReducedMotion();
  const naturalInputRef = React.useRef<HTMLTextAreaElement>(null);
  const naturalPanelRef = React.useRef<HTMLDivElement>(null);
  const structuredPanelRef = React.useRef<HTMLDivElement>(null);
  const plannerRef = React.useRef<HTMLElement>(null);
  const [mode, setMode] = React.useState<PlannerMode>(compact ? 'structured' : 'natural');
  const inspirationModeRef = React.useRef<PlannerMode>(mode);
  const appliedStructuredInspirationRef = React.useRef<number | null>(null);
  const tabsId = React.useId();
  const [config, setConfig] = React.useState<TripPlannerConfiguration | null>(null);
  const [configError, setConfigError] = React.useState<RequestFailure | null>(null);
  const [origin, setOrigin] = React.useState<PlaceIdentity | null>(null);
  const [destinations, setDestinations] = React.useState<Array<PlaceIdentity | null>>(
    initialDestinations.length ? initialDestinations.slice(0, 3) : [null],
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
    inspirationModeRef.current = mode;
    setNaturalText(inspiration.text);
    setError('');
    if (mode === 'structured') return;
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

  const days = tripDays(startDate, endDate);

  const submitStructured = async () => {
    setError('');
    const selectedDestinations = destinations.filter((item): item is PlaceIdentity => Boolean(item));
    if (!origin || selectedDestinations.length !== destinations.length) {
      setError('请从地点候选中确认出发地和所有目的地');
      return;
    }
    if (days < 1 || days > 14) {
      setError(days > 14 ? '单次旅行最多 14 天，请拆分后再规划' : '请选择正确的开始和结束日期');
      return;
    }
    const numericBudget = budget.trim() ? Number(budget) : null;
    if (numericBudget !== null && (!Number.isFinite(numericBudget) || numericBudget <= 0)) {
      setError('总预算请输入大于 0 的金额');
      return;
    }
    const identity: ControlledTripIdentity = {
      origin,
      destinations: selectedDestinations,
      start_date: startDate,
      end_date: endDate,
      party: { adults, children, elderly_companions: elderly, accessibility_required: false },
      style: { primary, secondary_interests: interests, source: primaryTouched ? 'current' : 'suggested' },
    };
    dispatch({ type: 'SET_GUIDED_INTAKE', payload: null });
    const budgetText = numericBudget !== null ? `，总预算约 ${numericBudget.toLocaleString('zh-CN')} 元` : '';
    const summary = `${guidedText || `从${origin.name}出发，前往${selectedDestinations.map((item) => item.name).join('、')}，${startDate} 至 ${endDate}`}${budgetText}`;
    await sendMessage(summary, undefined, {
      route: 'trip_planning',
      controlledTripIdentity: identity,
      assistantPendingLabel: '正在整理旅行信息',
    });
  };

  const submitNatural = async () => {
    const text = naturalText.trim();
    if (!text || state.isStreaming) return;
    setError('');
    await sendMessage(text, undefined, { assistantPendingLabel: '正在理解你的旅行想法' });
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
    <section ref={plannerRef} className={cn('planner-card', compact && 'planner-card-compact')} aria-label="旅行规划卡">
      {tabs}
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
              <button
                type="button"
                className="planner-natural-discovery"
                onClick={() => {
                  setNaturalText('还没有确定目的地，想找一个节奏轻松、能吃当地美食的地方，大约 5 天。');
                  naturalInputRef.current?.focus({ preventScroll: true });
                }}
              >
                还没定目的地？从偏好开始
                <ArrowRight size={13} aria-hidden />
              </button>
            </div>
            {error && <p className="planner-error" role="alert">{error}</p>}
            <Button size="lg" className="planner-main-action" disabled={!naturalText.trim() || state.isStreaming} onClick={() => void submitNatural()}>
              开始规划 <ArrowRight size={17} aria-hidden />
            </Button>
        </m.div>
        <m.div
          role="tabpanel"
          id={`${tabsId}-structured-panel`}
          aria-labelledby={`${tabsId}-structured-tab`}
          ref={structuredPanelRef}
          aria-hidden={mode !== 'structured'}
          className={cn('planner-panel', mode === 'structured' ? 'is-active' : 'is-inactive')}
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
                  <div className="planner-destination-fields">
                    {destinations.map((destination, index) => (
                      <div key={index} className="planner-destination-row">
                        <PlaceField
                          role="destination"
                          value={destination}
                          onChange={(place) => setDestinations((items) => items.map((item, i) => (i === index ? place : item)))}
                          label={index === 0 ? '去哪里' : `第 ${index + 1} 站`}
                          initialQuery={index === 0 ? extracted.destination : ''}
                        />
                        {destinations.length > 1 && (
                          <div className="flex shrink-0 items-center self-end">
                            <button type="button" aria-label="上移目的地" disabled={index === 0} onClick={() => setDestinations((items) => { const next = [...items]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; return next; })} className="planner-icon-action"><ArrowUp size={14} /></button>
                            <button type="button" aria-label="下移目的地" disabled={index === destinations.length - 1} onClick={() => setDestinations((items) => { const next = [...items]; [next[index + 1], next[index]] = [next[index + 1], next[index]]; return next; })} className="planner-icon-action"><ArrowDown size={14} /></button>
                            <button type="button" aria-label={`删除第 ${index + 1} 个目的地`} onClick={() => setDestinations((items) => items.filter((_, i) => i !== index))} className="planner-icon-action hover:text-error"><X size={14} /></button>
                          </div>
                        )}
                        {index === destinations.length - 1 && destinations.length < 3 && (
                          <button type="button" className="planner-add-destination" onClick={() => setDestinations((items) => [...items, null])}>
                            <Plus size={13} aria-hidden />添加目的地
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="planner-form-grid">
                  <DateRangePicker start={startDate} end={endDate} onChange={(nextStart, nextEnd) => { setStartDate(nextStart); setEndDate(nextEnd); setError(''); }} />
                  <Field label="同行" className="planner-party">
                    <Users size={16} className="shrink-0 text-accent" />
                    {([['成人', adults, setAdults, 1], ['儿童', children, setChildren, 0]] as const).map(([label, value, setter, min]) => (
                      <div key={label} className="flex items-center gap-0.5">
                        <span className="mr-1 text-[12px] text-ink-secondary">{label}</span>
                        <button type="button" aria-label={`减少${label}`} disabled={value <= min} onClick={() => setter(value - 1)} className="planner-stepper"><Minus size={13} /></button>
                        <span className="w-5 text-center font-mono text-[14px] tabular-nums">{value}</span>
                        <button type="button" aria-label={`增加${label}`} onClick={() => setter(value + 1)} className="planner-stepper"><Plus size={13} /></button>
                      </div>
                    ))}
                  </Field>
                </div>

                <div className="planner-preference-block">
                  <div className="planner-preference-heading">
                    <p className={FIELD_LABEL}>这次想要</p>
                    <div className="planner-budget-field">
                      <label htmlFor="planner-budget">总预算（可选）</label>
                      <div className="planner-budget-input">
                        <span>¥</span>
                        <input id="planner-budget" inputMode="numeric" min="0" type="number" value={budget} onChange={(event) => setBudget(event.target.value)} placeholder="12,000" />
                        <span>元</span>
                      </div>
                    </div>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {config.primary_styles.slice(0, VISIBLE_PRIMARY_STYLES).map((style) => (
                      <button key={style.id} type="button" aria-pressed={primary === style.label} onClick={() => { setPrimary(style.label); setPrimaryTouched(true); }} className={cn(CHIP, primary === style.label ? CHIP_ON : CHIP_OFF)}>{style.label}</button>
                    ))}
                    <button type="button" aria-expanded={more} className="min-h-9 px-2 text-[12px] font-medium text-accent hover:underline" onClick={() => setMore(!more)}>更多偏好</button>
                  </div>
                  {more && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {config.primary_styles.slice(VISIBLE_PRIMARY_STYLES).map((style) => (
                        <button key={style.id} type="button" aria-pressed={primary === style.label} onClick={() => { setPrimary(style.label); setPrimaryTouched(true); }} className={cn(CHIP, primary === style.label ? CHIP_ON : CHIP_OFF)}>{style.label}</button>
                      ))}
                      {config.secondary_interests.map((interest) => (
                        <button key={interest.id} type="button" aria-pressed={interests.includes(interest.label)} disabled={!interests.includes(interest.label) && interests.length >= config.max_secondary_interests} onClick={() => setInterests((items) => items.includes(interest.label) ? items.filter((item) => item !== interest.label) : [...items, interest.label])} className={cn(CHIP, interests.includes(interest.label) ? CHIP_ON : CHIP_OFF, 'disabled:opacity-40')}>{interest.label}</button>
                      ))}
                    </div>
                  )}
                </div>

                {error && <p className="planner-error" role="alert">{error}</p>}
                <Button size="lg" className="planner-main-action" onClick={() => void submitStructured()} disabled={state.isStreaming}>
                  开始规划 <ArrowRight size={17} aria-hidden />
                </Button>
              </>
            )}
        </m.div>
      </div>
    </section>
  );
};
