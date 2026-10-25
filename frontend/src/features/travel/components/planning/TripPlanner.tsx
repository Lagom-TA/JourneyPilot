import { getTripPlannerConfiguration } from "../../api/planner";
import { getDefaultOrigin, setDefaultOrigin } from "../../../settings/api/defaultOrigin";
import { useReducedMotion } from "motion/react";
import { ArrowDown, ArrowRight, ArrowUp, ChevronDown, MapPin, Minus, Plus, Send, Users, X } from "lucide-react";
import { createPlaceSearchRunner, type PlaceSearchCandidate } from "../../model/placeSearch";
import { describeRequestFailure, type RequestFailure } from "../../../../lib/requestFailureMessage";
import { RequestFailureNotice } from "../../../../components/ui/RequestFailureNotice";
import { cn } from "../../../../lib/utils";
import { type ControlledTripIdentity, type PlaceIdentity, type TripPlannerConfiguration } from "../../types/planner";
import { Button } from "../../../../components/ui/Button";
import { Field, FIELD_LABEL, FIELD_VALUE, RULED_FIELD } from "../../../../components/ui/Input";
import { Skeleton } from "../../../../components/ui/Skeleton";
import { useApp } from "../../../../app/state/AppContext";
import { useSendMessage } from "../../../../app/session/useSendMessage";
import { DateRangePicker } from "./DateRangePicker";
import React from 'react';
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
    return { origin, destination, start: exactDates?.[1] || '', end: exactDates?.[2] || '', adults: Number(adultMatch?.[1] || config.default_adults), children: Number(childMatch?.[1] || (hasChild ? Math.max(1, config.default_children) : config.default_children)), elderly, primary: inferred?.label || fallback.label } as const;
}
const CHIP = 'min-h-10 rounded-label px-2.5 text-sm transition-colors duration-fast ease-standard';
const CHIP_ON = 'bg-accent/10 font-medium text-accent';
const CHIP_OFF = 'text-ink-secondary hover:bg-ink/5 hover:text-ink';
const PANEL = 'rounded-card border border-stroke bg-panel p-5 sm:p-6';
function tripDays(start: string, end: string): number {
    if (!start || !end)
        return 0;
    return Math.floor((new Date(`${end}T00:00:00`).getTime() - new Date(`${start}T00:00:00`).getTime()) / 86400000) + 1;
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
        if (q.length < 2)
            return;
        await runner.run(q, { setLoading, setError, setCandidates });
    }, [runner]);
    React.useEffect(() => { if (value)
        setQuery(value.name); }, [value]);
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
    return (<div className={cn('relative min-w-0 flex-1', className)}>

      <label className={FIELD_LABEL}>{label}</label>
      <div className={RULED_FIELD}>
        <MapPin size={15} className="shrink-0 text-chart"/>
        <input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') {
        event.preventDefault();
        void search(query);
    } }} className={cn('min-w-0 flex-1 bg-transparent py-2', FIELD_VALUE)} placeholder={role === 'origin' ? '城市、机场或火车站' : '城市、区域或岛屿'} aria-label={label} autoComplete="off"/>
        {frequent && value && <span className="rounded-label bg-success/10 px-1.5 py-0.5 text-[11px] text-success">常用</span>}
        {loading && <span className="text-[11px] text-ink-muted">搜索中…</span>}
      </div>

      {(candidates.length > 0 || error) && (<div className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-card border border-stroke bg-panel p-1 shadow-lg">
          {candidates.map(({ place }) => (<button key={place.place_id} type="button" onClick={() => { onChange(place); setCandidates([]); setError(''); }} className="flex min-h-11 w-full items-start gap-2 rounded-label px-3 py-2 text-left transition-colors duration-fast ease-standard hover:bg-accent-soft">
              <MapPin size={14} className="mt-0.5 shrink-0 text-chart"/>
              <span className="min-w-0"><strong className="block truncate text-sm font-medium text-ink">{place.name}</strong><span className="block truncate text-xs text-ink-secondary">{place.display_name}</span></span>
            </button>))}
          {error && <p role="status" className="px-3 py-2 text-xs text-error">{error}</p>}
        </div>)}
    </div>);
};
export const TripPlanner: React.FC<{
    guidedText?: string;
    compact?: boolean;
    initialDestinations?: PlaceIdentity[];
}> = ({ guidedText = '', compact = false, initialDestinations = [] }) => {
    const { state, dispatch } = useApp();
    const { sendMessage } = useSendMessage();
    const [config, setConfig] = React.useState<TripPlannerConfiguration | null>(null);
    const [configError, setConfigError] = React.useState<RequestFailure | null>(null);
    const [origin, setOrigin] = React.useState<PlaceIdentity | null>(null);
    const extracted = React.useMemo(() => config ? factsFromNaturalText(guidedText, config) : null, [config, guidedText]);
    const [destinations, setDestinations] = React.useState<Array<PlaceIdentity | null>>(initialDestinations.length ? initialDestinations.slice(0, 3) : [null]);
    const [startDate, setStartDate] = React.useState('');
    const [endDate, setEndDate] = React.useState('');
    const [adults, setAdults] = React.useState(0);
    const [children, setChildren] = React.useState(0);
    const [advanced, setAdvanced] = React.useState(false);
    const [elderly, setElderly] = React.useState(false);
    const [accessible, setAccessible] = React.useState(false);
    const [primary, setPrimary] = React.useState('');
    const [primaryTouched, setPrimaryTouched] = React.useState(false);
    const [interests, setInterests] = React.useState<string[]>([]);
    const [more, setMore] = React.useState(false);
    const [naturalText, setNaturalText] = React.useState(guidedText);
    const [originReady, setOriginReady] = React.useState<boolean | null>(null);
    const [originSetup, setOriginSetup] = React.useState<PlaceIdentity | null>(null);
    const [error, setError] = React.useState('');
    const [promptIndex, setPromptIndex] = React.useState(0);
    const [naturalFocused, setNaturalFocused] = React.useState(false);
    const reducedMotion = useReducedMotion();
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
            setAccessible(next.default_accessibility_required);
            setPrimary(facts.primary);
        }
        catch (reason) {
            setConfigError(describeRequestFailure(reason, '读取', '旅行规划选项'));
        }
    }, [guidedText]);
    React.useEffect(() => { void loadConfiguration(); }, [loadConfiguration]);
    React.useEffect(() => {
        if (!config || naturalText || naturalFocused || reducedMotion)
            return;
        const timer = window.setInterval(() => setPromptIndex((index) => (index + 1) % config.inspiration_prompts.length), config.inspiration_rotation_ms);
        return () => window.clearInterval(timer);
    }, [config, naturalFocused, naturalText, reducedMotion]);
    React.useEffect(() => {
        let active = true;
        getDefaultOrigin().then((place) => {
            if (!active)
                return;
            setOrigin(extracted?.origin ? null : place);
            setOriginReady(Boolean(place));
        }).catch(() => { if (active)
            setOriginReady(false); });
        return () => { active = false; };
    }, [extracted?.origin]);
    const days = tripDays(startDate, endDate);
    const submitStructured = async () => {
        setError('');
        const selectedDestinations = destinations.filter((item): item is PlaceIdentity => Boolean(item));
        if (!origin || selectedDestinations.length !== destinations.length)
            return setError('请从地点候选中确认出发地和所有目的地');
        if (days < 1 || days > 14)
            return setError(days > 14 ? '单次旅行最多 14 天，请拆分后再规划' : '请选择正确的开始和结束日期');
        const identity: ControlledTripIdentity = {
            origin, destinations: selectedDestinations, start_date: startDate, end_date: endDate,
            party: { adults, children, elderly_companions: elderly, accessibility_required: accessible },
            style: { primary, secondary_interests: interests, source: primaryTouched ? 'current' : 'suggested' },
        };
        dispatch({ type: 'SET_GUIDED_INTAKE', payload: null });
        const summary = guidedText || `从${origin.name}出发，前往${selectedDestinations.map((item) => item.name).join('、')}，${startDate} 至 ${endDate}`;
        await sendMessage(summary, undefined, {
            route: 'trip_planning', controlledTripIdentity: identity, assistantPendingLabel: '正在整理旅行信息',
        });
    };
    if (configError)
        return <RequestFailureNotice title="暂时无法开始规划" failure={configError} onRetry={() => void loadConfiguration()}/>;
    if (!config || originReady === null || !extracted) {
        return (<div className="flex flex-col gap-6" aria-label="正在读取旅行规划配置">
        {[0, 1, 2].map((row) => (<div key={row} className="flex flex-col gap-2">
            <Skeleton radius="label" className="h-3 w-16"/>
            <div className="h-11 border-b border-stroke"/>
          </div>))}
      </div>);
    }
    if (!originReady) {
        return (<section aria-labelledby="origin-setup-title" className="origin-setup rounded-card border border-stroke bg-panel p-6 sm:p-8">
        <p className="mb-3 text-xs font-medium text-chart">先从熟悉的地方出发</p>
        <h2 id="origin-setup-title" className="text-xl font-semibold text-ink">选择你的常用出发地</h2>

        <p className="mt-1 text-sm text-ink-secondary">之后可以在「我的偏好」里改。</p>
        <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-end">
          <PlaceField role="origin" value={originSetup} onChange={setOriginSetup} label="常用出发地"/>
          <Button variant="primary" className="flex-shrink-0" disabled={!originSetup} onClick={async () => {
                if (!originSetup)
                    return;
                const saved = await setDefaultOrigin(originSetup);
                setOrigin(saved);
                setOriginReady(true);
            }}>保存并继续</Button>
        </div>

        <button type="button" onClick={() => { setOrigin(null); setOriginReady(true); }} className="mt-4 text-[13px] font-medium text-ink-secondary underline-offset-2 transition-colors duration-fast ease-standard hover:text-ink hover:underline">
          跳过
        </button>
      </section>);
    }
    return (<div className={cn('planner-layout', compact && 'planner-layout-compact')}>

      <section aria-label="结构化旅行规划器" className={cn(PANEL, 'planner-primary')}>
        <header className="planner-section-heading">
          <p className="planner-kicker">目的地已在心里</p>
          <h2 className="text-xl font-semibold text-ink">规划一趟确定的旅行</h2>
        </header>
        <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-start">
          <PlaceField role="origin" value={origin} onChange={setOrigin} label="从哪里出发" frequent={!extracted.origin} initialQuery={extracted.origin}/>

          <div className="hidden shrink-0 text-chart sm:flex sm:h-11 sm:items-center sm:mt-[22px]" aria-hidden>→</div>
          <div className="flex min-w-0 flex-[1.35] flex-col gap-3">
            {destinations.map((destination, index) => (<div key={index} className="flex items-end gap-1">
                <PlaceField role="destination" value={destination} onChange={(place) => setDestinations((items) => items.map((item, i) => i === index ? place : item))} label={index === 0 ? '去哪里' : `第 ${index + 1} 站`} initialQuery={index === 0 ? extracted.destination : ''}/>
                {destinations.length > 1 && (<div className="flex shrink-0 items-center gap-0.5">
                    <button type="button" aria-label="上移目的地" disabled={index === 0} onClick={() => setDestinations((items) => { const next = [...items]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; return next; })} className="grid h-11 w-8 place-items-center rounded-card text-ink-secondary transition-colors hover:bg-surface hover:text-ink disabled:opacity-30 disabled:hover:bg-transparent"><ArrowUp size={15}/></button>
                    <button type="button" aria-label="下移目的地" disabled={index === destinations.length - 1} onClick={() => setDestinations((items) => { const next = [...items]; [next[index + 1], next[index]] = [next[index], next[index + 1]]; return next; })} className="grid h-11 w-8 place-items-center rounded-card text-ink-secondary transition-colors hover:bg-surface hover:text-ink disabled:opacity-30 disabled:hover:bg-transparent"><ArrowDown size={15}/></button>
                    <button type="button" aria-label={`删除第 ${index + 1} 个目的地`} onClick={() => setDestinations((items) => items.filter((_, i) => i !== index))} className="grid h-11 w-8 place-items-center rounded-card text-ink-secondary transition-colors hover:bg-surface hover:text-error"><X size={15}/></button>
                  </div>)}
              </div>))}
            {destinations.length < 3 && <button type="button" className="mt-0.5 self-start text-[13px] font-medium text-accent hover:underline" onClick={() => setDestinations((items) => [...items, null])}>+ 添加目的地</button>}
          </div>
        </div>
        <div className="planner-date-party mt-5 flex flex-col gap-4 sm:flex-row">
          <DateRangePicker start={startDate} end={endDate} onChange={(nextStart, nextEnd) => { setStartDate(nextStart); setEndDate(nextEnd); setError(''); }}/>

          <Field label="同行" className="planner-party sm:flex-none sm:w-[300px]">
            <Users size={16} className="shrink-0 text-chart"/>
            {([['成人', adults, setAdults, 1], ['儿童', children, setChildren, 0]] as const).map(([label, value, setter, min]) => (<div key={label} className="flex items-center gap-0.5">
                <span className="mr-1 text-[13px] text-ink-secondary">{label}</span>
                <button type="button" aria-label={`减少${label}`} disabled={value <= min} onClick={() => setter(value - 1)} className="grid h-8 w-8 place-items-center text-ink-secondary transition-colors duration-fast ease-standard hover:text-ink disabled:opacity-30">
                  <Minus size={13}/>
                </button>
                <span className="w-5 text-center font-mono text-[15px] tabular-nums">{value}</span>
                <button type="button" aria-label={`增加${label}`} onClick={() => setter(value + 1)} className="grid h-8 w-8 place-items-center text-ink-secondary transition-colors duration-fast ease-standard hover:text-ink">
                  <Plus size={13}/>
                </button>
              </div>))}
          </Field>
        </div>
        <button type="button" data-testid="planner-party-advanced" aria-expanded={advanced} className="mt-4 flex items-center gap-1 text-[13px] text-ink-secondary transition-colors duration-fast ease-standard hover:text-ink" onClick={() => setAdvanced(!advanced)}>其他同行需求 <ChevronDown size={13} className={cn('transition-transform duration-base ease-standard', advanced && 'rotate-180')}/></button>

        {advanced && (<div className="mt-2 flex flex-wrap items-center gap-1.5">
            {([['elderly', elderly, setElderly, '老人同行'], ['accessible', accessible, setAccessible, '需要无障碍']] as const).map(([id, checked, setter, label]) => (<button key={id} type="button" data-testid={`planner-party-${id}`} aria-pressed={checked} onClick={() => setter(!checked)} className={cn(CHIP, checked ? CHIP_ON : CHIP_OFF)}>
                {label}
              </button>))}
          </div>)}


        <div className="mt-6 border-t border-stroke/60 pt-5">
          <p className={FIELD_LABEL}>这次想要</p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {config.primary_styles.map((style) => (<button key={style.id} type="button" aria-pressed={primary === style.label} onClick={() => { setPrimary(style.label); setPrimaryTouched(true); }} className={cn(CHIP, primary === style.label ? CHIP_ON : CHIP_OFF)}>
                {style.label}{style.is_default && !primaryTouched && ' · 建议'}
              </button>))}
            <button type="button" aria-expanded={more} className="ml-1 text-[13px] font-medium text-accent transition-colors duration-fast ease-standard hover:underline" onClick={() => setMore(!more)}>更多偏好</button>
          </div>
          {more && (<div className="mt-2 flex flex-wrap gap-1.5">
              {config.secondary_interests.map((interest) => (<button key={interest.id} type="button" aria-pressed={interests.includes(interest.label)} disabled={!interests.includes(interest.label) && interests.length >= config.max_secondary_interests} onClick={() => setInterests((items) => items.includes(interest.label) ? items.filter((item) => item !== interest.label) : [...items, interest.label])} className={cn(CHIP, interests.includes(interest.label) ? CHIP_ON : CHIP_OFF, 'disabled:opacity-40')}>
                  {interest.label}
                </button>))}
            </div>)}
        </div>
        <div className="planner-submit">
          <div className="min-w-0">
            <p className="text-xs leading-5 text-ink-secondary">先生成调研计划，由你确认后继续。</p>
            {error && <p className="mt-1 text-sm text-error" role="alert">{error}</p>}
          </div>
          <Button variant="primary" className="planner-submit-button" onClick={() => void submitStructured()} disabled={state.isStreaming}>开始规划 <ArrowRight size={16} aria-hidden="true"/></Button>
        </div>
      </section>


      {!compact && (<section className={cn(PANEL, 'planner-inspiration')} aria-label="自然语言旅行输入">
          <p className="planner-kicker">也可以，从灵感开始</p>
          <h2 className="text-xl font-semibold text-ink">还没完全想好？</h2>
          <p className="mt-2 text-[13px] leading-6 text-ink-secondary">一个想去的地方，一件想做的事，<br className="hidden xl:block"/>都可以是出发的理由。</p>
          <div className="inspiration-composer mt-5 flex items-end gap-2 rounded-card border border-stroke bg-panel p-2 transition-colors duration-base ease-standard focus-within:border-accent">
            <textarea aria-label="描述旅行想法" value={naturalText} onFocus={() => setNaturalFocused(true)} onBlur={() => setNaturalFocused(false)} onChange={(event) => setNaturalText(event.target.value)} rows={2} className="min-h-14 min-w-0 flex-1 resize-none bg-transparent px-2 py-1 text-[15px] leading-7 text-ink placeholder:text-ink-muted" placeholder={`例如：${config.inspiration_prompts[promptIndex]}`}/>
            <Button aria-label="发送旅行想法" variant="primary" disabled={!naturalText.trim() || state.isStreaming} onClick={() => void sendMessage(naturalText, undefined, { assistantPendingLabel: '正在判断任务' })}><Send size={15}/></Button>
          </div>
          <p className="mt-3 text-xs leading-5 text-ink-muted">说说你的想法，一起找到旅行的方向。</p>
        </section>)}
    </div>);
};
