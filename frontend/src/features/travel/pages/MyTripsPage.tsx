import React from 'react';
import { ArrowRight, Plus } from 'lucide-react';
import { Button } from '../../../components/ui/Button';
import { PageShell, type SurfaceState } from '../../../components/ui/PageShell';
import { useApp } from '../../../app/state/AppContext';
import { useSessionManager } from '../../../app/session/useSessionManager';
import { useStartNewTrip } from '../../../app/session/useStartNewTrip';
import { listTripRuns } from '../api/runs';
import { type TripRunResponse, type TripRunStatus } from '../types/runs';
import { type ChatSession } from '../../chat/types/messages';
import { parseSessionTitle } from '../../chat/model/sessionTitle';
import { describeRequestFailure, type RequestFailure } from '../../../lib/requestFailureMessage';

const STATUS_LABELS: Record<TripRunStatus, string> = {
  created: '规划中', running: '规划中', awaiting_input: '等待确认', completed: '已生成',
  failed: '生成失败', interrupted: '已中断', cancel_requested: '正在停止', cancelled: '已取消',
};

function openLabel(run: TripRunResponse | undefined): string {
  if (!run) return '查看对话';
  if (run.status === 'completed') return '查看行程';
  if (run.status === 'awaiting_input') return '继续规划';
  if (['created', 'running', 'cancel_requested'].includes(run.status)) return '查看进度';
  return '查看记录';
}

interface TripGroup {
  session: ChatSession | null;
  sessionId: string;
  runs: TripRunResponse[];
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(date);
}

export const MyTripsPage: React.FC = () => {
  const { state, dispatch } = useApp();
  const { openSession } = useSessionManager();
  const startNewTrip = useStartNewTrip();
  const [runs, setRuns] = React.useState<TripRunResponse[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<RequestFailure | null>(null);
  const [query, setQuery] = React.useState('');

  const loadRuns = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRuns((await listTripRuns({ mode: 'deep', limit: 80 })).runs);
    } catch (err) {
      setError(describeRequestFailure(err, '读取', '旅行记录'));
    } finally { setLoading(false); }
  }, []);
  React.useEffect(() => { void loadRuns(); }, [loadRuns]);

  const groups = React.useMemo<TripGroup[]>(() => {
    const bySession = new Map<string, TripRunResponse[]>();
    for (const run of runs) bySession.set(run.session_id, [...(bySession.get(run.session_id) ?? []), run]);
    const ids = new Set([...bySession.keys(), ...state.sessions.map(session => session.id)]);
    return [...ids].map(sessionId => ({
      sessionId,
      session: state.sessions.find(session => session.id === sessionId) ?? null,
      runs: bySession.get(sessionId) ?? [],
    })).sort((a, b) => {
      const updated = (group: TripGroup) => group.session?.updatedAt.toISOString() ?? group.runs[0]?.updated_at ?? '';
      return updated(b).localeCompare(updated(a));
    });
  }, [runs, state.sessions]);
  const visibleGroups = React.useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase('zh-CN');
    return keyword ? groups.filter(group => `${group.runs[0]?.title ?? ''} ${group.session?.title ?? ''}`.toLocaleLowerCase('zh-CN').includes(keyword)) : groups;
  }, [groups, query]);

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
  const surfaceState: SurfaceState = loading ? { kind: 'loading' } : error
    ? { kind: 'error', title: '暂时读不到旅行记录', failure: error, onRetry: () => void loadRuns() }
    : { kind: 'ready' };

  return <PageShell title="我的行程" state={surfaceState}
    actions={<Button onClick={startNewTrip}><Plus size={16} />新旅行</Button>}
    search={groups.length || query ? { value: query, onChange: setQuery, placeholder: '搜索行程' } : undefined}
    readout={!loading && !error && groups.length ? `${visibleGroups.length} 趟` : undefined}>
    {visibleGroups.length === 0 ? <div className="archive-empty">
      <h2>{query ? '没有找到这趟旅行' : '还没有行程'}</h2>
      {query ? <Button variant="ghost" onClick={() => setQuery('')}>清除搜索</Button> : <p>从一句旅行想法开始。</p>}
    </div> : <div className="my-trips-list">
      {visibleGroups.map(group => {
        const latest = group.runs[0];
        const rawTitle = latest?.title?.trim() || group.session?.title?.trim() || '未命名旅行';
        const title = parseSessionTitle(rawTitle);
        return <article className="my-trip-card" key={group.sessionId} data-testid={`trip-card-${group.sessionId}`}>
          <div className="my-trip-title-line">
            <h2><button type="button" onClick={() => openRun(group.sessionId)}>{title.kind === 'trip' ? title.destination : title.text}</button></h2>
            <span className={`my-trip-status${latest?.status === 'completed' ? ' is-complete' : ''}`}>{latest ? STATUS_LABELS[latest.status] : '旅行问答'}</span>
          </div>
          <div className="my-trip-meta">
            {title.kind === 'trip' && title.origin && <span>{title.origin}出发</span>}
            {title.kind === 'trip' && title.dates && <span>{title.dates}</span>}
            <span>更新于 {formatDateTime(group.session?.updatedAt.toISOString() ?? latest?.updated_at ?? '')}</span>
          </div>
          <div className="my-trip-actions"><button type="button" className="archive-link" onClick={() => openRun(group.sessionId)}>{openLabel(latest)}<ArrowRight size={15} /></button></div>
          {group.runs.length > 1 && <details className="my-trip-history">
            <summary>{group.runs.length} 次生成记录</summary>
            <ol>{group.runs.map((run, index) => <li key={run.run_id}>
              <span className="my-trip-history-time">{formatDateTime(run.created_at)}</span>
              <span>{index === 0 ? (run.status === 'completed' ? '当前结果' : '最新记录') : `第 ${group.runs.length - index} 次生成`}<small>{STATUS_LABELS[run.status]}</small></span>
              <button type="button" onClick={() => openRun(group.sessionId, run.run_id)}>{index === 0 ? '查看' : '只读查看'}<ArrowRight size={14} /></button>
            </li>)}</ol>
          </details>}
        </article>;
      })}
    </div>}
  </PageShell>;
};
