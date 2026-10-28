import { AnimatePresence, m } from 'motion/react';
import { ArrowRight, BookOpen, ChevronDown, Clock3, MapPin, Plus, Search } from 'lucide-react';
import { Button } from '../../../components/ui/Button';
import { useApp } from '../../../app/state/AppContext';
import { useSessionManager } from '../../../app/session/useSessionManager';
import { listTripRuns } from '../api/runs';
import { type TripRunResponse, type TripRunStatus } from '../types/runs';
import { type ChatSession } from '../../chat/types/messages';
import { parseSessionTitle } from '../../chat/model/sessionTitle';
import { cn } from '../../../lib/utils';
import { duration, easing } from '../../../lib/motion';
import React from 'react';

const STATUS_LABELS: Record<TripRunStatus, string> = {
  created: '规划中',
  running: '规划中',
  awaiting_input: '等待确认',
  completed: '已完成',
  failed: '未完成',
  interrupted: '已中断',
  cancel_requested: '正在停止',
  cancelled: '已取消',
};

interface TripGroup {
  session: ChatSession | null;
  sessionId: string;
  runs: TripRunResponse[];
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

function friendlyTripTitle(primary: string, fallback: string): string {
  const combined = `${primary} ${fallback}`;
  const days = combined.match(/(\d+)\s*天/)?.[1] ?? combined.match(/(\d+)\s*日/)?.[1];
  for (const raw of [primary, fallback]) {
    const text = raw.trim();
    if (!text) continue;
    const parsed = parseSessionTitle(text);
    if (parsed.kind === 'trip') return `${parsed.destination}${days ? ` ${days} 日` : ''}`;
    if (text.length <= 28 && !text.startsWith('请帮')) return text;
    const destination = text.match(/(?:去|前往)([^，,。\s]{1,12}?)(?:旅行|旅游|玩|待|住|，|,|。|$)/)?.[1];
    if (destination) return `${destination}${days ? ` ${days} 日` : '旅行'}`;
  }
  const text = (fallback || primary).trim();
  return text ? `${text.slice(0, 28)}${text.length > 28 ? '…' : ''}` : '未命名旅行';
}

function TripMiniCover({ title, count }: { title: string; count: number }) {
  const parsed = parseSessionTitle(title);
  const destination = parsed.kind === 'trip' ? parsed.destination : parsed.text;
  const origin = parsed.kind === 'trip' ? parsed.origin : null;
  return (
    <div className="trip-mini-cover" aria-hidden>
      <svg viewBox="0 0 260 180" preserveAspectRatio="none">
        <path d="M-20 46C38 5 76 66 127 35s86-24 153 9M-12 88c58-35 93 15 145-9s84-17 140 12M-18 139c61-28 93 9 146-11s86-4 147 20" />
        <path className="trip-mini-route" d="M43 129c39-64 88-23 129-74" />
        <circle cx="43" cy="129" r="6" />
        <circle cx="172" cy="55" r="6" />
      </svg>
      <span className="trip-mini-kicker">JOURNEY NOTES</span>
      <strong>{destination}</strong>
      <span className="trip-mini-origin">{origin ? `${origin} 出发` : '旅行手册'} · {count > 0 ? `${count} 次生成` : '旅行问答'}</span>
    </div>
  );
}

export const MyTripsPage: React.FC = () => {
  const { state, dispatch, activeStreamAbortRef } = useApp();
  const { openSession, setLastSession } = useSessionManager();
  const [runs, setRuns] = React.useState<TripRunResponse[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');
  const [query, setQuery] = React.useState('');
  const [expanded, setExpanded] = React.useState<string[]>([]);

  const loadRuns = React.useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await listTripRuns({ mode: 'deep', limit: 80 });
      setRuns(result.runs);
      if (result.runs.length > 0) setExpanded((current) => current.length > 0 ? current : [result.runs[0].session_id]);
    } catch {
      setError('暂时无法读取旅行记录，请稍后重试。');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  const groups = React.useMemo<TripGroup[]>(() => {
    const bySession = new Map<string, TripRunResponse[]>();
    for (const run of runs) {
      bySession.set(run.session_id, [...(bySession.get(run.session_id) ?? []), run]);
    }
    const sessionIds = new Set([...bySession.keys(), ...state.sessions.map((session) => session.id)]);
    return [...sessionIds].map((sessionId) => ({
      sessionId,
      session: state.sessions.find((session) => session.id === sessionId) ?? null,
      runs: [...(bySession.get(sessionId) ?? [])].sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? '')),
    })).sort((a, b) => {
      const aUpdated = a.runs[0]?.updated_at ?? a.session?.updatedAt.toISOString() ?? '';
      const bUpdated = b.runs[0]?.updated_at ?? b.session?.updatedAt.toISOString() ?? '';
      return bUpdated.localeCompare(aUpdated);
    });
  }, [runs, state.sessions]);

  const visibleGroups = React.useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase('zh-CN');
    if (!keyword) return groups;
    return groups.filter((group) => {
      const text = `${group.runs[0]?.title ?? ''} ${group.session?.title ?? ''} ${group.session?.lastMessagePreview ?? ''}`;
      return text.toLocaleLowerCase('zh-CN').includes(keyword);
    });
  }, [groups, query]);

  const startNewTrip = () => {
    activeStreamAbortRef.current?.abort();
    activeStreamAbortRef.current = null;
    dispatch({ type: 'CLEAR_CHAT' });
    setLastSession(null);
    const url = new URL(window.location.href);
    url.searchParams.delete('session_id');
    url.searchParams.delete('run_id');
    url.searchParams.set('view', 'chat');
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    dispatch({ type: 'SET_ACTIVE_VIEW', payload: 'chat' });
  };

  const openRun = (sessionId: string, runId?: string) => {
    const url = new URL(window.location.href);
    url.searchParams.set('view', 'chat');
    url.searchParams.set('session_id', sessionId);
    if (runId) url.searchParams.set('run_id', runId);
    else url.searchParams.delete('run_id');
    window.history.pushState(null, '', `${url.pathname}${url.search}${url.hash}`);
    dispatch({ type: 'SET_ACTIVE_VIEW', payload: 'chat' });
    void openSession(sessionId, runId);
  };

  return (
    <div className="my-trips-page">
      <header className="my-trips-heading">
        <div>
          <p className="my-trips-kicker">YOUR JOURNEYS</p>
          <h1>我的行程</h1>
          <p>珍藏每一段旅程，也从这里继续出发。</p>
        </div>
        <Button size="lg" onClick={startNewTrip}><Plus size={17} />新旅行</Button>
      </header>

      <div className="my-trips-toolbar">
        <label className="my-trips-search">
          <Search size={16} aria-hidden />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索目的地或旅行名称" aria-label="搜索我的行程" />
        </label>
        {!loading && !error && <span>{groups.length} 趟旅行 · {runs.length} 次生成</span>}
      </div>

      {loading ? (
        <div className="my-trips-loading" aria-label="正在读取我的行程">
          {[0, 1, 2].map((item) => <div key={item} />)}
        </div>
      ) : error ? (
        <div className="my-trips-empty" role="alert">
          <BookOpen size={28} />
          <h2>旅行记录暂时没有打开</h2>
          <p>{error}</p>
          <Button variant="secondary" onClick={() => void loadRuns()}>重新读取</Button>
        </div>
      ) : visibleGroups.length === 0 ? (
        <div className="my-trips-empty">
          <MapPin size={28} />
          <h2>{query ? '没有找到这趟旅行' : '第一趟旅行，正在等你'}</h2>
          <p>{query ? '试试其他目的地或旅行名称。' : '从一句想法开始，生成一份每天都能照着走的计划。'}</p>
          {query ? <Button variant="secondary" onClick={() => setQuery('')}>清除搜索</Button> : <Button onClick={startNewTrip}>开始新旅行<ArrowRight size={15} /></Button>}
        </div>
      ) : (
        <div className="my-trips-list">
          {visibleGroups.map((group) => {
            const latest: TripRunResponse | undefined = group.runs[0];
            const title = friendlyTripTitle(latest?.title ?? group.session?.title ?? '', group.session?.lastMessagePreview ?? group.session?.title ?? '');
            const isExpanded = expanded.includes(group.sessionId);
            return (
              <article className="my-trip-card" key={group.sessionId} data-testid={`trip-card-${group.sessionId}`}>
                <div className="my-trip-main">
                  <TripMiniCover title={title} count={group.runs.length} />
                  <div className="my-trip-copy">
                    <div className="my-trip-title-line">
                      <h2>{title}</h2>
                      <span className={cn('my-trip-status', latest?.status === 'completed' && 'is-complete')}>{latest ? STATUS_LABELS[latest.status] : '旅行问答'}</span>
                    </div>
                    <p>{group.session?.lastMessagePreview || '旅行需求、生成记录和正式结果都保存在这里。'}</p>
                    <div className="my-trip-meta">
                      <span><Clock3 size={14} />最近更新 {formatDateTime(latest?.updated_at ?? group.session?.updatedAt.toISOString() ?? '')}</span>
                      <span><BookOpen size={14} />{group.runs.length} 次生成记录</span>
                    </div>
                    <div className="my-trip-actions">
                      <Button variant="secondary" onClick={() => openRun(group.sessionId)}>
                        {latest ? (latest.status === 'completed' ? '打开当前行程' : '继续这趟旅行') : '打开对话'}<ArrowRight size={15} />
                      </Button>
                      {group.runs.length > 0 && <button type="button" aria-expanded={isExpanded} onClick={() => setExpanded((items) => items.includes(group.sessionId) ? items.filter((id) => id !== group.sessionId) : [...items, group.sessionId])} className="my-trip-history-toggle">
                        生成记录 <ChevronDown size={14} className={cn('transition-transform', isExpanded && 'rotate-180')} />
                      </button>}
                    </div>
                  </div>
                </div>
                <AnimatePresence initial={false}>
                  {isExpanded && group.runs.length > 0 && (
                    <m.div
                      className="my-trip-history"
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1, transition: { duration: duration.slow, ease: easing.decelerate } }}
                      exit={{ height: 0, opacity: 0, transition: { duration: duration.base, ease: easing.accelerate } }}
                    >
                      <div className="my-trip-history-inner">
                        <h3>生成记录</h3>
                        <ol>
                          {group.runs.map((run, index) => (
                            <li key={run.run_id}>
                              <span className="my-trip-history-time">{formatDateTime(run.created_at)}</span>
                              <span className="my-trip-history-name">{index === 0 ? '当前结果' : `第 ${group.runs.length - index} 次生成`}<small>{STATUS_LABELS[run.status]}</small></span>
                              <button type="button" onClick={() => openRun(group.sessionId, run.run_id)}>{index === 0 ? '查看' : '只读查看'}<ArrowRight size={13} /></button>
                            </li>
                          ))}
                        </ol>
                      </div>
                    </m.div>
                  )}
                </AnimatePresence>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
};
