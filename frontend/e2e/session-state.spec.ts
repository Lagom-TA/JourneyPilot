import { expect, test, type Page } from '@playwright/test';
import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { deliveryBundle, sessionDetail, sessionSummary } from './fixtures/sessionData';
import { xianLayoutBundle, xianMixedTransportBundle, xianTransportDisplayBundle } from './fixtures/xianBundle';

test.skip(process.env.JP_SESSION_STATE_E2E !== '1', 'Explicit offline session-state opt-in required');
const baseURL = process.env.JOURNEYPILOT_APP_URL || '';
if (process.env.JP_SESSION_STATE_E2E === '1' && !/^http:\/\/127\.0\.0\.1:\d+$/.test(baseURL)) throw new Error('Offline suite requires an explicit loopback Vite URL');

type StreamHarness = { send: (events: unknown[]) => void; close: () => void };
type FixtureWindow = Window & { offlineStream?: StreamHarness; offlineStreams?: Record<string, StreamHarness>; __offlineChatBodies?: unknown[]; __offlineFailChatAttempts?: number; __offlineStaleGateOnce?: boolean };
type TerminalRunStatus = 'completed' | 'failed' | 'cancelled' | 'interrupted';

const STAGED_RESEARCH_STEPS = [
  { step_id: 'research-start', agent_name: '目的地调研', step_name: '查询景点与体验', content: '正在整理厦门的海岸步道与市区体验', timestamp: '2026-10-25T08:00:00Z', progress_status: 'running' },
  { step_id: 'place-result', agent_name: '目的地调研', step_name: '地点搜索', content: '', timestamp: '2026-10-25T08:00:01Z', is_tool_call: true, tool_name: 'global_place_search', tool_args: '{"query":"厦门 海岸步道"}', tool_result: '找到 3 个适合安排进行程的地点', tool_status: 'completed', result_preview: [{ title: '环岛路海岸步道', detail: '适合安排半天散步与骑行，可串联曾厝垵和音乐广场。', url: 'https://example.org/xiamen-coast' }] },
  { step_id: 'transport-start', agent_name: '交通查询', step_name: '查询往返交通', content: '正在比较深圳到厦门的火车方案', timestamp: '2026-10-25T08:00:02Z', progress_status: 'running' },
  { step_id: 'route-result', agent_name: '交通查询', step_name: '火车查询', content: '', timestamp: '2026-10-25T08:00:03Z', is_tool_call: true, tool_name: 'train_search', tool_args: '{"from_name":"深圳北","to_name":"厦门北","date":"2026-11-01"}', tool_result: '已整理往返车次与到站衔接', tool_status: 'completed' },
  { step_id: 'stay-start', agent_name: '住宿查询', step_name: '查询住宿', content: '正在筛选交通方便的住宿区域', timestamp: '2026-10-25T08:00:04Z', progress_status: 'running' },
];

function stagedResearchSteps(longChain: boolean) {
  if (!longChain) return STAGED_RESEARCH_STEPS;
  const rounds = Array.from({ length: 8 }, (_, round) => STAGED_RESEARCH_STEPS.map((step, index) => ({
    ...step,
    step_id: `${step.step_id}-r${round}`,
    timestamp: new Date(Date.parse('2026-10-25T08:00:00Z') + (round + 1) * 60_000 + index * 1_000).toISOString(),
  })));
  return [...STAGED_RESEARCH_STEPS, ...rounds.flat()];
}

async function offlineApp(page: Page, options: { bundle?: boolean; recovery?: boolean; delayedA?: boolean; research?: boolean; planGate?: boolean; specialParty?: boolean; longTrip?: boolean; notice?: boolean; noticeRestoreError?: boolean; bundleData?: ReturnType<typeof deliveryBundle>; terminalStatus?: TerminalRunStatus; resumable?: boolean; readOnlyHistory?: boolean; longChain?: boolean; memoryFact?: boolean } = {}) {
  const pageErrors: string[] = [], escapes: string[] = [], requests: string[] = [];
  let status: string = options.planGate
    ? 'awaiting_input'
    : options.terminalStatus ?? (options.bundle || options.noticeRestoreError ? 'completed' : 'running');
  let recovered = false, releaseA: (() => void) | undefined;
  let gateRevision = 0;
  let gateDetailUnavailable = false;
  let aReads = 0;
  // 恢复提示夹具：先保持 running 且无提示，触发后只放行一次终态窗口，随后连接保持中断。
  let noticeTriggered = false;
  let noticeTerminalPolls = 0;
  let noticeEventsHealthy = false;
  let noticeBundleMode: 'ok' | 'fail' = 'ok';
  let noticeBundleDelayMs = 0;
  const aWait = new Promise<void>(resolve => { releaseA = resolve; });
  const bundle = options.bundleData ?? deliveryBundle();
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.addInitScript(() => {
    if (localStorage.getItem('journeypilot.last-session-id') === null) {
      localStorage.setItem('journeypilot.last-session-id', 'A');
    }
    const originalFetch = window.fetch.bind(window);
    const fixtureWindow = window as FixtureWindow;
    fixtureWindow.__offlineChatBodies = [];
    fixtureWindow.offlineStreams = {};
    window.fetch = (input, init) => {
      const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
      if (url.pathname !== '/api/chat-stream') return originalFetch(input, init);
      let streamSession = 'new';
      try {
        const body = JSON.parse(String(init?.body ?? '{}'));
        fixtureWindow.__offlineChatBodies?.push(body);
        if (typeof body.session_id === 'string') streamSession = body.session_id;
      } catch { /* ignore non-JSON bodies */ }
      if (fixtureWindow.__offlineStaleGateOnce) {
        fixtureWindow.__offlineStaleGateOnce = false;
        return Promise.resolve(new Response(JSON.stringify({ detail: { code: 'plan_gate_version_stale', message: '计划版本已变化' } }), { status: 409, headers: { 'content-type': 'application/json' } }));
      }
      if ((fixtureWindow.__offlineFailChatAttempts ?? 0) > 0) {
        fixtureWindow.__offlineFailChatAttempts = (fixtureWindow.__offlineFailChatAttempts ?? 0) - 1;
        return Promise.resolve(new Response(JSON.stringify({ detail: '离线模拟提交失败' }), { status: 503, headers: { 'content-type': 'application/json' } }));
      }
      const encoder = new TextEncoder();
      const stream = new ReadableStream<Uint8Array>({ start(controller) {
        const handle: StreamHarness = {
          send(events) { for (const event of events) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`)); },
          close() { controller.close(); release(); },
        };
        const release = () => {
          if (fixtureWindow.offlineStream === handle) delete fixtureWindow.offlineStream;
          if (fixtureWindow.offlineStreams?.[streamSession] === handle) delete fixtureWindow.offlineStreams[streamSession];
        };
        fixtureWindow.offlineStream = handle;
        if (fixtureWindow.offlineStreams) fixtureWindow.offlineStreams[streamSession] = handle;
        init?.signal?.addEventListener('abort', () => { controller.error(new DOMException('Aborted', 'AbortError')); release(); }, { once: true });
      } });
      return Promise.resolve(new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } }));
    };
  });
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== baseURL) {
      if (/^https:\/\/webrd0[1-4]\.is\.autonavi\.com\/appmaptile/.test(url.href)) {
        await route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e9e8df"/></svg>' });
        return;
      }
      escapes.push(request.url());
      await route.abort('blockedbyclient');
      return;
    }
    if (!url.pathname.startsWith('/api/')) { await route.continue(); return; }
    requests.push(`${request.method()} ${url.pathname}${url.search}`);
    const json = async (body: unknown, code = 200) => route.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify(body) });
    const path = url.pathname.slice(4);
    if (path === '/user/sessions') return json(['A', 'B'].map(sessionSummary));
    if (/^\/user\/sessions\/[AB]$/.test(path)) {
      const id = path.at(-1)!;
      if (id === 'A' && ++aReads > 1 && options.delayedA) await aWait;
      return json(id === 'A' && options.research ? {
        ...sessionDetail(id),
        messages: [{
          id: 'research-message', role: 'assistant', content: '', display_content: '', timestamp: '2026-10-25T08:00:00Z',
          thinking_steps: stagedResearchSteps(options.longChain === true),
        }],
      } : sessionDetail(id));
    }
    if (path === '/trip-runs') {
      const id = url.searchParams.get('session_id');
      const hasRun = Boolean(options.bundle || options.recovery || options.planGate || options.notice || options.noticeRestoreError || options.terminalStatus);
      const runA = { run_id: 'run-A', session_id: 'A', status: options.notice && noticeTriggered ? 'completed' : status, title: '离线运行', mode: 'deep', created_at: '2026-10-25T08:00:00Z', updated_at: '2026-10-25T08:00:00Z' };
      const runB = { run_id: 'run-B', session_id: 'A', status: 'completed', title: '离线运行（较新）', mode: 'deep', created_at: '2026-10-26T08:00:00Z', updated_at: '2026-10-26T08:00:00Z' };
      const runs = id !== 'A' || !hasRun ? [] : options.readOnlyHistory ? [runB, runA] : [runA];
      return json({ runs, total: id === 'A' ? Math.max(1, runs.length) : 0 });
    }
    if (path === '/trip-runs/run-A' && gateDetailUnavailable) return json({ detail: '离线模拟计划读取失败' }, 503);
    if (path === '/trip-runs/run-A') return json({ run: { run_id: 'run-A', session_id: 'A', status: options.notice && noticeTriggered ? 'completed' : status }, state: { pending_user_choice: options.planGate ? {
      type: 'approval_gate', gate: 'plan', read_only: status === 'cancelled', terminal_status: status === 'cancelled' ? 'cancelled' : null,
      payload: { gate: 'plan', approval_token: `test-token-A-${gateRevision}`, revision: gateRevision, revision_limit: 2, decision_options: ['approve', 'supplement', 'cancel'], plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '安排适合放松的城市路线' } }] }, recognized_requirements: { hard: [], preferences: [{ requirement_id: 'slow', summary: '想慢一点，每天少走一些' }], attention: [] }, unresolved_requirement_ids: [] },
    } : null, latest_state_summary: {} }, execution: options.resumable ? { status: 'resume_available', last_heartbeat_at: null, lease_expires_at: null, last_safe_checkpoint_id: 'checkpoint-offline', recovery_reason: 'offline fixture' } : null, available_actions: options.resumable ? ['resume'] : [], events: [], controlled_trip_identity: { origin: { name: '北京' }, destinations: options.longTrip ? [{ name: '杭州市西湖风景名胜区与灵隐片区' }, { name: '苏州市平江路历史街区与园林群' }, { name: '南京市玄武湖与明城墙沿线' }] : [{ name: '西安' }], start_date: '2026-11-01', end_date: options.longTrip ? '2026-11-03' : '2026-11-02', party: options.specialParty ? { adults: 2, children: 1, elderly_companions: true, accessibility_required: true } : { adults: 1, children: 0, elderly_companions: false, accessibility_required: false }, style: options.longTrip ? { primary: '建筑、博物馆与本地生活', secondary_interests: ['咖啡与面包店', '安静街区散步', '无障碍优先'], source: 'current' } : { primary: '轻松', secondary_interests: ['当地美食'], source: 'current' } } });
    if (path === '/trip-runs/run-A/bundle/current') {
      if (options.noticeRestoreError) return json({ detail: '离线模拟正式结果不可用' }, 503);
      if (options.notice) {
        if (!noticeTriggered) return json({ detail: 'not ready' }, 404);
        if (noticeBundleDelayMs) await new Promise(resolve => setTimeout(resolve, noticeBundleDelayMs));
        if (noticeBundleMode === 'fail') return json({ detail: '离线模拟正式结果不可用' }, 503);
        return json(bundle);
      }
      return options.bundle || recovered ? json(bundle) : json({ detail: 'not ready' }, 404);
    }
    if (path === '/trip-runs/run-A/events') {
      const after = Number(url.searchParams.get('after_sequence'));
      if (options.noticeRestoreError) {
        return json({ run_id: 'run-A', requested_after_sequence: after, replay_floor_sequence: 1, latest_sequence: 0, next_after_sequence: after, window_expired: false, run_status: 'running', current_bundle_id: null, events: [] });
      }
      if (options.notice) {
        if (!noticeTriggered) {
          return json({ run_id: 'run-A', requested_after_sequence: after, replay_floor_sequence: 1, latest_sequence: 0, next_after_sequence: after, window_expired: false, run_status: 'running', current_bundle_id: null, events: [] });
        }
        if (!noticeEventsHealthy) {
          if (noticeTerminalPolls <= 0) return json({ detail: '离线模拟连接中断' }, 503);
          noticeTerminalPolls -= 1;
        }
        return json({ run_id: 'run-A', requested_after_sequence: after, replay_floor_sequence: 1, latest_sequence: 2, next_after_sequence: Math.max(after, 2), window_expired: false, run_status: 'completed', current_bundle_id: 'bundle-1',
          events: after < 2 ? [{ event_id: 2, run_id: 'run-A', sequence: 2, event_type: 'run.terminal', payload: { status: 'completed', bundle_id: 'bundle-1' }, created_at: '2026-10-25T08:00:00Z' }] : [] });
      }
      const ready = options.bundle || recovered;
      const terminalReady = ready && !options.planGate;
      return json({ run_id: 'run-A', requested_after_sequence: after, replay_floor_sequence: 1, latest_sequence: terminalReady ? 2 : 0, next_after_sequence: terminalReady ? Math.max(after, 2) : after, window_expired: false, run_status: options.planGate ? 'awaiting_input' : ready ? 'completed' : status, current_bundle_id: terminalReady ? 'bundle-1' : null,
        events: terminalReady && after < 2 ? [{ event_id: 2, run_id: 'run-A', sequence: 2, event_type: 'run.terminal', payload: { status: 'completed', bundle_id: 'bundle-1' }, created_at: '2026-10-25T08:00:00Z' }] : [] });
    }
    if (path === '/trip-runs/run-followup/events') {
      // 续聊产生的新 Run 只用于验证归属；离线窗口直接收口为失败，不要求新的 Bundle。
      const after = Number(url.searchParams.get('after_sequence'));
      return json({ run_id: 'run-followup', requested_after_sequence: after, replay_floor_sequence: 1, latest_sequence: 0, next_after_sequence: after, window_expired: false, run_status: 'failed', current_bundle_id: null, events: [] });
    }
    if (path === '/trip-runs/run-A/control') { expect(request.postDataJSON()).toEqual({ action: 'cancel', session_id: 'A' }); status = 'cancelled'; return json({ accepted: true, run_status: 'cancelled', message: '已取消' }); }
    if (path === '/trip-runs/run-A/supplements') return json({ accepted: true, status: 'pending', command_id: 'supplement-1', message: '已加入当前运行，将在下一个执行边界处理。' });
    if (path === '/trip-runs/run-A/bundle/current/weather/refresh') return json({ refresh_id: request.postDataJSON().refresh_id, attempted: false, committed: false, used_previous_values: true, refusal_reason: null, bundle });
    if (path === '/presets') return json([]);
    if (path === '/user/default-origin') return json({ place: null });
    if (path === '/product/trip-planner') return json({ primary_styles: [{ id: 'relaxed', label: '轻松', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 5000, inspiration_prompts: [] });
    if (path === '/knowledge/collections/travel_knowledge/stats') return json({ total: 0, sources: 0, source_details: [] });
    if (path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: options.memoryFact ? [{ fact_id: 'offline-fact', content: '偏好靠窗座位', source: 'manual', category: 'other' }] : [] });
    escapes.push(request.url()); return json({ detail: 'Unmocked API request' }, 501);
  });
  return {
    pageErrors,
    escapes,
    requests,
    releaseA: () => releaseA?.(),
    completeRecovery: () => { recovered = true; status = 'completed'; },
    recoverPlanGate: () => { options.planGate = true; status = 'awaiting_input'; },
    advancePlanGate: () => { gateRevision += 1; },
    setGateDetailUnavailable: (value: boolean) => { gateDetailUnavailable = value; },
    cancelPlanGate: () => { status = 'cancelled'; },
    triggerRecoveryNotice: (config: { bundle?: 'ok' | 'fail'; delayMs?: number } = {}) => {
      noticeTriggered = true;
      noticeTerminalPolls = 1;
      noticeBundleMode = config.bundle ?? 'ok';
      noticeBundleDelayMs = config.delayMs ?? 0;
    },
    setNoticeBundle: (mode: 'ok' | 'fail', delayMs = 0) => { noticeBundleMode = mode; noticeBundleDelayMs = delayMs; },
    restoreNoticeEvents: () => { noticeEventsHealthy = true; },
  };
}
async function sendFrames(page: Page, events: unknown[], close = false) {
  await page.evaluate(({ events, close }) => { const stream = (window as FixtureWindow).offlineStream; if (!stream) throw new Error('No mocked SSE stream'); stream.send(events); if (close) stream.close(); }, { events, close });
}
async function sendSessionFrames(page: Page, sessionId: string, events: unknown[], close = false) {
  await page.evaluate(({ sessionId, events, close }) => { const stream = (window as FixtureWindow).offlineStreams?.[sessionId]; if (!stream) throw new Error(`No mocked SSE stream for ${sessionId}`); stream.send(events); if (close) stream.close(); }, { sessionId, events, close });
}
async function selectSession(page: Page, id: string) {
  const mobile = page.getByTestId('sidebar-open');
  if (await mobile.isVisible()) await mobile.click();
  await page.getByRole('link', { name: '我的行程', exact: true }).click();
  const card = page.getByTestId(`trip-card-${id}`);
  await card.getByRole('button', { name: /打开对话|打开当前行程|继续这趟旅行/ }).click();
}
async function assertOffline(page: Page, fixture: Awaited<ReturnType<typeof offlineApp>>) {
  expect(fixture.pageErrors).toEqual([]); expect(fixture.escapes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await test.info().attach('offline-boundaries', { body: JSON.stringify(fixture, null, 2), contentType: 'application/json' });
}

const FOLLOWUP_EVIDENCE_DIR = '../test-results/e2e-evidence/workspace-followup-composer';

type ChatRequestBody = {
  session_id?: string | null;
  run_id?: string | null;
  route?: string | null;
  gate_decision?: unknown;
  messages?: Array<{ role?: string; content?: string; message_id?: string }>;
};

function sampleHandoffHeights(page: Page, durationMs = 520) {
  return page.getByTestId('generation-handoff').evaluate(async (element, duration) => {
    const samples: Array<{ at: number; height: number }> = [];
    const started = performance.now();
    await new Promise<void>((resolve) => {
      const tick = (now: number) => {
        samples.push({ at: Math.round(now - started), height: Math.round(element.getBoundingClientRect().height * 10) / 10 });
        if (now - started >= duration) resolve();
        else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    return samples;
  }, durationMs);
}

async function lastChatBody(page: Page): Promise<ChatRequestBody | null> {
  return page.evaluate(() => {
    const bodies = (window as FixtureWindow).__offlineChatBodies ?? [];
    return (bodies[bodies.length - 1] as ChatRequestBody | undefined) ?? null;
  });
}

async function followupComposerFacts(page: Page) {
  return page.evaluate(() => {
    const round = (value: number) => Math.round(value * 10) / 10;
    const box = (element: Element | null) => {
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return { top: round(rect.top), bottom: round(rect.bottom), left: round(rect.left), right: round(rect.right), width: round(rect.width), height: round(rect.height) };
    };
    const composer = document.querySelector<HTMLElement>('[data-testid="generation-followup-composer"]');
    const panel = document.querySelector<HTMLElement>('.research-panel-workspace');
    const inner = composer?.querySelector<HTMLElement>('.generation-followup-inner') ?? null;
    const body = document.querySelector<HTMLElement>('.generation-activity-body');
    const textarea = composer?.querySelector<HTMLTextAreaElement>('textarea') ?? null;
    const send = composer?.querySelector<HTMLButtonElement>('button[aria-label="发送"]') ?? null;
    return {
      composer: box(composer),
      panel: box(panel),
      inner: box(inner),
      composerPosition: composer ? getComputedStyle(composer).position : null,
      body: body ? {
        scrollTop: Math.round(body.scrollTop),
        scrollHeight: body.scrollHeight,
        clientHeight: body.clientHeight,
        overflowY: getComputedStyle(body).overflowY,
      } : null,
      activeInComposer: composer ? composer.contains(document.activeElement) : false,
      input: textarea ? { value: textarea.value, placeholder: textarea.placeholder } : null,
      send: send ? { ...box(send), disabled: send.disabled } : null,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      documentOverflow: document.documentElement.scrollWidth - window.innerWidth,
    };
  });
}

// 恢复提示是覆盖层：几何只取工作区布局与内部滚动容器，提示不得影响这两项。
type WorkspaceGeometry = {
  layout: { x: number; y: number; width: number; height: number; top: number; bottom: number };
  workspaceScrollTop: number | null;
  windowScrollY: number;
  topbarBottom: number;
  viewportWidth: number;
  viewportHeight: number;
};
const RECOVERY_EVIDENCE_DIR = '../test-results/e2e-evidence/floating-recovery-notice';
const recoveryBundleRequests = (fixture: Awaited<ReturnType<typeof offlineApp>>) =>
  fixture.requests.filter(request => request.startsWith('GET /api/trip-runs/run-A/bundle/current')).length;
async function workspaceGeometry(page: Page): Promise<WorkspaceGeometry> {
  return page.evaluate(() => {
    const layout = document.querySelector<HTMLElement>('[data-testid="trip-workspace-layout"]');
    if (!layout) throw new Error('workspace layout is missing');
    const rect = layout.getBoundingClientRect();
    const scroller = layout.querySelector<HTMLElement>('.generation-planning-sidebar');
    const topbar = document.querySelector<HTMLElement>('.app-topbar');
    const round = (value: number) => Math.round(value * 10) / 10;
    return {
      layout: { x: round(rect.x), y: round(rect.y), width: round(rect.width), height: round(rect.height), top: round(rect.top), bottom: round(rect.bottom) },
      workspaceScrollTop: scroller ? scroller.scrollTop : null,
      windowScrollY: window.scrollY,
      topbarBottom: round(topbar?.getBoundingClientRect().bottom ?? 0),
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    };
  });
}
async function recoveryNoticeFacts(page: Page) {
  return page.evaluate(() => {
    const notice = document.querySelector<HTMLElement>('[data-testid="delivery-recovery-notice"]');
    if (!notice) throw new Error('recovery notice is missing');
    const rect = notice.getBoundingClientRect();
    const style = getComputedStyle(notice);
    const message = notice.querySelector<HTMLElement>('[data-testid="delivery-recovery-notice-message"]');
    const retry = notice.querySelector<HTMLButtonElement>('button');
    const retryRect = retry?.getBoundingClientRect();
    const round = (value: number) => Math.round(value * 10) / 10;
    return {
      position: style.position,
      zIndex: style.zIndex,
      pointerEvents: style.pointerEvents,
      retryPointerEvents: retry ? getComputedStyle(retry).pointerEvents : null,
      top: round(rect.top), bottom: round(rect.bottom), left: round(rect.left), right: round(rect.right),
      width: round(rect.width), height: round(rect.height),
      role: notice.getAttribute('role'),
      ariaModal: notice.getAttribute('aria-modal'),
      ariaAtomic: notice.getAttribute('aria-atomic'),
      dialogCount: document.querySelectorAll('[role="dialog"]').length,
      messageOverflow: message ? message.scrollWidth - message.clientWidth : -1,
      messageHeight: message ? round(message.getBoundingClientRect().height) : -1,
      retry: retry && retryRect
        ? { disabled: retry.disabled, left: round(retryRect.left), right: round(retryRect.right), top: round(retryRect.top), bottom: round(retryRect.bottom), width: round(retryRect.width) }
        : null,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      documentOverflow: document.documentElement.scrollWidth - window.innerWidth,
    };
  });
}

// 相机证据取自真实地图状态：瓦片 z 是当前缩放级别，Marker 在容器中的屏幕坐标
// 覆盖平移与中心，map pane transform 一并留档；任一项变化都说明相机动过。
type MapCamera = {
  zoom: string[];
  pane: string | null;
  markers: Record<string, [number, number] | null>;
};
async function mapCamera(page: Page, markerIds: string[]): Promise<MapCamera> {
  return page.evaluate((ids) => {
    const map = document.querySelector('[data-testid="bundle-leaflet-map"]');
    if (!map) throw new Error('map container is missing');
    const mapBox = map.getBoundingClientRect();
    const markers: Record<string, [number, number] | null> = {};
    for (const id of ids) {
      const marker = map.querySelector(`[data-bundle-map-entity="${id}"]`);
      if (!marker) { markers[id] = null; continue; }
      const box = marker.getBoundingClientRect();
      markers[id] = [
        Math.round((box.x + box.width / 2 - mapBox.x) * 10) / 10,
        Math.round((box.y + box.height / 2 - mapBox.y) * 10) / 10,
      ];
    }
    const pane = map.querySelector('.leaflet-map-pane') as HTMLElement | null;
    const tileZooms = Array.from(map.querySelectorAll<HTMLImageElement>('.leaflet-tile'))
      .map(tile => /[?&]z=(\d+)/.exec(tile.src)?.[1])
      .filter((value): value is string => Boolean(value));
    const zoom = Array.from(new Set(tileZooms)).sort();
    return { zoom, pane: pane ? pane.style.transform : null, markers };
  }, markerIds);
}
async function settleMap(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
}
// 等到连续两次快照一致才取值，甩动惯性或拖动收尾都不算相机自己动。
async function settledCamera(page: Page, markerIds: string[]): Promise<MapCamera> {
  await expect.poll(async () => (await mapCamera(page, markerIds)).zoom.length, { timeout: 8000 }).toBeGreaterThan(0);
  let previous = await mapCamera(page, markerIds);
  for (let attempt = 0; attempt < 40; attempt += 1) {
    await page.waitForTimeout(100);
    const current = await mapCamera(page, markerIds);
    if (JSON.stringify(current) === JSON.stringify(previous)) return current;
    previous = current;
  }
  return previous;
}
async function expectCameraHeld(page: Page, expected: MapCamera, markerIds = Object.keys(expected.markers)) {
  await settleMap(page);
  expect(await mapCamera(page, markerIds), 'map camera must not move').toEqual(expected);
}

test('直接链接可打开列表中缺失的会话', async ({ page }) => {
  const fixture = await offlineApp(page);
  await page.route('**/api/user/sessions', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.goto('/?view=chat&session_id=A');
  await expect(page.getByText('A 的历史回答', { exact: true })).toBeVisible();
  await assertOffline(page, fixture);
});

test('restores persisted history and switches sessions without carrying the other answer', async ({ page }) => {
  const fixture = await offlineApp(page);
  await page.goto('/');
  await expect(page.getByText('A 的历史回答', { exact: true })).toBeVisible();
  await selectSession(page, 'B');
  await expect(page.getByText('B 的历史回答', { exact: true })).toBeVisible();
  await expect(page.getByText('A 的历史回答', { exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByText('B 的历史回答', { exact: true })).toBeVisible();
  await expect(page.getByText('A 的历史回答', { exact: true })).toHaveCount(0);
  await assertOffline(page, fixture);
});

test('rejects a stale history response after a newer session selection', async ({ page }) => {
  const fixture = await offlineApp(page, { delayedA: true });
  await page.goto('/');
  await expect(page.getByText('A 的历史回答', { exact: true })).toBeVisible();
  await selectSession(page, 'A');
  await selectSession(page, 'B');
  await expect(page.getByText('B 的历史回答', { exact: true })).toBeVisible();
  fixture.releaseA();
  await expect.poll(() => page.evaluate(() => localStorage.getItem('journeypilot.last-session-id'))).toBe('B');
  await expect(page.getByText('A 的历史回答', { exact: true })).toHaveCount(0);
  await assertOffline(page, fixture);
});

test('continues a hidden stream in its own cache and restores it while still streaming', async ({ page }) => {
  const fixture = await offlineApp(page);
  await page.goto('/');
  await expect(page.getByText('A 的历史回答', { exact: true })).toBeVisible();
  await page.getByTestId('brief-input').fill('离线回答测试');
  await page.getByTestId('send-button').click();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'chat_start', session_id: 'A', message_id: 'stream-A' }, { type: 'chat_chunk', content: 'A 可见草稿' }]);
  await expect(page.getByText('A 可见草稿', { exact: true })).toBeVisible();
  await expect(page.getByText('离线回答测试', { exact: true })).toBeVisible();
  await selectSession(page, 'B');
  await expect(page.getByText('B 的历史回答', { exact: true })).toBeVisible();
  await sendFrames(page, [{ type: 'chat_chunk', content: '，后台继续' }, { type: 'usage_update', run_id: 'run-A', call_id: 'offline-call', input_tokens: 10, output_tokens: 5, total_tokens: 15, cost_usd: 0.01 }]);
  await expect(page.getByText('A 可见草稿，后台继续', { exact: true })).toHaveCount(0);
  await selectSession(page, 'A');
  await expect(page.getByText('A 可见草稿，后台继续', { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'chat_complete', session_id: 'A', final_content: 'A 离线最终回答', run_status: 'completed' }], true);
  await expect(page.getByText('A 离线最终回答', { exact: true })).toBeVisible();
  await expect(page.getByTestId('send-button')).toHaveAttribute('data-streaming', 'false');
  await assertOffline(page, fixture);
});

test('不同会话并行发送时仍能返回第一条进行中的流', async ({ page }) => {
  await offlineApp(page);
  await page.goto('/');
  await expect(page.getByText('A 的历史回答', { exact: true })).toBeVisible();
  await page.getByTestId('brief-input').fill('会话 A 的问题');
  await page.getByTestId('send-button').click();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'chat_start', session_id: 'A', message_id: 'parallel-A' }, { type: 'chat_chunk', content: 'A 正在生成' }]);
  await expect(page.getByText('A 正在生成', { exact: true })).toBeVisible();
  await selectSession(page, 'B');
  await expect(page.getByText('B 的历史回答', { exact: true })).toBeVisible();
  await page.getByTestId('brief-input').fill('会话 B 的问题');
  await page.getByTestId('send-button').click();
  await expect.poll(() => page.evaluate(() => (window as FixtureWindow).__offlineChatBodies?.length)).toBe(2);
  await sendFrames(page, [{ type: 'chat_start', session_id: 'B', message_id: 'parallel-B' }, { type: 'chat_chunk', content: 'B 正在生成' }]);
  await sendSessionFrames(page, 'A', [{ type: 'chat_chunk', content: '，后台继续' }]);
  await selectSession(page, 'A');
  await expect(page.getByText('A 正在生成，后台继续', { exact: true })).toBeVisible();
  await page.getByTestId('send-button').click();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStreams?.A))).toBe(false);
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStreams?.B))).toBe(true);
  await selectSession(page, 'B');
  await expect(page.getByText('B 正在生成', { exact: true })).toBeVisible();
  await sendSessionFrames(page, 'B', [{ type: 'chat_complete', session_id: 'B', final_content: 'B 已完成', run_status: 'completed' }], true);
  await expect(page.getByText('B 已完成', { exact: true })).toBeVisible();
});

test('cancels through HTTP control and leaves the composer usable', async ({ page }) => {
  const fixture = await offlineApp(page);
  await page.goto('/');
  await expect(page.getByText('A 的历史回答', { exact: true })).toBeVisible();
  await page.getByTestId('brief-input').fill('离线取消测试'); await page.getByTestId('send-button').click();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'chat_start', session_id: 'A', message_id: 'cancel-A', run_id: 'run-A', route_decision: { route: 'trip_planning' } }, { type: 'agent_progress', agent_name: 'destination_researcher', content: '正在查找目的地资料', progress_status: 'running' }]);
  const workspace = page.getByTestId('generation-journey-panel');
  await expect(workspace.locator('.research-panel-title')).toHaveText('查找旅行资料');
  await expect(workspace.getByTestId('generation-followup-composer')).toHaveCount(0);
  await workspace.getByTestId('boarding-pass-stop').click();
  await expect(workspace.locator('.generation-progress > h2')).toHaveText('旅行规划已取消');
  await expect(workspace.getByRole('textbox', { name: '行程调整要求' })).toBeEditable();
  expect(fixture.requests.some(request => request.startsWith('POST /api/trip-runs/run-A/control'))).toBe(true);
  await workspace.locator('.generation-stage-button').filter({ hasText: '查找旅行资料' }).click();
  await expect(workspace.locator('.research-panel-title')).toHaveText('查找旅行资料');
  await expect(workspace.getByTestId('thinking-chain')).toBeVisible();
  await assertOffline(page, fixture);
});

test('completed planning without a bundle keeps a follow-up composer below the process', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  mkdirSync(FOLLOWUP_EVIDENCE_DIR, { recursive: true });
  const fixture = await offlineApp(page, { terminalStatus: 'completed', research: true, longChain: true });
  await page.goto('/');
  const workspace = page.getByTestId('generation-journey-panel');
  const composer = page.getByTestId('generation-followup-composer');
  await expect(workspace).toBeVisible();
  await expect(workspace.locator('.generation-progress > h2')).toHaveText('旅行规划已生成');
  await expect(page.getByTestId('delivery-recovery-notice')).toBeVisible();
  await expect(composer).toBeVisible();
  await expect(composer).toContainText('规划已生成');
  await expect(composer.getByTestId('brief-input')).toHaveValue('');
  const collapsedGroups = workspace.locator('.research-agent-heading[aria-expanded="false"]');
  expect(await collapsedGroups.count()).toBeGreaterThan(0);
  for (let remaining = await collapsedGroups.count(); remaining > 0; remaining -= 1) {
    await collapsedGroups.first().click();
  }
  await expect(collapsedGroups).toHaveCount(0);

  const initial = await followupComposerFacts(page);
  expect(initial.body?.scrollHeight ?? 0).toBeGreaterThan((initial.body?.clientHeight ?? 0) + 200);
  expect(initial.body?.scrollTop).toBe(0);
  expect(initial.activeInComposer).toBe(false);
  expect(initial.composerPosition).toBe('static');
  expect(initial.composer!.top).toBeGreaterThanOrEqual(0);
  expect(initial.composer!.bottom).toBeLessThanOrEqual(initial.viewport.height + 1);
  expect(initial.inner!.left).toBeLessThanOrEqual(initial.panel!.left + 16);
  expect(initial.inner!.left).toBeGreaterThanOrEqual(initial.panel!.left - 16);
  expect(initial.documentOverflow).toBe(0);
  await page.screenshot({ path: `${FOLLOWUP_EVIDENCE_DIR}/desktop-2000-completed-followup.png`, fullPage: true });

  // 滚动过程不应把 composer 推出视口，也不应该把焦点抢进输入框。
  await page.locator('.generation-activity-body').evaluate((element) => { element.scrollTop = element.scrollHeight; });
  const scrolled = await followupComposerFacts(page);
  expect(scrolled.body?.scrollTop ?? 0).toBeGreaterThan(0);
  expect(Math.abs(scrolled.composer!.top - initial.composer!.top)).toBeLessThanOrEqual(1);
  expect(scrolled.activeInComposer).toBe(false);
  await page.screenshot({ path: `${FOLLOWUP_EVIDENCE_DIR}/desktop-2000-completed-followup-scrolled.png`, fullPage: true });

  const textarea = composer.getByTestId('brief-input');
  await textarea.fill('第二天少安排一个景点，多留休息时间');
  await textarea.press('Enter');
  await expect(composer).toBeVisible();
  await expect.poll(() => page.evaluate(() => ((window as FixtureWindow).__offlineChatBodies ?? []).length)).toBe(1);
  const request = await lastChatBody(page);
  expect(request?.session_id).toBe('A');
  expect(request?.run_id).toBe('run-A');
  expect(request?.route).toBeNull();
  expect(request?.gate_decision ?? null).toBeNull();
  expect(request?.messages?.[0]?.content).toBe('第二天少安排一个景点，多留休息时间');

  // 发送后沿用真实 streaming 状态；新事件的 Run 身份归到新上下文。
  await sendFrames(page, [
    { type: 'chat_start', session_id: 'A', run_id: 'run-followup', message_id: 'followup', route_decision: { route: 'trip_planning' } },
    { type: 'thinking', message_id: 'followup', agent_name: '行程规划', step_name: '安排路线', content: '正在按新的休息要求重新安排路线', ts_ms: Date.now() },
  ]);
  await expect(workspace).toContainText('正在按新的休息要求重新安排路线');
  await expect(composer).toBeVisible();
  await sendFrames(page, [{ type: 'chat_complete', session_id: 'A', run_id: 'run-followup', final_content: '已按补充要求重新安排。', run_status: 'failed' }], true);
  await expect(composer).toBeVisible();
  expect(await page.evaluate(() => (window as FixtureWindow).__offlineChatBodies?.length ?? 0)).toBe(1);

  writeFileSync(`${FOLLOWUP_EVIDENCE_DIR}/followup-request.json`, JSON.stringify({
    post: '/api/chat-stream',
    count: 1,
    session_id: request?.session_id,
    run_id: request?.run_id,
    route: request?.route,
    gate_decision: request?.gate_decision ?? null,
    message: request?.messages?.[0]?.content,
  }, null, 2));
  writeFileSync(`${FOLLOWUP_EVIDENCE_DIR}/desktop-composer-geometry.json`, JSON.stringify({ initial, scrolled }, null, 2));
  await assertOffline(page, fixture);
});

for (const terminalStatus of ['failed', 'cancelled'] as const) {
  test(`${terminalStatus} planning keeps the follow-up composer and the real retry actions`, async ({ page }) => {
    await page.setViewportSize({ width: 2000, height: 880 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    mkdirSync(FOLLOWUP_EVIDENCE_DIR, { recursive: true });
    const fixture = await offlineApp(page, { terminalStatus, research: true });
    await page.goto('/');
    const workspace = page.getByTestId('generation-journey-panel');
    const composer = page.getByTestId('generation-followup-composer');
    await expect(workspace).toBeVisible();
    await expect(workspace.locator('.generation-progress > h2')).toHaveText(terminalStatus === 'failed' ? '旅行规划未完成' : '旅行规划已取消');
    await expect(composer).toBeVisible();
    await expect(composer.getByTestId('brief-input')).toBeVisible();
    await expect(workspace.getByTestId('boarding-pass-resume')).toHaveCount(0);
    await expect(workspace.getByRole('button', { name: '返回新旅行', exact: true })).toBeVisible();
    if (terminalStatus === 'failed') {
      await expect(composer).toContainText('没有完成');
      await page.screenshot({ path: `${FOLLOWUP_EVIDENCE_DIR}/desktop-2000-failed-followup.png`, fullPage: true });
    }
    await assertOffline(page, fixture);
  });
}

test('resumable interrupted planning keeps the dedicated resume path beside the composer', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  mkdirSync(FOLLOWUP_EVIDENCE_DIR, { recursive: true });
  const fixture = await offlineApp(page, { terminalStatus: 'interrupted', resumable: true, research: true });
  await page.goto('/');
  const workspace = page.getByTestId('generation-journey-panel');
  const composer = page.getByTestId('generation-followup-composer');
  await expect(workspace).toBeVisible();
  await expect(workspace.locator('.generation-progress > h2')).toHaveText('旅行规划已中断');
  await expect(composer).toBeVisible();
  await expect(composer).toContainText('从最近的位置继续');
  const resume = workspace.getByTestId('boarding-pass-resume');
  await expect(resume).toBeVisible();
  await page.screenshot({ path: `${FOLLOWUP_EVIDENCE_DIR}/desktop-2000-interrupted-followup.png`, fullPage: true });

  await resume.click();
  await expect.poll(() => page.evaluate(() => ((window as FixtureWindow).__offlineChatBodies ?? []).length)).toBe(1);
  const request = await lastChatBody(page);
  expect(request?.session_id).toBe('A');
  expect(request?.run_id).toBe('run-A');
  expect(request?.route).toBe('trip_refinement');
  expect(request?.messages?.[0]?.content).toBe('继续上次被中断的规划');
  await assertOffline(page, fixture);
});

test('read-only history run never mounts a writable follow-up composer', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { terminalStatus: 'completed', readOnlyHistory: true, research: true });
  await page.goto('/?session_id=A&run_id=run-A');
  const workspace = page.getByTestId('generation-journey-panel');
  await expect(workspace).toBeVisible();
  await expect(workspace.locator('.generation-readonly-note')).toHaveText('历史生成记录 · 只读');
  await expect(page.getByTestId('generation-followup-composer')).toHaveCount(0);
  await expect(page.getByTestId('brief-input')).toHaveCount(0);
  await assertOffline(page, fixture);
});

test('delivered trip adjustment keeps the single shared composer in the same workspace', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  mkdirSync(FOLLOWUP_EVIDENCE_DIR, { recursive: true });
  const fixture = await offlineApp(page, { bundle: true });
  await page.goto('/');
  await expect(page.getByTestId('interactive-itinerary')).toBeVisible();
  await expect(page.getByTestId('generation-followup-composer')).toHaveCount(0);
  await page.getByRole('button', { name: '调整', exact: true }).first().click();
  const conversation = page.locator('.journey-conversation-view');
  await expect(conversation).toBeVisible();
  await expect(page.locator('.journey-content-scene')).toHaveCount(1);
  await expect(conversation.getByTestId('brief-input')).toBeVisible();
  await page.screenshot({ path: `${FOLLOWUP_EVIDENCE_DIR}/desktop-2000-delivered-adjustment.png`, fullPage: true });

  await conversation.getByTestId('brief-input').fill('把第二天的晚餐换成清淡一点');
  await conversation.getByTestId('brief-input').press('Enter');
  await expect.poll(() => page.evaluate(() => ((window as FixtureWindow).__offlineChatBodies ?? []).length)).toBe(1);
  const request = await lastChatBody(page);
  expect(request?.session_id).toBe('A');
  expect(request?.run_id).toBe('run-A');
  expect(request?.route).toBeNull();
  expect(request?.messages?.[0]?.content).toBe('把第二天的晚餐换成清淡一点');
  await expect(page.getByTestId('generation-followup-composer')).toHaveCount(0);
  await sendFrames(page, [{ type: 'chat_start', session_id: 'A', run_id: 'run-followup', message_id: 'revision', route_decision: { route: 'trip_refinement' } }, { type: 'thinking', message_id: 'revision', agent_name: '行程规划', step_name: '安排路线', content: '正在调整行程' }]);
  await expect(conversation).toContainText('正在调整行程');
  await expect(page.getByTestId('itinerary-map-region')).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('adjustment-in-progress.png'), fullPage: true });
  await sendFrames(page, [{ type: 'run_failed', run_id: 'run-followup', message: '调整未完成，原行程仍可查看。' }], true);
  await expect(conversation.getByRole('alert')).toBeVisible();
  await expect(page.getByTestId('itinerary-map-region')).toBeVisible();
  await assertOffline(page, fixture);
});

for (const width of [390, 1440]) {
  test(`天气建议可在 ${width}px 带入行程调整对话`, async ({ page }) => {
    const bundle = deliveryBundle();
    bundle.workspace.weather_adjustments.push({
      proposal_id: 'rain-day-one', date: '2026-11-01', severity: 'high',
      summary: '降雨变化，建议调整 1 项安排', cost_delta_cny: null, time_delta_minutes: 20,
    });
    const fixture = await offlineApp(page, { bundle: true, bundleData: bundle });
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    if (width === 390) await page.getByTestId('canvas-pill').click();
    const suggestions = page.getByTestId('weather-suggestions');
    await expect(suggestions).toContainText('2026-11-01');
    await expect(suggestions).toContainText('降雨变化，建议调整 1 项安排');
    await suggestions.getByRole('button', { name: '讨论调整' }).click();
    const composer = page.locator('.journey-conversation-view').getByTestId('brief-input');
    await expect(composer).toBeFocused();
    await expect(composer).toHaveValue(/2026-11-01.*降雨变化，建议调整 1 项安排/);
    expect(await page.evaluate(() => (window as FixtureWindow).__offlineChatBodies?.length)).toBe(0);
    await composer.press('Enter');
    await expect.poll(async () => (await lastChatBody(page))?.messages?.[0]?.content).toContain('降雨变化，建议调整 1 项安排');
    expect((await lastChatBody(page))?.run_id).toBe('run-A');
    await sendFrames(page, [
      { type: 'chat_start', session_id: 'A', run_id: 'run-A', message_id: 'weather-adjustment', route_decision: { route: 'trip_refinement' } },
      gateFrame(),
    ]);
    await expect(page.getByTestId('trip-brief-plan-gate')).toBeVisible();
    await sendFrames(page, [{ type: 'run_failed', run_id: 'run-A', message: '调整未完成' }], true);
    await expect(page.locator('.journey-conversation-view').getByTestId('brief-input')).toHaveValue('');
    await assertOffline(page, fixture);
  });
}

test('取消同一会话的调整后，天气讨论使用仍可查看的父行程', async ({ page }) => {
  // 会话和 Run 身份与聊天入口的 UUIDv5 规则一致，调整 Run 属于同一会话并指向父 Run。
  const uuid5 = (name: string) => {
    const bytes = createHash('sha1')
      .update(Buffer.from('6ba7b8119dad11d180b400c04fd430c8', 'hex'))
      .update(name)
      .digest().subarray(0, 16);
    bytes[6] = (bytes[6] & 0x0f) | 0x50;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    return bytes.toString('hex');
  };
  const firstMessageId = randomUUID();
  const sessionHex = uuid5(`local:session:${firstMessageId}`);
  const sessionId = `${sessionHex.slice(0, 8)}-${sessionHex.slice(8, 12)}-${sessionHex.slice(12, 16)}-${sessionHex.slice(16, 20)}-${sessionHex.slice(20)}`;
  const runIdFor = (messageId: string) => `trip_${uuid5(`local:${sessionId}:${messageId}`)}`;
  const parentId = runIdFor(firstMessageId);
  const bundle = deliveryBundle();
  bundle.manifest.run_id = parentId;
  bundle.workspace.run_id = parentId;
  bundle.workspace.weather_adjustments.push({
    proposal_id: 'rain-day-one', date: '2026-11-01', severity: 'high',
    summary: '降雨变化，建议调整 1 项安排', cost_delta_cny: null, time_delta_minutes: 20,
  });
  const baseRun = {
    session_id: sessionId, mode: 'deep', title: '天气调整',
    created_at: '2026-10-25T08:00:00Z', updated_at: '2026-10-25T08:00:00Z',
  };
  const parent = { ...baseRun, run_id: parentId, parent_run_id: null, status: 'completed' as const, request_message_id: firstMessageId };
  const children: Array<typeof baseRun & { run_id: string; parent_run_id: string; status: 'running' | 'cancel_requested' | 'cancelled'; request_message_id: string }> = [];
  const cancelled: string[] = [];
  let showCancelledEvents = false;
  const fixture = await offlineApp(page);
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (url.pathname === '/api/user/sessions') return json([sessionSummary(sessionId)]);
    if (url.pathname === `/api/user/sessions/${sessionId}`) return json(sessionDetail(sessionId));
    if (url.pathname === '/api/trip-runs') {
      expect(url.searchParams.get('session_id')).toBe(sessionId);
      return json({ runs: [...[...children].reverse(), parent], total: children.length + 1 });
    }
    const match = /^\/api\/trip-runs\/([^/]+)(?:\/(.*))?$/.exec(url.pathname);
    if (!match) return route.fallback();
    const run = [parent, ...children].find((item) => item.run_id === match[1]);
    if (!run) return route.fallback();
    const suffix = match[2] ?? '';
    if (!suffix) return json({
      run, state: { pending_user_choice: null, latest_state_summary: {} }, execution: null,
      available_actions: [], events: [], controlled_trip_identity: {
        origin: { name: '北京' }, destinations: [{ name: '西安' }], start_date: '2026-11-01', end_date: '2026-11-02',
        party: { adults: 1, children: 0, elderly_companions: false, accessibility_required: false },
        style: { primary: '轻松', secondary_interests: [], source: 'current' },
      },
    });
    if (suffix === 'bundle/current') return run.run_id === parentId ? json(bundle) : json({ detail: 'not ready' }, 404);
    if (suffix === 'bundle/current/weather/refresh') return json({ refresh_id: request.postDataJSON().refresh_id, attempted: false, committed: false, used_previous_values: true, refusal_reason: null, bundle });
    if (suffix === 'events') {
      const after = Number(url.searchParams.get('after_sequence'));
      return json({
        run_id: run.run_id, requested_after_sequence: after, replay_floor_sequence: 1,
        latest_sequence: after, next_after_sequence: after, window_expired: false,
        run_status: run.status === 'cancelled' && !showCancelledEvents ? 'running' : run.status,
        current_bundle_id: run.run_id === parentId ? bundle.manifest.bundle_id : null, events: [],
      });
    }
    if (suffix === 'control') {
      const child = children.find((item) => item.run_id === run.run_id);
      expect(child).toBeDefined();
      expect(request.postDataJSON()).toEqual({ action: 'cancel', session_id: sessionId });
      child!.status = 'cancel_requested';
      cancelled.push(child!.run_id);
      return json({ run_id: child!.run_id, action: 'cancel', command_id: `cancel-${child!.run_id}`, accepted: true, status: 'pending', run_status: 'cancel_requested', message: '取消请求已记录' });
    }
    return route.fallback();
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(`/?session_id=${encodeURIComponent(sessionId)}`);
  await page.getByRole('button', { name: '调整', exact: true }).first().click();
  const conversation = page.locator('.journey-conversation-view');
  await conversation.getByTestId('brief-input').fill('把第二天的晚餐换清淡一点');
  await conversation.getByTestId('brief-input').press('Enter');
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  const firstRequest = await lastChatBody(page);
  expect(firstRequest?.session_id).toBe(sessionId);
  expect(firstRequest?.run_id).toBe(parentId);
  const firstChildId = runIdFor(firstRequest!.messages![0].message_id!);
  children.push({ ...baseRun, run_id: firstChildId, parent_run_id: parentId, status: 'running', request_message_id: firstRequest!.messages![0].message_id! });
  await sendFrames(page, [{ type: 'chat_start', session_id: sessionId, run_id: firstChildId, message_id: 'first-adjustment', route_decision: { route: 'trip_refinement' } }]);
  await expect(conversation.getByTestId('send-button')).toHaveAttribute('aria-label', '停止本次运行');
  await conversation.getByTestId('send-button').click();
  await expect.poll(() => cancelled).toEqual([firstChildId]);
  await expect(conversation.getByRole('textbox', { name: '行程调整要求' })).toBeVisible();
  await conversation.getByRole('button', { name: '返回日程' }).click();
  await page.getByTestId('weather-suggestions').getByRole('button', { name: '讨论调整' }).click();
  const stoppedComposer = conversation.getByRole('textbox', { name: '行程调整要求' });
  await expect(stoppedComposer).toHaveValue(/降雨变化/);
  await page.evaluate(() => { (window as FixtureWindow).__offlineFailChatAttempts = 3; });
  await stoppedComposer.press('Enter');
  await expect(conversation.getByTestId('retry-send').last()).toBeVisible();
  await expect(conversation.getByTestId('brief-input')).toHaveValue(/降雨变化/);
  expect((await lastChatBody(page))?.run_id).toBe(parentId);
  await conversation.getByTestId('retry-send').last().click();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  const retry = await lastChatBody(page);
  expect(retry?.session_id).toBe(sessionId);
  expect(retry?.run_id).toBe(parentId);
  const secondChildId = runIdFor(retry!.messages![0].message_id!);
  children.push({ ...baseRun, run_id: secondChildId, parent_run_id: parentId, status: 'running', request_message_id: retry!.messages![0].message_id! });
  await sendFrames(page, [{ type: 'chat_start', session_id: sessionId, run_id: secondChildId, message_id: 'weather-adjustment', route_decision: { route: 'trip_refinement' } }]);
  await conversation.getByTestId('brief-input').fill('');
  await expect(conversation.getByTestId('send-button')).toHaveAttribute('aria-label', '停止本次运行');
  await conversation.getByTestId('send-button').click();
  await expect.poll(() => cancelled).toEqual([firstChildId, secondChildId]);
  for (const child of children) child.status = 'cancelled';
  showCancelledEvents = true;
  await page.reload();
  await page.getByTestId('weather-suggestions').getByRole('button', { name: '讨论调整' }).click();
  await conversation.getByTestId('brief-input').press('Enter');
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  const restoredRequest = await lastChatBody(page);
  expect(restoredRequest?.session_id).toBe(sessionId);
  expect(restoredRequest?.run_id).toBe(parentId);
  expect(restoredRequest?.messages?.[0]?.content).toContain('降雨变化');
  await assertOffline(page, fixture);
});

test('只读行程展示天气建议但不提供调整入口', async ({ page }) => {
  const bundle = deliveryBundle();
  bundle.workspace.weather_adjustments.push({
    proposal_id: 'rain-day-one', date: '2026-11-01', severity: 'medium',
    summary: '降雨变化，建议调整 1 项安排', cost_delta_cny: null, time_delta_minutes: null,
  });
  const fixture = await offlineApp(page, { bundle: true, bundleData: bundle, readOnlyHistory: true });
  await page.goto('/?session_id=A&run_id=run-A');
  const suggestions = page.getByTestId('weather-suggestions');
  await expect(suggestions).toContainText('降雨变化');
  await expect(suggestions.getByRole('button', { name: '讨论调整' })).toHaveCount(0);
  await assertOffline(page, fixture);
});

test('phone terminal follow-up stays visible without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  mkdirSync(FOLLOWUP_EVIDENCE_DIR, { recursive: true });
  const fixture = await offlineApp(page, { terminalStatus: 'completed', research: true, longChain: true });
  await page.goto('/');
  const composer = page.getByTestId('generation-followup-composer');
  await expect(composer).toBeVisible();
  await composer.scrollIntoViewIfNeeded();
  const initial = await followupComposerFacts(page);
  expect(initial.documentOverflow).toBe(0);
  expect(initial.composer!.bottom).toBeLessThanOrEqual(initial.viewport.height + 1);
  expect(initial.send!.right).toBeLessThanOrEqual(initial.viewport.width + 1);
  await page.screenshot({ path: `${FOLLOWUP_EVIDENCE_DIR}/phone-390-completed-followup.png`, fullPage: true });

  // 软件键盘等效：焦点进入输入框并压缩视口后，输入与发送仍完整可见。
  const textarea = composer.getByTestId('brief-input');
  await textarea.focus();
  await page.setViewportSize({ width: 390, height: 500 });
  // 真实软键盘弹起时浏览器会把聚焦的输入框带回视口；这里做等价处理。
  await composer.scrollIntoViewIfNeeded();
  const focused = await followupComposerFacts(page);
  expect(focused.activeInComposer).toBe(true);
  expect(focused.documentOverflow).toBe(0);
  expect(focused.composer!.top).toBeGreaterThanOrEqual(0);
  expect(focused.composer!.bottom).toBeLessThanOrEqual(focused.viewport.height + 1);
  expect(focused.send!.width).toBeGreaterThan(0);
  expect(focused.send!.right).toBeLessThanOrEqual(focused.viewport.width + 1);
  await page.screenshot({ path: `${FOLLOWUP_EVIDENCE_DIR}/phone-390-completed-followup-keyboard.png`, fullPage: true });
  writeFileSync(`${FOLLOWUP_EVIDENCE_DIR}/phone-composer-geometry.json`, JSON.stringify({ initial, focused }, null, 2));
  await assertOffline(page, fixture);
});

test('phone pending plan gate keeps only the dedicated approval editor', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  mkdirSync(FOLLOWUP_EVIDENCE_DIR, { recursive: true });
  const fixture = await offlineApp(page, { planGate: true });
  await page.goto('/');
  await expect(page.getByTestId('trip-brief-plan-gate')).toBeVisible();
  await expect(page.getByTestId('generation-followup-composer')).toHaveCount(0);
  await expect(page.getByTestId('brief-input')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${FOLLOWUP_EVIDENCE_DIR}/phone-390-pending-gate.png`, fullPage: true });
  await assertOffline(page, fixture);
});

test('recovers durable delivery without a stream and keeps recovery mounted across navigation', async ({ page }) => {
  const fixture = await offlineApp(page, { recovery: true });
  await page.goto('/');
  await expect(page.getByTestId('generation-journey-panel')).toBeVisible();
  await expect(page.getByTestId('thinking-chain')).toBeVisible();
  await expect(page.getByTestId('thinking-chain').getByRole('button').first()).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByTestId('generation-journey-panel')).not.toContainText('每一步安排，都有据可查');
  await expect(page.getByText('规划过程', { exact: true })).toHaveCount(0);
  await expect(page.getByText('查看不同阶段的思考摘要、查询内容和已找到的旅行资料。', { exact: true })).toHaveCount(0);
  await expect(page.getByText('规划进度', { exact: true })).toHaveCount(0);
  await expect(page.getByText('正在整理这趟旅行的基本信息。', { exact: true })).toHaveCount(0);
  await expect(page.getByTestId('generation-journey-panel').locator('.generation-trip-card')).toBeVisible();
  await expect(page.getByTestId('generation-journey-panel').locator('.research-panel-workspace')).toBeVisible();
  await expect(page.getByTestId('generation-journey-panel').locator('.generation-progress')).toHaveAttribute('data-active', 'false');
  await expect(page.getByTestId('generation-journey-panel')).not.toContainText('责任');
  await expect(page.getByTestId('itinerary-map-region')).toHaveCount(0);
  await expect(page.getByTestId('bundle-leaflet-map')).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath('desktop-generation-workspace.png'), fullPage: true });
  await page.getByRole('link', { name: '偏好与资料', exact: true }).click();
  await page.getByRole('link', { name: '资料来源', exact: true }).click();
  await expect(page.getByRole('heading', { name: '资料来源', exact: true })).toBeVisible();
  fixture.completeRecovery();
  await expect.poll(() => fixture.requests.filter(request => request.startsWith('GET /api/trip-runs/run-A/bundle/current')).length).toBeGreaterThan(1);
  await selectSession(page, 'A');
  await expect(page.getByTestId('interactive-itinerary')).toBeVisible();
  await page.getByRole('button', { name: '阅读版', exact: true }).click();
  await expect(page.getByTestId('full-report')).toBeVisible();
  await expect(page.getByText('离线旅行报告', { exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('desktop-session-report.png'), fullPage: true });
  await assertOffline(page, fixture);
});

test('浮动的恢复提示不改变工作区几何、滚动位置与键盘焦点', async ({ page }) => {
  // 先用较矮的视口让规划工作区真实可滚，再回到反馈尺寸截图。
  await page.setViewportSize({ width: 2000, height: 560 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { notice: true, research: true });
  mkdirSync(RECOVERY_EVIDENCE_DIR, { recursive: true });
  await page.goto('/');
  const notice = page.getByTestId('delivery-recovery-notice');
  await expect(page.getByTestId('generation-journey-panel')).toBeVisible();
  await expect(notice).toHaveCount(0);
  const disclosure = page.getByTestId('thinking-chain').getByRole('button').first();
  await disclosure.focus();
  await expect(disclosure).toBeFocused();
  await page.evaluate(() => {
    const scroller = document.querySelector<HTMLElement>('.generation-planning-sidebar');
    if (!scroller) throw new Error('generation planning sidebar is missing');
    scroller.scrollTop = 240;
  });
  await page.waitForTimeout(100);
  const before = await workspaceGeometry(page);
  expect(before.workspaceScrollTop).toBeGreaterThan(0);
  expect(before.layout.top).toBe(before.topbarBottom);
  expect(Math.abs(before.layout.height - (before.viewportHeight - before.topbarBottom))).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${RECOVERY_EVIDENCE_DIR}/desktop-scroll-before-notice.png`, fullPage: true });

  // 同一 Run 下由“无提示”进入正式结果恢复：先出现 loading，再恢复完成。
  const bundleRequestsBefore = recoveryBundleRequests(fixture);
  fixture.triggerRecoveryNotice({ bundle: 'ok', delayMs: 5000 });
  await expect(notice).toBeVisible();
  await expect(notice).toContainText('正在重新加载这趟旅行…');
  const during = await workspaceGeometry(page);
  const facts = await recoveryNoticeFacts(page);
  await page.screenshot({ path: `${RECOVERY_EVIDENCE_DIR}/desktop-scroll-during-notice.png`, fullPage: true });
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.screenshot({ path: `${RECOVERY_EVIDENCE_DIR}/desktop-2000-loading-notice.png`, fullPage: true });

  // 提示出现不改变工作区矩形、顶部位置与滚动位置。
  expect(during).toEqual(before);
  expect(facts.position).toBe('absolute');
  expect(facts.zIndex).toBe('1150');
  // 非交互提示内容不接收指针事件；只有重试按钮可点，框下工作区保持可操作。
  expect(facts.pointerEvents).toBe('none');
  expect(facts.retryPointerEvents).toBe('auto');
  expect(facts.role).toBe('alert');
  expect(facts.ariaAtomic).toBe('true');
  expect(facts.ariaModal).toBeNull();
  expect(facts.dialogCount).toBe(0);
  expect(facts.documentOverflow).toBeLessThanOrEqual(0);
  expect(facts.left).toBeGreaterThanOrEqual(0);
  expect(facts.right).toBeLessThanOrEqual(facts.viewport.width);
  expect(facts.height).toBeLessThanOrEqual(60);
  // 非模态：焦点没被抢，框外原有按钮照常可用，loading 时不重复提交。
  await expect(disclosure).toBeFocused();
  const retry = notice.getByRole('button', { name: '重试', exact: true });
  await expect(retry).toBeDisabled();
  const expandedBefore = await disclosure.getAttribute('aria-expanded');
  await disclosure.click();
  await expect(disclosure).toHaveAttribute('aria-expanded', expandedBefore === 'true' ? 'false' : 'true');
  await expect(page.getByTestId('interactive-itinerary')).toBeVisible({ timeout: 15000 });
  await expect(notice).toHaveCount(0);
  expect(recoveryBundleRequests(fixture)).toBe(bundleRequestsBefore + 1);
  writeFileSync(`${RECOVERY_EVIDENCE_DIR}/desktop-geometry.json`, JSON.stringify({ beforeNotice: before, duringNotice: during, notice: facts }, null, 2));
  await assertOffline(page, fixture);
});

test('浮动的恢复提示在桌面与手机上非模态，重试单次提交并在恢复后消失', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { notice: true, research: true });
  mkdirSync(RECOVERY_EVIDENCE_DIR, { recursive: true });
  await page.goto('/');
  const notice = page.getByTestId('delivery-recovery-notice');
  await expect(page.getByTestId('generation-journey-panel')).toBeVisible();
  await expect(notice).toHaveCount(0);
  const before = await workspaceGeometry(page);

  // 已完成规划、正式结果恢复失败：连接中断提示。
  fixture.triggerRecoveryNotice({ bundle: 'fail' });
  await expect(notice).toContainText('正在重新加载这趟旅行…');
  await expect(notice).toContainText('连接中断，正在从已保存的旅行结果恢复。', { timeout: 15000 });
  const desktopDuring = await workspaceGeometry(page);
  const desktopFacts = await recoveryNoticeFacts(page);
  expect(desktopDuring).toEqual(before);
  expect(desktopFacts.position).toBe('absolute');
  expect(desktopFacts.zIndex).toBe('1150');
  expect(desktopFacts.pointerEvents).toBe('none');
  expect(desktopFacts.retryPointerEvents).toBe('auto');
  expect(desktopFacts.documentOverflow).toBeLessThanOrEqual(0);
  expect(desktopFacts.height).toBeLessThanOrEqual(60);
  await page.screenshot({ path: `${RECOVERY_EVIDENCE_DIR}/desktop-2000-completed-recovery-notice.png`, fullPage: true });

  // 手机：长提示换行，重试可见可点，无横向溢出，且不越出工作区。
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(notice).toBeVisible();
  await expect.poll(async () => (await recoveryNoticeFacts(page)).zIndex).toBe('1050');
  const phoneDuring = await workspaceGeometry(page);
  const phoneFacts = await recoveryNoticeFacts(page);
  expect(phoneFacts.position).toBe('absolute');
  expect(phoneFacts.zIndex).toBe('1050');
  expect(phoneFacts.documentOverflow).toBeLessThanOrEqual(0);
  expect(phoneFacts.messageOverflow).toBeLessThanOrEqual(1);
  expect(phoneFacts.messageHeight).toBeGreaterThan(24);
  expect(phoneFacts.left).toBeGreaterThanOrEqual(0);
  expect(phoneFacts.right).toBeLessThanOrEqual(phoneFacts.viewport.width);
  expect(phoneFacts.retry).not.toBeNull();
  expect(phoneFacts.retry!.width).toBeGreaterThan(0);
  expect(phoneFacts.retry!.left).toBeGreaterThanOrEqual(phoneFacts.left);
  expect(phoneFacts.retry!.right).toBeLessThanOrEqual(phoneFacts.right);
  expect(phoneFacts.retry!.right).toBeLessThanOrEqual(phoneFacts.viewport.width);
  expect(phoneDuring.layout.top).toBe(phoneDuring.topbarBottom);
  expect(Math.abs(phoneDuring.layout.height - (phoneDuring.viewportHeight - phoneDuring.topbarBottom))).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${RECOVERY_EVIDENCE_DIR}/phone-390-recovery-notice.png`, fullPage: true });

  // 键盘可到达重试，名称完整；框外全局导航仍可操作，提示不压住抽屉。
  const retry = notice.getByRole('button', { name: '重试', exact: true });
  await retry.focus();
  await expect(retry).toBeFocused();
  await page.getByTestId('sidebar-open').click();
  const drawer = page.getByTestId('app-sidebar');
  await expect(drawer).toHaveClass(/is-open/);
  await expect(page.getByTestId('sidebar-open')).toHaveAttribute('aria-expanded', 'true');
  // 提示的层级低于导航抽屉：打开全局导航时不会被浮框压住。
  expect(await page.evaluate(() => {
    const noticeNode = document.querySelector<HTMLElement>('[data-testid="delivery-recovery-notice"]');
    const drawerNode = document.querySelector<HTMLElement>('[data-testid="app-sidebar"]');
    const zIndex = (node: HTMLElement | null) => Number(getComputedStyle(node!).zIndex) || 0;
    return zIndex(drawerNode) > zIndex(noticeNode);
  })).toBe(true);
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveClass(/is-closed/);
  await expect(page.getByTestId('sidebar-open')).toHaveAttribute('aria-expanded', 'false');
  await expect(notice).toBeVisible();

  // 重试请求只提交一次：loading 时按钮禁用，失败后仍只有一次新请求。
  fixture.setNoticeBundle('fail', 900);
  const requestsBeforeRetry = recoveryBundleRequests(fixture);
  await retry.click();
  await expect(notice).toContainText('正在重新加载这趟旅行…');
  await expect(retry).toBeDisabled();
  expect(recoveryBundleRequests(fixture)).toBe(requestsBeforeRetry + 1);
  await expect(notice).toContainText('连接中断，正在从已保存的旅行结果恢复。', { timeout: 15000 });
  expect(recoveryBundleRequests(fixture)).toBe(requestsBeforeRetry + 1);

  // 恢复成功后仍由原有状态清除提示；连接恢复后提示不会再次弹出。
  fixture.setNoticeBundle('ok');
  await retry.click();
  await expect(page.getByTestId('canvas-pill')).toBeVisible({ timeout: 15000 });
  await expect(notice).toHaveCount(0);
  fixture.restoreNoticeEvents();
  const eventRequests = () => fixture.requests.filter(request => request.startsWith('GET /api/trip-runs/run-A/events')).length;
  const eventsBeforeReconnect = eventRequests();
  await expect.poll(eventRequests, { timeout: 10000 }).toBeGreaterThan(eventsBeforeReconnect);
  await expect(notice).toHaveCount(0);
  await expect(page.getByTestId('canvas-pill')).toBeVisible();
  writeFileSync(`${RECOVERY_EVIDENCE_DIR}/phone-geometry.json`, JSON.stringify({ desktopBefore: before, desktopDuring, desktopNotice: desktopFacts, phoneDuring, phoneNotice: phoneFacts }, null, 2));
  await assertOffline(page, fixture);
});

test('已完成规划的恢复提示浮在工作区上方且不占高度', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { noticeRestoreError: true, research: true });
  mkdirSync(RECOVERY_EVIDENCE_DIR, { recursive: true });
  await page.goto('/');
  const notice = page.getByTestId('delivery-recovery-notice');
  const panel = page.getByTestId('generation-journey-panel');
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('heading', { name: '旅行规划已生成', exact: true })).toBeVisible();
  await expect(notice).toContainText('暂时无法加载这趟旅行的正式结果，请稍后重试。');
  const geometry = await workspaceGeometry(page);
  const facts = await recoveryNoticeFacts(page);
  // 提示占高时工作区会变短；这里直接验证工作区仍然是整块可用高度。
  expect(geometry.layout.top).toBe(geometry.topbarBottom);
  expect(Math.abs(geometry.layout.height - (geometry.viewportHeight - geometry.topbarBottom))).toBeLessThanOrEqual(1);
  expect(facts.position).toBe('absolute');
  expect(facts.zIndex).toBe('1150');
  expect(facts.documentOverflow).toBeLessThanOrEqual(0);
  expect(facts.right).toBeLessThanOrEqual(facts.viewport.width);
  await page.screenshot({ path: `${RECOVERY_EVIDENCE_DIR}/desktop-2000-completed-recovery-error.png`, fullPage: true });
  writeFileSync(`${RECOVERY_EVIDENCE_DIR}/desktop-completed-geometry.json`, JSON.stringify({ geometry, notice: facts }, null, 2));
  await assertOffline(page, fixture);
});

test('restores staged research with formatted tool calls and results', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { recovery: true, research: true });
  await page.goto('/');
  const workspace = page.getByTestId('generation-journey-panel');
  const destination = workspace.getByTestId('research-agent-destination');
  await expect(destination.getByRole('button')).toHaveCount(1);
  await expect(destination.getByRole('button')).toHaveAttribute('aria-expanded', 'false');
  await expect(destination.locator('.research-agent-body')).toHaveCount(0);
  await destination.getByRole('button').click();
  await expect(destination).toContainText('找到 3 个适合安排进行程的地点');
  await expect(destination.getByTestId('research-agent-update')).toHaveCount(0);
  await destination.getByTestId('research-query').locator('summary').click();
  await expect(destination.locator('[data-detail-section="input"]')).toContainText('厦门 海岸步道');
  await expect(destination).not.toContainText('返回 3 条结果');
  await expect(workspace.getByRole('link', { name: '环岛路海岸步道' })).toBeVisible();
  const transport = workspace.getByTestId('research-agent-transport');
  await expect(transport.locator('.research-agent-body')).toHaveCount(0);
  await transport.getByRole('button').click();
  await expect(transport).toContainText('已整理往返车次与到站衔接');
  await transport.getByTestId('research-query').locator('summary').click();
  await expect(transport.locator('[data-detail-section="input"]')).toContainText('深圳北');
  await expect(transport.locator('[data-detail-section="input"]')).toContainText('厦门北');
  await expect(workspace.getByTestId('research-agent-stay')).toContainText('已结束');
  await expect(workspace.getByTestId('research-agent-stay')).not.toContainText('正在筛选交通方便的住宿区域');
  await page.screenshot({ path: test.info().outputPath('desktop-generation-research.png'), fullPage: true });
  await assertOffline(page, fixture);
});

test('plan gate stays inside the generation workspace through revise retry and approve', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { planGate: true });
  await page.goto('/');
  const workspace = page.getByTestId('generation-journey-panel');
  const gate = page.getByTestId('trip-brief-plan-gate');
  const sidebar = workspace.locator('.generation-planning-sidebar');
  await expect(workspace).toBeVisible();
  await expect(sidebar.locator('.generation-trip-card')).toBeVisible();
  await expect(workspace.locator('.generation-progress > h2')).toHaveText('等待确认研究方案');
  await expect(gate).toBeVisible();
  await expect(gate).toContainText('安排适合放松的城市路线');
  await expect(gate.locator('.plan-gate-header > p')).toHaveCount(0);
  await expect(gate.locator('.plan-gate-header > span')).toHaveCount(0);
  await expect(gate.locator('.plan-gate-context')).toHaveCount(0);
  await expect(gate.locator('.plan-gate-plan-note')).toHaveCount(0);
  await expect(gate.locator('.plan-gate-actions > p')).toHaveCount(0);
  await expect(sidebar.locator('.generation-trip-card')).toContainText('1 位成人');
  await expect(sidebar.locator('.generation-trip-card')).toContainText('当地美食');
  await expect(page.getByRole('heading', { name: '确认这趟旅行', exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '接下来，我们会这样安排', exact: true })).toHaveCount(0);
  await sidebar.evaluate(node => node.setAttribute('data-mount-probe', 'kept'));
  await page.screenshot({ path: '../test-results/e2e-evidence/unified-planning-workspace/workspace-2000-pending-gate.png', fullPage: true });

  await gate.getByRole('button', { name: '补充或调整旅行要求', exact: true }).click();
  const guide = gate.getByLabel('想改哪里？');
  await guide.fill('每天只安排一个主要景点，午后留出休息时间');
  await page.screenshot({ path: '../test-results/e2e-evidence/unified-planning-workspace/workspace-2000-gate-editing.png', fullPage: true });
  await page.evaluate(() => { (window as FixtureWindow).__offlineFailChatAttempts = 3; });
  await gate.getByTestId('plan-gate-supplement').click();
  await expect(gate.getByRole('alert')).toContainText('旅行信息和修改已保留');
  await expect(gate.getByRole('alert')).toBeFocused();
  await expect(guide).toHaveValue('每天只安排一个主要景点，午后留出休息时间');
  await expect(sidebar).toHaveAttribute('data-mount-probe', 'kept');

  await gate.getByTestId('plan-gate-supplement').click();
  await expect.poll(() => page.evaluate(() => {
    const bodies = (window as FixtureWindow).__offlineChatBodies ?? [];
    return (bodies[bodies.length - 1] as { gate_decision?: { action?: string; content?: string } } | undefined)?.gate_decision;
  })).toEqual({ action: 'supplement', content: '每天只安排一个主要景点，午后留出休息时间', approval_token: 'test-token-A-0' });
  await sendFrames(page, [
    { type: 'chat_start', session_id: 'A', run_id: 'run-A', message_id: 'gate-supplement', route_decision: { route: 'trip_refinement' } },
    { type: 'approval_gate_raised', run_id: 'run-A', gate: 'plan', run_status: 'awaiting_input', payload: { gate: 'plan', approval_token: 'test-token-A-1', revision: 1, revision_limit: 2, decision_options: ['approve', 'supplement', 'cancel'], plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '每天只安排一个主要景点' } }] }, recognized_requirements: { hard: [], preferences: [{ requirement_id: 'slow', summary: '每天只安排一个主要景点' }], attention: [] }, unresolved_requirement_ids: [] } },
    { type: 'chat_complete', run_id: 'run-A', run_status: 'awaiting_input', ts_ms: Date.now() },
  ], true);
  await expect(gate).toContainText('每天只安排一个主要景点');
  await expect(guide).toHaveValue('');
  await expect(sidebar).toHaveAttribute('data-mount-probe', 'kept');
  await expect(workspace.locator('.generation-progress > h2')).toHaveText('等待确认研究方案');

  await gate.getByRole('button', { name: '确认并开始生成', exact: true }).click();
  await expect.poll(() => page.evaluate(() => {
    const bodies = (window as FixtureWindow).__offlineChatBodies ?? [];
    return (bodies[bodies.length - 1] as { gate_decision?: { action?: string } } | undefined)?.gate_decision?.action;
  })).toBe('approve');
  expect((await lastChatBody(page))?.gate_decision).toEqual({ action: 'approve', content: '', approval_token: 'test-token-A-1' });
  await sendFrames(page, [
    { type: 'chat_start', session_id: 'A', run_id: 'run-A', message_id: 'gate-approve', route_decision: { route: 'trip_refinement' } },
    { type: 'thinking', message_id: 'gate-approve', agent_name: '行程规划', content: '正在把景点和交通排进每天路线', step_name: '安排路线', ts_ms: Date.now() },
  ]);
  await expect(gate).toHaveCount(0);
  await expect(workspace.locator('.research-panel-title')).toHaveText('安排每天路线');
  await expect(sidebar).toHaveAttribute('data-mount-probe', 'kept');
  await expect(sidebar.locator('.generation-trip-card')).toBeVisible();
  await page.screenshot({ path: '../test-results/e2e-evidence/unified-planning-workspace/workspace-2000-approved-research.png', fullPage: true });
  await assertOffline(page, fixture);
});

test('cancel keeps the current run workspace and restores a pending gate on phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { planGate: true });
  await page.goto('/');
  const workspace = page.getByTestId('generation-journey-panel');
  const gate = page.getByTestId('trip-brief-plan-gate');
  await expect(gate).toBeVisible();
  await expect(workspace.locator('.generation-trip-card')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: '../test-results/e2e-evidence/unified-planning-workspace/workspace-390-pending-gate.png', fullPage: true });

  await page.setViewportSize({ width: 2000, height: 880 });
  await page.reload();
  await expect(gate).toBeVisible();
  await expect(workspace.locator('.generation-progress > h2')).toHaveText('等待确认研究方案');
  const sidebar = workspace.locator('.generation-planning-sidebar');
  await sidebar.evaluate(node => node.setAttribute('data-mount-probe', 'kept'));

  await gate.getByRole('button', { name: '取消规划', exact: true }).click();
  await expect.poll(() => page.evaluate(() => {
    const bodies = (window as FixtureWindow).__offlineChatBodies ?? [];
    return (bodies[bodies.length - 1] as { gate_decision?: { action?: string } } | undefined)?.gate_decision?.action;
  })).toBe('cancel');
  expect((await lastChatBody(page))?.gate_decision).toEqual({ action: 'cancel', content: '' });
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'run_cancelled', run_id: 'run-A', final_content: '已取消当前规划。', ts_ms: Date.now() }]);
  await expect(gate).toHaveCount(0);
  await expect(workspace).toBeVisible();
  await expect(sidebar).toHaveAttribute('data-mount-probe', 'kept');
  await expect(workspace.locator('.generation-progress > h2')).toHaveText('旅行规划已取消');
  await expect(page.getByText('这次规划已取消。', { exact: true })).toBeVisible();
  await expect(page.getByTestId('new-trip-hero')).toHaveCount(0);
  await page.screenshot({ path: '../test-results/e2e-evidence/unified-planning-workspace/workspace-2000-cancelled.png', fullPage: true });
  await assertOffline(page, fixture);
});

test('narrow plan gate keeps actions visible and party conditions readable through reload and approve', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { planGate: true, specialParty: true });
  const assertGateGeometry = async () => {
    const gate = page.getByTestId('trip-brief-plan-gate');
    const geometry = await gate.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const actions = element.querySelector('.plan-gate-actions') as HTMLElement;
      const buttons = Array.from(actions.querySelectorAll('button')).map((button) => {
        const rect = button.getBoundingClientRect();
        return { left: rect.left, right: rect.right, width: rect.width };
      });
      return {
        boxLeft: box.left,
        boxRight: box.right,
        overflow: element.scrollWidth - element.clientWidth,
        actionOverflow: actions.scrollWidth - actions.clientWidth,
        buttons,
        viewport: window.innerWidth,
      };
    });
    expect(geometry.overflow).toBeLessThanOrEqual(1);
    expect(geometry.actionOverflow).toBeLessThanOrEqual(1);
    expect(geometry.buttons.length).toBeGreaterThanOrEqual(2);
    for (const button of geometry.buttons) {
      expect(button.width).toBeGreaterThan(0);
      expect(button.left).toBeGreaterThanOrEqual(geometry.boxLeft - 1);
      expect(button.right).toBeLessThanOrEqual(geometry.boxRight + 1);
      expect(button.right).toBeLessThanOrEqual(geometry.viewport + 1);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  };

  for (const width of [640, 660, 768]) {
    await page.setViewportSize({ width, height: 900 });
    if (width === 640) await page.goto('/');
    else await page.reload();
    const gate = page.getByTestId('trip-brief-plan-gate');
    const workspace = page.getByTestId('generation-journey-panel');
    await expect(gate).toBeVisible();
    await expect(gate.locator('.plan-gate-context')).toHaveCount(0);
    await expect(workspace.locator('.generation-trip-card')).toContainText('1 位儿童');
    await expect(workspace.locator('.generation-trip-card')).toContainText('有长辈同行');
    await expect(workspace.locator('.generation-trip-card')).toContainText('需要无障碍安排');
    await expect(gate.getByRole('button', { name: '确认并开始生成', exact: true })).toBeVisible();
    await expect(gate.getByRole('button', { name: '确认并开始生成', exact: true })).toBeEnabled();
    await expect(gate.getByRole('button', { name: '取消规划', exact: true })).toBeVisible();
    await expect(gate.getByRole('button', { name: '取消规划', exact: true })).toBeEnabled();
    await assertGateGeometry();
    if (width === 640) await page.screenshot({ path: '../test-results/e2e-evidence/unified-planning-workspace/workspace-640-pending-gate-special.png', fullPage: true });
    await gate.getByRole('button', { name: '补充或调整旅行要求', exact: true }).click();
    const guide = gate.getByLabel('想改哪里？');
    await guide.fill('每天少走一些，预留无障碍休息点');
    await expect(gate.getByTestId('plan-gate-supplement')).toBeVisible();
    await expect(gate.getByTestId('plan-gate-supplement')).toBeEnabled();
    await assertGateGeometry();
    await guide.fill('');
  }

  await page.setViewportSize({ width: 640, height: 900 });
  await page.reload();
  const gate = page.getByTestId('trip-brief-plan-gate');
  const workspace = page.getByTestId('generation-journey-panel');
  await expect(gate).toBeVisible();
  await expect(gate.locator('.plan-gate-context')).toHaveCount(0);
  await expect(workspace.locator('.generation-trip-card')).toContainText('1 位儿童');
  await expect(workspace.locator('.generation-trip-card')).toContainText('有长辈同行');
  await expect(workspace.locator('.generation-trip-card')).toContainText('需要无障碍安排');
  await gate.getByRole('button', { name: '确认并开始生成', exact: true }).click();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [
    { type: 'chat_start', session_id: 'A', run_id: 'run-A', message_id: 'special-party-approve', route_decision: { route: 'trip_refinement' } },
    { type: 'thinking', message_id: 'special-party-approve', agent_name: '行程规划', content: '正在安排每天路线并预留休息点', step_name: '安排路线', ts_ms: Date.now() },
  ]);
  await expect(gate).toHaveCount(0);
  await expect(workspace.locator('.generation-trip-card')).toContainText('1 位儿童');
  await expect(workspace.locator('.generation-trip-card')).toContainText('有长辈同行');
  await expect(workspace.locator('.generation-trip-card')).toContainText('需要无障碍安排');
  await assertOffline(page, fixture);
});

test('handoff expands from compact requirements to the plan gate and collapses only after server state clears', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  const evidence = '../test-results/e2e-evidence/gate-handoff-motion';
  mkdirSync(evidence, { recursive: true });
  const fixture = await offlineApp(page, { terminalStatus: 'failed', research: true });
  await page.goto('/');
  const workspace = page.getByTestId('generation-journey-panel');
  const handoff = page.getByTestId('generation-handoff');
  const gate = page.getByTestId('trip-brief-plan-gate');
  const process = page.getByTestId('thinking-chain');
  const composer = page.getByTestId('generation-followup-composer');
  await expect(composer).toBeVisible();
  const input = composer.getByTestId('brief-input');
  await input.fill('继续完善这趟旅行');
  await input.press('Enter');
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await expect(process.getByRole('button').first()).toHaveAttribute('aria-expanded', 'false');
  await expect(handoff).toHaveAttribute('data-phase', 'process');

  await sendFrames(page, [
    { type: 'chat_start', session_id: 'A', run_id: 'run-A', message_id: 'handoff-live', route_decision: { route: 'trip_refinement' } },
    { type: 'agent_progress', agent_name: 'requirements_preparer', content: '正在整理旅行需求', progress_status: 'running' },
  ]);
  await expect(workspace.locator('.research-panel-title')).toHaveText('整理旅行需求');
  await expect(workspace.locator('.generation-progress li.is-active .generation-stage-title')).toHaveText('整理旅行需求');
  await expect(handoff).toHaveAttribute('data-phase', 'process');
  await page.screenshot({ path: `${evidence}/desktop-2000-handoff-compact.png`, fullPage: true });
  const compactHeight = await handoff.evaluate((element) => element.getBoundingClientRect().height);

  const expanding = sampleHandoffHeights(page);
  await sendFrames(page, [{
    type: 'approval_gate_raised', run_id: 'run-A', gate: 'plan', run_status: 'awaiting_input',
    payload: {
      gate: 'plan', approval_token: 'test-token-A-0', revision: 0, revision_limit: 1,
      decision_options: ['approve', 'supplement', 'cancel'],
      plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '查清本次目的地与同行要求' } }] },
      plan_text: '**研究重点**：查清本次目的地的建筑与本地生活，并核对同行通行条件。',
      recognized_requirements: { hard: [], preferences: [{ requirement_id: 'slow', summary: '想慢一点，每天少走一些' }] },
    },
  }, { type: 'chat_complete', run_id: 'run-A', run_status: 'awaiting_input', ts_ms: Date.now() }], true);
  await expect(gate).toBeVisible();
  await page.waitForTimeout(80);
  await page.screenshot({ path: `${evidence}/desktop-2000-handoff-expanding.png`, fullPage: true });
  const expansionFrames = await expanding;
  await expect(handoff).toHaveAttribute('data-phase', 'gate');
  const openHeight = await handoff.evaluate((element) => element.getBoundingClientRect().height);
  expect(openHeight).toBeGreaterThan(compactHeight + 80);
  expect(expansionFrames.some((frame) => frame.height > compactHeight + 3)).toBe(true);
  expect(expansionFrames.some((frame) => frame.height > compactHeight + 8 && frame.height < openHeight - 8)).toBe(true);
  expect(expansionFrames.at(-1)!.height).toBeGreaterThan(openHeight - 8);
  await page.screenshot({ path: `${evidence}/desktop-2000-handoff-gate.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(gate).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${evidence}/phone-390-handoff-gate.png`, fullPage: true });
  await page.setViewportSize({ width: 2000, height: 880 });

  await gate.getByRole('button', { name: '确认并开始生成', exact: true }).click();
  await expect.poll(() => page.evaluate(() => {
    const bodies = (window as FixtureWindow).__offlineChatBodies ?? [];
    return (bodies[bodies.length - 1] as { gate_decision?: { action?: string } } | undefined)?.gate_decision?.action;
  })).toBe('approve');
  // 点击以及打开新流都不是服务端确认；门仍在。
  await expect(gate).toBeVisible();
  await expect(handoff).toHaveAttribute('data-phase', 'gate');
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);

  await sendFrames(page, [{ type: 'chat_start', session_id: 'A', run_id: 'run-A', message_id: 'handoff-approved', route_decision: { route: 'trip_refinement' } }]);
  await expect(handoff).toHaveAttribute('data-phase', 'gate');
  const collapsing = sampleHandoffHeights(page);
  await sendFrames(page, [{ type: 'thinking', message_id: 'handoff-approved', agent_name: 'planner', step_name: '准备研究', content: '正在准备研究计划', ts_ms: Date.now() }]);
  const collapseFrames = await collapsing;
  await expect(handoff).toHaveAttribute('data-phase', 'process');
  await expect(gate).toHaveCount(0);
  await expect(workspace.locator('.research-panel-title')).toHaveText('整理旅行需求');
  await expect(process.getByRole('button').first()).toBeFocused();
  const collapsedHeight = await handoff.evaluate((element) => element.getBoundingClientRect().height);
  expect(collapsedHeight).toBeLessThan(openHeight - 80);
  expect(collapseFrames.some((frame) => frame.height < openHeight - 3)).toBe(true);
  expect(collapseFrames.some((frame) => frame.height < openHeight - 8 && frame.height > collapsedHeight + 8)).toBe(true);
  await page.screenshot({ path: `${evidence}/desktop-2000-handoff-collapsed.png`, fullPage: true });

  await sendFrames(page, [{ type: 'thinking', message_id: 'handoff-approved', agent_name: '目的地调研', step_name: '地点搜索', content: '正在核对本次目的地的建筑与本地生活', ts_ms: Date.now(), progress_status: 'running' }]);
  await expect(workspace.locator('.research-panel-title')).toHaveText('查找旅行资料');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(handoff).toHaveAttribute('data-phase', 'process');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${evidence}/phone-390-handoff-process.png`, fullPage: true });
  await assertOffline(page, fixture);
});

test('handoff reaches restored and reduced-motion targets without a residual size transition', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const evidence = '../test-results/e2e-evidence/gate-handoff-motion';
  mkdirSync(evidence, { recursive: true });
  const fixture = await offlineApp(page, { planGate: true });
  await page.goto('/');
  const handoff = page.getByTestId('generation-handoff');
  const gate = page.getByTestId('trip-brief-plan-gate');
  await expect(gate).toBeVisible();
  await expect(handoff).toHaveAttribute('data-phase', 'gate');
  await expect(handoff).toHaveClass(/is-instant/);
  const durations = await handoff.locator('.generation-handoff-gate').evaluate((element) => {
    const style = getComputedStyle(element);
    return { duration: style.transitionDuration, delay: style.transitionDelay };
  });
  expect(durations.duration.split(',').every((value) => value.trim() === '0s')).toBe(true);
  await expect(gate.getByRole('heading', { name: '确认研究方案', exact: true })).toBeFocused();
  await page.screenshot({ path: `${evidence}/desktop-2000-handoff-restored-reduced.png`, fullPage: true });

  const before = await handoff.evaluate((element) => element.getBoundingClientRect().height);
  await gate.getByRole('button', { name: '取消规划', exact: true }).click();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'run_cancelled', run_id: 'run-A', final_content: '已取消当前规划。', ts_ms: Date.now() }]);
  await expect(gate).toHaveCount(0);
  const after = await handoff.evaluate((element) => element.getBoundingClientRect().height);
  expect(after).toBeLessThan(before - 80);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(handoff).toHaveAttribute('data-phase', 'process');
  // 空过程终态不再渲染重复标题的 ThinkingChain，只保留左侧状态与后续输入。
  await expect(page.getByTestId('thinking-chain')).toHaveCount(0);
  await expect(page.locator('.generation-progress > h2')).toHaveText('旅行规划已取消');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${evidence}/phone-390-handoff-cancelled-reduced.png`, fullPage: true });
  await assertOffline(page, fixture);
});

test('trip card integrates companions and style with route facts across desktop and phone', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const evidence = '../test-results/e2e-evidence/trip-card-layout';
  mkdirSync(evidence, { recursive: true });
  const fixture = await offlineApp(page, { planGate: true, specialParty: true, longTrip: true });
  await page.goto('/');
  const workspace = page.getByTestId('generation-journey-panel');
  const card = workspace.locator('.generation-trip-card');
  const facts = card.locator('.generation-trip-card-meta');
  await expect(card).toContainText('杭州市西湖风景名胜区与灵隐片区');
  await expect(card).toContainText('苏州市平江路历史街区与园林群');
  await expect(card).toContainText('南京市玄武湖与明城墙沿线');
  await expect(card).toContainText('3 日');
  await expect(card).toContainText('北京出发');
  await expect(card).toContainText('2 位成人');
  await expect(card).toContainText('1 位儿童');
  await expect(card).toContainText('有长辈同行');
  await expect(card).toContainText('需要无障碍安排');
  await expect(card).toContainText('建筑、博物馆与本地生活');
  await expect(card).toContainText('咖啡与面包店');
  await expect(card).toContainText('安静街区散步');
  await expect(card).toContainText('无障碍优先');
  const desktop = await facts.evaluate((element) => {
    const cardBox = element.closest('.generation-trip-card')!.getBoundingClientRect();
    const rows = Array.from(element.children).map((row) => {
      const box = row.getBoundingClientRect();
      return { top: box.top, bottom: box.bottom, left: box.left, right: box.right };
    });
    return { cardLeft: cardBox.left, cardRight: cardBox.right, rows, overflow: element.scrollWidth - element.clientWidth };
  });
  expect(desktop.overflow).toBeLessThanOrEqual(1);
  for (const row of desktop.rows) {
    expect(row.left).toBeGreaterThanOrEqual(desktop.cardLeft - 1);
    expect(row.right).toBeLessThanOrEqual(desktop.cardRight + 1);
  }
  expect(desktop.rows[0].top).toBeLessThan(desktop.rows[1].top);
  expect(desktop.rows[1].top).toBeLessThan(desktop.rows[2].top);
  await page.screenshot({ path: `${evidence}/desktop-2000-trip-card-long.png`, fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(card).toContainText('杭州市西湖风景名胜区与灵隐片区');
  const phone = await card.evaluate((element) => {
    const box = element.getBoundingClientRect();
    return { left: box.left, right: box.right, overflow: element.scrollWidth - element.clientWidth, viewport: window.innerWidth };
  });
  expect(phone.overflow).toBeLessThanOrEqual(1);
  expect(phone.left).toBeGreaterThanOrEqual(0);
  expect(phone.right).toBeLessThanOrEqual(phone.viewport + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${evidence}/phone-390-trip-card-long.png`, fullPage: true });
  await assertOffline(page, fixture);
});

test('delivered trip refinement gate keeps party context and actions inside the narrow conversation', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { bundle: true, planGate: true, specialParty: true });
  await page.goto('/');
  await expect(page.getByTestId('interactive-itinerary')).toBeVisible();
  await page.getByRole('button', { name: '调整', exact: true }).first().click();
  const gate = page.getByTestId('trip-brief-plan-gate');
  await expect(gate).toBeVisible();
  const tripCard = page.locator('.journey-conversation-view .generation-trip-card');
  await expect(tripCard).toContainText('2 位成人');
  await expect(tripCard).toContainText('1 位儿童');
  await expect(tripCard).toContainText('有长辈同行');
  await expect(tripCard).toContainText('需要无障碍安排');
  const geometry = await gate.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const actions = element.querySelector('.plan-gate-actions') as HTMLElement;
    return {
      width: box.width,
      overflow: element.scrollWidth - element.clientWidth,
      actionOverflow: actions.scrollWidth - actions.clientWidth,
      buttons: Array.from(actions.querySelectorAll('button')).map((button) => {
        const rect = button.getBoundingClientRect();
        return { left: rect.left, right: rect.right, width: rect.width };
      }),
      boxLeft: box.left,
      boxRight: box.right,
    };
  });
  expect(geometry.width).toBeLessThan(440);
  expect(geometry.overflow).toBeLessThanOrEqual(1);
  expect(geometry.actionOverflow).toBeLessThanOrEqual(1);
  for (const button of geometry.buttons) {
    expect(button.width).toBeGreaterThan(0);
    expect(button.left).toBeGreaterThanOrEqual(geometry.boxLeft - 1);
    expect(button.right).toBeLessThanOrEqual(geometry.boxRight + 1);
  }
  const approve = gate.getByRole('button', { name: '确认并开始生成', exact: true });
  const cancel = gate.getByRole('button', { name: '取消规划', exact: true });
  await expect(approve).toBeEnabled();
  await expect(cancel).toBeEnabled();
  await page.screenshot({ path: '../test-results/e2e-evidence/unified-planning-workspace/bundle-adjustment-gate-1280.png', fullPage: true });
  await gate.locator('.plan-gate-actions').scrollIntoViewIfNeeded();
  await expect(approve).toBeVisible();
  await expect(cancel).toBeVisible();
  expect(await gate.locator('.plan-gate-actions').evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return rect.top >= 0 && rect.bottom <= window.innerHeight;
  })).toBe(true);
  await page.screenshot({ path: '../test-results/e2e-evidence/unified-planning-workspace/bundle-adjustment-gate-actions-1280.png', fullPage: true });
  await assertOffline(page, fixture);
});

test('phone restores the bundle without opening a sheet and navigates between lazy pages', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const fixture = await offlineApp(page, { bundle: true });
  await page.goto('/');
  await expect(page.getByTestId('canvas-pill')).toBeVisible();
  await expect(page.getByRole('button', { name: '阅读版', exact: true })).toHaveCount(0);
  await page.getByTestId('canvas-pill').click();
  await page.getByTestId('canvas-sheet').getByRole('button', { name: '阅读版', exact: true }).click();
  await expect(page.getByTestId('full-report')).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('phone-session-report.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await page.getByTestId('sidebar-open').click();
  await page.getByRole('link', { name: '旅行风格', exact: true }).click();
  await expect(page.getByRole('heading', { name: '旅行风格', exact: true })).toBeVisible();
  await page.getByTestId('sidebar-open').click();
  await page.getByTestId('app-sidebar').getByRole('link', { name: '我的偏好', exact: true }).click();
  await expect(page.getByRole('heading', { name: '我的偏好', exact: true })).toBeVisible();
  await assertOffline(page, fixture);
});

test('modal completes closing and restores focus to its opener', async ({ page }) => {
  const fixture = await offlineApp(page);
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto('/');
  await page.getByRole('link', { name: '偏好与资料', exact: true }).click();
  await page.getByRole('link', { name: '资料来源', exact: true }).click();
  const opener = page.getByRole('button', { name: '添加文本', exact: true });
  await opener.click();
  const dialog = page.getByRole('dialog', { name: '添加旅行资料', exact: true });
  await expect(dialog).toBeVisible();
  await expect.poll(() => dialog.evaluate((node) => getComputedStyle(node).transform)).toBe('none');
  await page.screenshot({ path: test.info().outputPath('modal-open.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  await assertOffline(page, fixture);
});

for (const width of [390, 1280]) {
  test(`date picker closes and restores focus at ${width}px`, async ({ page }) => {
    const fixture = await offlineApp(page);
    await page.setViewportSize({ width, height: 844 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.goto('/');
    await expect(page.getByText('A 的历史回答', { exact: true })).toBeVisible();
    await page.getByRole('link', { name: 'JourneyPilot 新旅行', exact: true }).click();
    const structuredTab = page.getByRole('tab', { name: '按条件规划' });
    await structuredTab.click();
    await expect(structuredTab).toHaveAttribute('aria-selected', 'true');
    const skip = page.getByRole('button', { name: '暂时不用默认值', exact: true });
    const originInput = page.getByRole('textbox', { name: '从哪里出发' });
    await expect(skip.or(originInput)).toBeVisible();
    if (await skip.count()) await skip.click();
    await expect(originInput).toBeVisible();
    const opener = page.getByTestId('date-range-trigger');
    await opener.click();
    const dialog = page.getByTestId('date-range-dialog');
    await expect(dialog).toBeVisible();
    await expect.poll(() => dialog.evaluate((node) => getComputedStyle(node).opacity)).toBe('1');
    await expect.poll(() => dialog.evaluate((node) => getComputedStyle(node).transform)).toBe('none');
    if (width === 390) {
      await expect.poll(() => dialog.evaluate((node) => node.getBoundingClientRect().bottom)).toBe(844);
    } else {
      const secondMonthVisible = await dialog.evaluate((node) => {
        const month = node.querySelectorAll('section')[1];
        if (!month) return false;
        const rect = month.getBoundingClientRect();
        const hit = document.elementFromPoint(rect.right - 4, rect.top + 4);
        return hit !== null && node.contains(hit);
      });
      expect(secondMonthVisible).toBe(true);
    }
    await page.screenshot({ path: test.info().outputPath(`date-picker-${width}.png`), fullPage: true });
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
    await assertOffline(page, fixture);
  });
}

test('phone sheet closes with Escape and restores the canvas entry', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto('/');
  const opener = page.getByTestId('canvas-pill');
  await expect(opener).toBeVisible();
  await opener.click();
  await expect(page.getByTestId('canvas-sheet')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('canvas-sheet')).toHaveCount(0);
  await expect(opener).toBeFocused();
  await assertOffline(page, fixture);
});

test('concise delivery keeps unlocated stops and one reason without listing gaps across views', async ({ page }) => {
  const bundle = structuredClone(deliveryBundle());
  const evidenceDir = '../test-results/e2e-evidence/generation-05-concise-delivery';
  const reason = '适合慢步游览。';
  const museum = bundle.workspace.itinerary.visit_stops.find((stop) => stop.item_id === 'visit-shaanxi-museum')!;
  museum.latitude = null;
  museum.longitude = null;
  museum.selection_reason = reason;
  bundle.map_projection.content.places = bundle.map_projection.content.places.map((place) => (
    place.entity_ref.entity_id === museum.item_id ? { ...place, latitude: null, longitude: null } : place
  ));
  for (const route of bundle.map_projection.content.routes) {
    for (const segment of route.segments) {
      for (const endpoint of [segment.from_endpoint, segment.to_endpoint]) {
        if (endpoint.place_id === museum.place_id) {
          Object.assign(endpoint, { latitude: null, longitude: null });
        }
      }
    }
  }
  const block = bundle.report_projection.document.days[1].blocks.find((item) => item.entity_ref.entity_id === museum.item_id)!;
  block.summary = reason;
  block.details.node_summary = null;
  block.details.price_label = null;
  bundle.report_projection.document.unresolved = ['晚间游船暂未安排'];
  bundle.workspace.itinerary.unresolved = ['晚间游船暂未安排'];
  const fixture = await offlineApp(page, { bundle: true, bundleData: bundle });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await expect(page.getByText('晚间游船暂未安排')).toHaveCount(0);
  await page.getByTestId('day-summary-card-day-2').click();
  const occurrence = page.locator('[data-itinerary-occurrence="d2-museum"]');
  await expect(occurrence).toContainText(reason);
  await expect(occurrence.getByRole('button', { name: '在地图查看' })).toHaveCount(0);
  await expect(page.locator('[data-bundle-map-entity="visit-yongning-gate"]')).toBeVisible();
  await occurrence.getByRole('button', { name: '查看详情' }).click();
  await expect(occurrence.getByText(reason, { exact: true })).toHaveCount(1);
  await page.waitForTimeout(500);
  mkdirSync(evidenceDir, { recursive: true });
  writeFileSync(`${evidenceDir}/fixture-bundle.json`, JSON.stringify(bundle, null, 2));
  await page.screenshot({ path: `${evidenceDir}/concise-desktop-itinerary.png`, fullPage: true });
  await page.getByRole('button', { name: '阅读版', exact: true }).click();
  const report = page.getByTestId('full-report');
  await expect(report.getByText(reason, { exact: true })).toHaveCount(1);
  await expect(report).not.toContainText('晚间游船暂未安排');
  await expect(report).not.toContainText('费用按行程逐项列出');
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${evidenceDir}/concise-desktop-report.png`, fullPage: true });
  await page.reload();
  await expect(page.getByText('晚间游船暂未安排')).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId('bundle-leaflet-map')).toBeVisible();
  await page.getByRole('button', { name: '第 2 天', exact: true }).click();
  await expect(page.locator('[data-bundle-map-entity="visit-yongning-gate"]')).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${evidenceDir}/concise-phone-map.png`, fullPage: true });
  await assertOffline(page, fixture);
});

test('reading and map remain usable through an animated round trip', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto('/');
  await expect(page.getByTestId('interactive-itinerary')).toBeVisible();
  await page.getByRole('button', { name: '阅读版', exact: true }).click();
  await expect(page.getByTestId('full-report')).toBeVisible();
  await page.getByRole('button', { name: '返回地图', exact: true }).click();
  await expect(page.getByTestId('interactive-itinerary')).toBeVisible();
  await expect(page.getByTestId('full-report')).toHaveCount(0);
  await assertOffline(page, fixture);
});

test('desktop itinerary cards and map stay linked across hover, selection, days and layers', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await expect(page.locator('.journey-title-row h1')).toHaveText('西安两日 · 秦唐风物');
  await expect(page.locator('.journey-sidebar-header > p').first()).toContainText('西安 · 2 天');
  await expect(page.getByTestId('itinerary-card-flow')).toHaveCount(0);
  await expect(page.getByTestId('day-summary-card-day-1')).toBeVisible();
  await page.getByTestId('day-summary-card-day-1').click();
  // 场景切换期间，退出的全程内容会短暂与当天内容共存；等退场结束且当前场景唯一后再取容器。
  const currentScene = page.locator('.journey-content-scene:not([aria-hidden="true"])');
  await expect(currentScene).toHaveCount(1);
  await expect(page.getByTestId('interactive-itinerary')).toHaveCount(1);
  await expect(page.locator('[data-itinerary-occurrence]')).toHaveCount(7);
  await expect(page.locator('[data-bundle-map-entity]')).toHaveCount(4);
  await expect(page.locator('.leaflet-overlay-pane path[data-route-entity]')).toHaveCount(3);
  await expect(page.locator('.leaflet-overlay-pane path[data-route-geometry="provider"]')).toHaveCount(2);
  await expect(page.locator('.leaflet-overlay-pane path[data-route-geometry="endpoint"]')).toHaveCount(1);
  expect(await page.locator('[data-itinerary-occurrence]').evaluateAll(nodes => nodes.slice(0, 7).map(node => node.getAttribute('data-entity-id')))).toEqual([
    'visit-terracotta', 'leg-terracotta-lunch', 'dining-lintong', 'leg-lunch-dayan', 'visit-dayan', 'leg-dayan-hotel', 'stay-bell-tower',
  ]);
  expect(await page.locator('.leaflet-overlay-pane path').evaluateAll(paths => paths.flatMap(path => path.getAnimations()).length)).toBe(0);

  const terracotta = page.locator('[data-itinerary-occurrence="d1-terracotta"]');
  const dayan = page.locator('[data-itinerary-occurrence="d1-dayan"]');
  const marker = page.locator('[data-bundle-map-entity="visit-terracotta"]');
  const dayanMarker = page.locator('[data-bundle-map-entity="visit-dayan"]');
  const map = page.getByTestId('bundle-leaflet-map');
  const mapTrigger = terracotta.getByRole('button', { name: '在地图查看', exact: true });
  const detail = page.getByTestId('map-place-detail');
  const initialCamera = await settledCamera(page, ['visit-terracotta', 'visit-dayan']);
  expect(initialCamera.zoom).toHaveLength(1);
  const contentScroll = currentScene.getByTestId('interactive-itinerary');
  const scrollBefore = await contentScroll.evaluate(node => node.scrollTop);

  // 没有选中项：连续 hover 地点卡与路线只联动高亮，相机和详情都不动。
  await terracotta.hover();
  await expect(marker).toHaveAttribute('data-linked', 'on');
  await expect(terracotta).toHaveAttribute('data-linked', 'on');
  await expectCameraHeld(page, initialCamera);
  expect(await contentScroll.evaluate(node => node.scrollTop)).toBe(scrollBefore);

  await dayan.hover();
  await expect(dayanMarker).toHaveAttribute('data-linked', 'on');
  await expect(marker).not.toHaveAttribute('data-linked', 'on');
  await expect(dayan).toHaveAttribute('data-linked', 'on');
  await expectCameraHeld(page, initialCamera);
  await expect(page.getByRole('button', { name: '第 1 天', exact: true })).toHaveAttribute('aria-pressed', 'true');

  const routePoint = await page.locator('.leaflet-overlay-pane path[data-route-segment="segment-terracotta-lunch"]').evaluate((path) => {
    const element = path as SVGPathElement;
    const point = element.getPointAtLength(element.getTotalLength() / 2);
    const matrix = element.getScreenCTM();
    if (!matrix) throw new Error('route has no screen matrix');
    return { x: matrix.a * point.x + matrix.c * point.y + matrix.e, y: matrix.b * point.x + matrix.d * point.y + matrix.f };
  });
  await page.mouse.move(routePoint.x, routePoint.y);
  await expect(page.locator('[data-itinerary-occurrence="d1-transfer-lunch"]')).toHaveAttribute('data-linked', 'on');
  await expectCameraHeld(page, initialCamera);
  await page.mouse.move(4, 4);
  await expectCameraHeld(page, initialCamera);
  await expect(detail).toHaveCount(0);

  // 地图 Marker 的 hover 也只联动高亮，与卡片 hover 同一边界。
  await marker.hover();
  await expect(terracotta).toHaveAttribute('data-linked', 'on');
  await expectCameraHeld(page, initialCamera);

  // 显式点击才定位并打开详情。
  await mapTrigger.click();
  await expect(detail).toBeVisible();
  await expect(terracotta).toHaveAttribute('data-selected', 'on');
  await expect.poll(async () => (await mapCamera(page, ['visit-terracotta'])).markers['visit-terracotta']).not.toEqual(initialCamera.markers['visit-terracotta']);
  const focusedCamera = await settledCamera(page, ['visit-terracotta', 'visit-dayan']);
  const mapBox = await map.boundingBox();
  const panelBox = await page.locator('.journey-floating-panel').boundingBox();
  const focusedBox = await marker.boundingBox();
  expect(mapBox).not.toBeNull();
  expect(panelBox).not.toBeNull();
  expect(focusedBox).not.toBeNull();
  // 相机偏移来自面板右缘，不在测试里复制一个固定像素。
  const expectedShift = (panelBox!.x + panelBox!.width + 20 - mapBox!.x) / 2;
  expect(Math.abs(focusedBox!.x + focusedBox!.width / 2 - (mapBox!.x + mapBox!.width / 2 + expectedShift))).toBeLessThan(40);
  expect(Math.abs(focusedBox!.y + focusedBox!.height / 2 - (mapBox!.y + mapBox!.height / 2))).toBeLessThan(40);

  // 已有锁定项时，hover 其他地点仍只是高亮：相机不动、详情不换。
  await dayan.hover();
  await expect(page.locator('[data-bundle-map-entity="visit-dayan"]')).toHaveAttribute('data-linked', 'on');
  await expect(detail).toContainText('兵马俑');
  await expectCameraHeld(page, focusedCamera);

  // 关闭详情后的焦点恢复只做高亮，不把相机拉回全程，也不重新打开详情。
  await page.getByRole('button', { name: '关闭地点详情', exact: true }).click();
  await expect(mapTrigger).toBeFocused();
  await expect(detail).toHaveCount(0);
  await expectCameraHeld(page, focusedCamera);

  // 键盘聚焦只高亮；Enter 激活才算显式操作。
  await page.mouse.move(4, 4);
  await expectCameraHeld(page, focusedCamera);
  await page.keyboard.press('Tab');
  await expect(terracotta.getByRole('button', { name: '查看详情', exact: true })).toBeFocused();
  await expect(terracotta).toHaveAttribute('data-linked', 'on');
  await expectCameraHeld(page, focusedCamera);
  await page.keyboard.press('Shift+Tab');
  await expect(mapTrigger).toBeFocused();
  await expectCameraHeld(page, focusedCamera);
  await mapTrigger.press('Enter');
  await expect(detail).toBeVisible();
  await expectCameraHeld(page, focusedCamera);
  await page.keyboard.press('Escape');
  await expect(detail).toHaveCount(0);
  await expect(mapTrigger).toBeFocused();
  await expectCameraHeld(page, focusedCamera);

  // 真正的数据上下文变化（切日）仍然自动适配相机。
  await page.getByRole('button', { name: '第 2 天', exact: true }).click();
  await expect(page.locator('[data-itinerary-occurrence]')).toHaveCount(7);
  await expect(page.locator('[data-bundle-map-entity]')).toHaveCount(4);
  await expect(page.locator('.leaflet-overlay-pane path[data-route-entity]')).toHaveCount(3);
  await expect.poll(async () => (await mapCamera(page, ['visit-shaanxi-museum'])).markers['visit-shaanxi-museum']).not.toBeNull();
  const dayTwoCamera = await settledCamera(page, ['visit-shaanxi-museum', 'visit-yongning-gate']);
  expect(dayTwoCamera.zoom).not.toEqual(initialCamera.zoom);
  await page.getByRole('button', { name: '图层', exact: true }).click();
  await page.getByRole('checkbox', { name: '餐饮', exact: true }).uncheck();
  await expect(page.locator('[data-bundle-map-entity]')).toHaveCount(3);
  await page.keyboard.press('Escape');
  const lunch = page.locator('[data-itinerary-occurrence="d2-lunch"]');
  await lunch.getByRole('button', { name: '在地图查看', exact: true }).click();
  await expect(page.locator('[data-bundle-map-entity]')).toHaveCount(4);
  await expect(page.getByTestId('map-place-detail')).toContainText('子午路张记肉夹馍');

  await page.evaluate(() => {
    (window as unknown as { __journeyMapElement: Element | null }).__journeyMapElement = document.querySelector('[data-testid="bundle-leaflet-map"]');
  });
  await page.getByRole('button', { name: '阅读版', exact: true }).click();
  await expect(page.getByTestId('full-report')).toBeVisible();
  await page.getByRole('button', { name: '返回地图', exact: true }).click();
  await expect(page.getByTestId('itinerary-card-flow')).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __journeyMapElement: Element | null }).__journeyMapElement === document.querySelector('[data-testid="bundle-leaflet-map"]'))).toBe(true);
  // 回到第 1 天：数据上下文再次改变，无选中项时相机回到与初次相同的视野。
  await page.getByRole('button', { name: '第 1 天', exact: true }).click();
  await expect.poll(async () => (await mapCamera(page, ['visit-terracotta'])).markers['visit-terracotta']).not.toBeNull();
  await settleMap(page);
  await expectCameraHeld(page, initialCamera);
  await page.screenshot({ path: test.info().outputPath('desktop-xian-floating-panel.png'), fullPage: true });

  // 可画市内路线的交通卡片整卡进入路线视野，不再有独立按钮。
  const routeEntry = page.locator('[data-itinerary-occurrence="d1-transfer-lunch"]').getByTestId('transport-map-entry');
  await routeEntry.click();
  await expect(page.getByTestId('map-place-detail')).toContainText('24 分钟');
  await expect(page.getByTestId('map-place-detail')).toContainText('9.2 公里');
  await expect.poll(async () => (await mapCamera(page, ['visit-terracotta'])).markers['visit-terracotta']).not.toEqual(initialCamera.markers['visit-terracotta']);
  const routeCamera = await settledCamera(page, ['visit-terracotta', 'visit-dayan']);
  await page.getByRole('button', { name: '关闭地点详情', exact: true }).click();
  await expect(page.getByTestId('map-place-detail')).toHaveCount(0);
  await expect(routeEntry).toBeFocused();
  await expectCameraHeld(page, routeCamera);

  // 用户手动拖动后，普通悬浮不再把视野抢回。
  const dragFrom = await map.boundingBox();
  expect(dragFrom).not.toBeNull();
  await page.mouse.move(dragFrom!.x + 900, dragFrom!.y + 700);
  await page.mouse.down();
  await page.mouse.move(dragFrom!.x + 820, dragFrom!.y + 620, { steps: 8 });
  await page.mouse.up();
  const draggedCamera = await settledCamera(page, ['visit-terracotta', 'visit-dayan']);
  expect(draggedCamera).not.toEqual(initialCamera);
  await terracotta.hover();
  await expect(terracotta).toHaveAttribute('data-linked', 'on');
  await expectCameraHeld(page, draggedCamera);
  await assertOffline(page, fixture);
});

test('map detail switches selections without overlapping detail panels', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('/');
  await page.getByTestId('day-summary-card-day-1').click();
  await page.locator('[data-itinerary-occurrence="d1-terracotta"]').getByRole('button', { name: '在地图查看', exact: true }).click();
  const detail = page.getByTestId('map-place-detail');
  await expect(detail).toContainText('兵马俑');
  await page.evaluate(() => {
    const evidence = { maximum: 0 };
    (window as unknown as { detailPanelEvidence: typeof evidence }).detailPanelEvidence = evidence;
    new MutationObserver(() => {
      evidence.maximum = Math.max(evidence.maximum, document.querySelectorAll('[data-testid="map-place-detail"]').length);
    }).observe(document.body, { childList: true, subtree: true });
  });
  await page.locator('[data-itinerary-occurrence="d1-dayan"]').getByRole('button', { name: '在地图查看', exact: true }).click();
  await expect(detail).toContainText('大雁塔');
  await page.locator('[data-itinerary-occurrence="d1-terracotta"]').getByRole('button', { name: '在地图查看', exact: true }).click();
  await expect(detail).toContainText('兵马俑');
  expect(await page.evaluate(() => (window as unknown as { detailPanelEvidence: { maximum: number } }).detailPanelEvidence.maximum)).toBe(1);
  await assertOffline(page, fixture);
});

test('desktop itinerary layout evidence keeps the panel wide and weather on the date row', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true, bundleData: xianLayoutBundle({ dayCount: 5, longTitle: true, weather: 'mixed' }) });
  const evidenceDir = '../test-results/e2e-evidence/workspace-visual';
  mkdirSync(evidenceDir, { recursive: true });
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await expect(page.locator('.journey-title-row h1')).toContainText('去西安看秋风里的城墙');
  await expect(page.locator('.day-summary-card')).toHaveCount(5);
  const panelBox = await page.locator('.journey-floating-panel').boundingBox();
  expect(panelBox).not.toBeNull();
  expect(panelBox!.width).toBeGreaterThanOrEqual(600);
  expect(panelBox!.width).toBeLessThanOrEqual(640);
  const controlsBox = await page.locator('.journey-map-top-controls').boundingBox();
  expect(controlsBox).not.toBeNull();
  expect(controlsBox!.x).toBeGreaterThanOrEqual(panelBox!.x + panelBox!.width);
  await page.screenshot({ path: `${evidenceDir}/overview-2000.png`, fullPage: true });

  await page.getByTestId('day-summary-card-day-1').click();
  const header = page.getByTestId('day-header-day-1');
  await expect(header).toBeVisible();
  await expect(page.getByTestId('trip-overview')).toHaveCount(0);
  const metaBox = await header.locator('.journey-day-header-meta').boundingBox();
  const weatherBox = await header.getByTestId('day-weather-badge').boundingBox();
  const sectionRight = await header.evaluate((node) => node.parentElement!.getBoundingClientRect().right);
  expect(metaBox && weatherBox).not.toBeNull();
  expect(Math.abs((weatherBox!.y + weatherBox!.height / 2) - (metaBox!.y + metaBox!.height / 2))).toBeLessThan(4);
  expect(sectionRight - (weatherBox!.x + weatherBox!.width)).toBeLessThan(40);
  expect(await header.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${evidenceDir}/day-2000.png`, fullPage: true });
  await assertOffline(page, fixture);
});

test('desktop itinerary layout evidence holds at 1440 and 1280', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true, bundleData: xianLayoutBundle({ dayCount: 5, weather: 'mixed' }) });
  const evidenceDir = '../test-results/e2e-evidence/workspace-visual';
  mkdirSync(evidenceDir, { recursive: true });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const viewport of [{ width: 1440, height: 960 }, { width: 1280, height: 900 }]) {
    await page.setViewportSize(viewport);
    await page.goto('/');
    await expect(page.locator('.day-summary-card')).toHaveCount(5);
    await page.getByTestId('day-summary-card-day-1').click();
    const header = page.getByTestId('day-header-day-1');
    await expect(header).toBeVisible();
    await expect(page.getByTestId('trip-overview')).toHaveCount(0);
    const metaBox = await header.locator('.journey-day-header-meta').boundingBox();
    const weatherBox = await header.getByTestId('day-weather-badge').boundingBox();
    const panelBox = await page.locator('.journey-floating-panel').boundingBox();
    const controlsBox = await page.locator('.journey-map-top-controls').boundingBox();
    expect(metaBox && weatherBox && panelBox && controlsBox).not.toBeNull();
    expect(panelBox!.width).toBeGreaterThanOrEqual(viewport.width === 1440 ? 550 : 510);
    expect(controlsBox!.x).toBeGreaterThanOrEqual(panelBox!.x + panelBox!.width);
    expect(Math.abs((weatherBox!.y + weatherBox!.height / 2) - (metaBox!.y + metaBox!.height / 2))).toBeLessThan(4);
    await page.screenshot({ path: `${evidenceDir}/day-${viewport.width}.png`, fullPage: true });
    await assertOffline(page, fixture);
  }
});

test('phone itinerary layout evidence handles 14 days, a long title and missing weather', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true, bundleData: xianLayoutBundle({ dayCount: 14, longTitle: true }) });
  const evidenceDir = '../test-results/e2e-evidence/workspace-visual';
  mkdirSync(evidenceDir, { recursive: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.getByTestId('canvas-pill').click();
  const sheet = page.getByTestId('canvas-sheet');
  await expect(sheet.locator('.day-summary-card')).toHaveCount(14);
  await sheet.getByTestId('sheet-handle').click();
  await expect(sheet).toHaveAttribute('data-detent', '92');
  await page.screenshot({ path: `${evidenceDir}/phone-overview-14.png`, fullPage: true });
  const lastDay = sheet.getByTestId('day-summary-card-day-14');
  await lastDay.evaluate((node) => {
    const scroller = node.closest('.journey-content-scroll');
    if (!scroller) return;
    const nodeRect = node.getBoundingClientRect();
    const scrollerRect = scroller.getBoundingClientRect();
    scroller.scrollTop += nodeRect.top - scrollerRect.top - 72;
  });
  await expect(lastDay).toBeInViewport();
  await lastDay.click();
  await expect(sheet.getByTestId('day-header-day-14')).toBeVisible();
  await expect(sheet.getByTestId('trip-overview')).toHaveCount(0);
  await expect(sheet.getByTestId('day-header-day-14').getByTestId('day-weather-badge')).toHaveCount(0);
  expect(await sheet.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${evidenceDir}/phone-day-14.png`, fullPage: true });
  await sheet.getByTestId('day-overview-back').click();
  await expect(lastDay).toBeFocused();
  await assertOffline(page, fixture);
});

test('phone itinerary layout evidence handles a single day', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true, bundleData: xianLayoutBundle({ dayCount: 1, weather: 'mixed' }) });
  const evidenceDir = '../test-results/e2e-evidence/workspace-visual';
  mkdirSync(evidenceDir, { recursive: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.getByTestId('canvas-pill').click();
  const sheet = page.getByTestId('canvas-sheet');
  await expect(sheet.locator('.day-summary-card')).toHaveCount(1);
  await sheet.getByTestId('sheet-handle').click();
  await expect(sheet).toHaveAttribute('data-detent', '92');
  await sheet.getByTestId('day-summary-card-day-1').click();
  await expect(sheet.getByTestId('day-header-day-1')).toBeVisible();
  await expect(sheet.getByTestId('trip-overview')).toHaveCount(0);
  expect(await sheet.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${evidenceDir}/phone-day-1.png`, fullPage: true });
  await assertOffline(page, fixture);
});

test('desktop today view keeps hover highlights still and selects only on explicit activation', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-11-01T10:00:00+08:00'));
  const fixture = await offlineApp(page, { bundle: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await expect(page.getByTestId('bundle-leaflet-map')).toBeVisible();
  await page.getByRole('button', { name: '旅中查看', exact: true }).click();
  const timeline = page.getByTestId('day-timeline');
  await expect(timeline).toBeVisible();
  await expect(timeline.locator('[data-testid^="day-timeline-node-"]')).toHaveCount(7);
  const camera = await settledCamera(page, ['visit-terracotta', 'visit-dayan']);
  expect(camera.zoom).toHaveLength(1);

  // 今天视图与普通日程一样：悬浮时间线只高亮，相机、日期与详情均不动。
  const terracotta = page.getByTestId('day-timeline-node-d1-terracotta');
  const dayan = page.getByTestId('day-timeline-node-d1-dayan');
  await terracotta.hover();
  await expect(terracotta).toHaveAttribute('data-linked', 'on');
  await expect(page.locator('[data-bundle-map-entity="visit-terracotta"]')).toHaveAttribute('data-linked', 'on');
  await expectCameraHeld(page, camera);

  await dayan.hover();
  await expect(dayan).toHaveAttribute('data-linked', 'on');
  await expect(terracotta).not.toHaveAttribute('data-linked', 'on');
  await expectCameraHeld(page, camera);

  // 地图 Marker 的点击仍是显式定位，并打开对应详情。
  await page.locator('[data-bundle-map-entity="visit-dayan"]').click();
  const detail = page.getByTestId('map-place-detail');
  await expect(detail).toBeVisible();
  await expect(detail).toContainText('大雁塔');
  await expect.poll(async () => (await mapCamera(page, ['visit-dayan'])).markers['visit-dayan']).not.toEqual(camera.markers['visit-dayan']);
  const focusedCamera = await settledCamera(page, ['visit-terracotta', 'visit-dayan']);

  // 已有选中项后，悬浮其他时间线节点不再移动相机，也不换详情。
  await terracotta.hover();
  await expect(terracotta).toHaveAttribute('data-linked', 'on');
  await expect(detail).toContainText('大雁塔');
  await expectCameraHeld(page, focusedCamera);

  await page.getByRole('button', { name: '关闭地点详情', exact: true }).click();
  await expect(detail).toHaveCount(0);
  await page.mouse.move(4, 4);
  await expectCameraHeld(page, focusedCamera);
  await page.screenshot({ path: test.info().outputPath('desktop-today-hover-stable.png'), fullPage: true });
  await assertOffline(page, fixture);
});

test('hover intent evidence records camera state for hover and explicit selection', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true });
  const evidenceDir = '../test-results/e2e-evidence/hover-intent';
  mkdirSync(evidenceDir, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.getByTestId('day-summary-card-day-1').click();
  await expect(page.locator('[data-itinerary-occurrence]')).toHaveCount(7);
  await settleMap(page);
  const markerIds = ['visit-terracotta', 'visit-dayan'];
  const snapshots: Record<string, MapCamera> = {};
  const capture = async (name: string) => {
    snapshots[name] = await settledCamera(page, markerIds);
    await page.screenshot({ path: `${evidenceDir}/${name}.png` });
  };

  await capture('hover-before');
  await page.locator('[data-itinerary-occurrence="d1-terracotta"]').hover();
  await settleMap(page);
  await capture('hover-terracotta');
  await page.locator('[data-itinerary-occurrence="d1-dayan"]').hover();
  await settleMap(page);
  await capture('hover-dayan');
  expect(snapshots['hover-terracotta']).toEqual(snapshots['hover-before']);
  expect(snapshots['hover-dayan']).toEqual(snapshots['hover-before']);

  await page.locator('[data-itinerary-occurrence="d1-terracotta"]').getByRole('button', { name: '在地图查看', exact: true }).click();
  await expect(page.getByTestId('map-place-detail')).toBeVisible();
  await settleMap(page);
  await capture('selected-terracotta');
  expect(snapshots['selected-terracotta'].markers['visit-terracotta']).not.toEqual(snapshots['hover-before'].markers['visit-terracotta']);
  writeFileSync(`${evidenceDir}/camera-stability.json`, JSON.stringify({
    viewport: '1440x960',
    note: 'zoom 取自瓦片 z；markers 为 Marker 中心相对地图容器的屏幕坐标；pane 为 Leaflet map pane transform',
    snapshots,
  }, null, 2));
  await assertOffline(page, fixture);
});

test('mixed transport map keeps every target, mode color and geometry visible', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true, bundleData: xianMixedTransportBundle() });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  const map = page.getByTestId('bundle-leaflet-map');
  await expect(map).toBeVisible();
  await expect(page.getByTestId('interactive-itinerary')).toBeVisible();
  await page.getByTestId('day-summary-card-day-1').click();
  await expect(page.locator('[data-itinerary-occurrence]')).toHaveCount(10);
  const contentEntityIds = await page.locator('[data-itinerary-occurrence]').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-entity-id') ?? ''));
  expect(contentEntityIds.slice(0, 3)).toEqual(['leg-flight-demo', 'leg-ride-demo', 'visit-terracotta']);
  await expect(page.locator('[data-bundle-map-kind="transport_endpoint"]')).toHaveCount(2);
  await expect(page.getByLabel('路线图例')).toHaveCount(0);
  await expect(page.getByTestId('map-unlocated-places')).toHaveCount(0);

  const paths = page.locator('.leaflet-overlay-pane path[data-route-entity]');
  await expect(paths).toHaveCount(5);
  const mappedEntityIds = await paths.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-route-entity') ?? '').sort());
  expect(mappedEntityIds).toEqual(contentEntityIds.filter(id => id.startsWith('leg-')).sort());
  await expect(page.locator('path[data-route-geometry="provider"]')).toHaveCount(3);
  await expect(page.locator('path[data-route-geometry="direct"]')).toHaveCount(1);
  await expect(page.locator('path[data-route-geometry="endpoint"]')).toHaveCount(1);
  await expect(page.locator('path[data-route-segment="segment-flight-demo"]')).toHaveCSS('stroke', 'rgb(108, 99, 206)');
  await expect(page.locator('path[data-route-segment="segment-ride-demo"]')).toHaveAttribute('data-route-mode', 'ride_hailing');
  await expect(page.locator('path[data-route-segment="segment-ride-demo"]')).toHaveCSS('stroke', 'rgb(194, 106, 27)');

  const driveCard = page.getByTestId('transport-card-leg-terracotta-lunch');
  const cardColor = await driveCard.locator('.transport-mode-icon').first().evaluate(node => getComputedStyle(node).color);
  await expect(page.locator('path[data-route-segment="segment-terracotta-lunch"]')).toHaveCSS('stroke', cardColor);

  const mapBox = await map.boundingBox();
  const markers = page.locator('[data-bundle-map-entity], [data-bundle-map-group]');
  expect(mapBox).not.toBeNull();
  expect(await markers.count()).toBeGreaterThan(0);
  for (let index = 0; index < await markers.count(); index += 1) {
    const markerBox = await markers.nth(index).boundingBox();
    expect(markerBox, `marker ${index} has a box`).not.toBeNull();
    expect(markerBox!.x, `marker ${index} starts inside the map`).toBeGreaterThanOrEqual(mapBox!.x);
    expect(markerBox!.y, `marker ${index} starts inside the map`).toBeGreaterThanOrEqual(mapBox!.y);
    expect(markerBox!.x + markerBox!.width, `marker ${index} ends inside the map`).toBeLessThanOrEqual(mapBox!.x + mapBox!.width);
    expect(markerBox!.y + markerBox!.height, `marker ${index} ends inside the map`).toBeLessThanOrEqual(mapBox!.y + mapBox!.height);
  }

  await page.screenshot({ path: test.info().outputPath('desktop-mixed-transport-map-overview.png'), fullPage: true });
  const group = page.locator('[data-bundle-map-group]');
  await expect(group).toHaveCount(1);
  await group.click();
  await expect(page.locator('[data-bundle-map-entity="visit-dayan"]')).toBeVisible();
  const duplicate = page.locator('[data-bundle-map-entity="visit-dayan-duplicate"]');
  await expect(duplicate).toBeVisible();
  await duplicate.click();
  await expect(page.getByTestId('map-place-detail')).toContainText('大雁塔文化讲解');
  await page.screenshot({ path: test.info().outputPath('desktop-mixed-transport-map.png'), fullPage: true });
  await assertOffline(page, fixture);
});

test('mixed transport map stays clean and usable on a phone', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true, bundleData: xianMixedTransportBundle() });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await expect(page.getByTestId('bundle-leaflet-map')).toBeVisible();
  await expect(page.getByLabel('路线图例')).toHaveCount(0);
  await expect(page.getByTestId('map-unlocated-places')).toHaveCount(0);
  await expect(page.getByTestId('canvas-pill')).toBeVisible();
  await page.waitForTimeout(500);
  await page.screenshot({ path: test.info().outputPath('phone-mixed-transport-map.png'), fullPage: true });
  await assertOffline(page, fixture);
});

test('mixed transport display merges headings and keeps station truth', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true, bundleData: xianTransportDisplayBundle() });
  const evidenceDir = '../test-results/e2e-evidence/transit-card-redesign';
  mkdirSync(evidenceDir, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.getByTestId('day-summary-card-day-1').click();

  const rail = page.getByTestId('transport-card-leg-display-rail');
  await expect(rail).toBeVisible();
  await expect(rail).toContainText('高铁');
  await expect(rail).toContainText('G382');
  await expect(rail).toContainText('11:41–19:30');
  await expect(rail).toContainText('7 小时 49 分钟');
  await expect(rail).toContainText('¥1,108');
  await expect(rail.locator('.transport-mode-icon')).toHaveCount(1);
  await expect(rail).not.toContainText('班次');
  await expect(rail).not.toContainText('IOQ');
  await expect(rail).not.toContainText('BXP');
  await expect(rail).not.toContainText('直达');
  const railSummary = rail.getByTestId('transport-summary');
  await expect(railSummary.locator('dt.sr-only')).toHaveCount(2);
  await expect(railSummary).not.toContainText('换乘');
  const railOccurrence = page.locator('[data-itinerary-occurrence="d1-display-rail"]');
  await expect(railOccurrence.locator('[data-timeline-domain="transport"]')).toHaveCount(0);
  await expect(railOccurrence.getByText('11:41–19:30')).toHaveCount(1);
  await expect(railOccurrence.getByTestId('transport-map-entry')).toHaveCount(0);
  await expect(railOccurrence.getByRole('button', { name: /在地图中查看/ })).toHaveCount(0);

  const flight = page.getByTestId('transport-card-leg-display-flight');
  await expect(flight).toContainText('飞机');
  await expect(flight).toContainText('CA1234');
  await expect(flight).toContainText('PEK');
  await expect(flight).toContainText('XIY');
  await expect(flight.locator('.transport-mode-icon')).toHaveCount(1);
  await expect(flight).not.toContainText('班次');
  const flightOccurrence = page.locator('[data-itinerary-occurrence="d1-display-flight"]');
  await expect(flightOccurrence.getByTestId('transport-map-entry')).toHaveCount(0);
  await expect(flightOccurrence.getByRole('button', { name: /在地图中查看/ })).toHaveCount(0);

  const direct = page.getByTestId('transport-card-leg-display-metro-direct');
  await expect(direct).toContainText('地铁2号线');
  await expect(direct).toContainText('往小寨站');
  await expect(direct).toContainText('钟楼站');
  await expect(direct).toContainText('小寨站');
  await expect(direct).toContainText('09:00–09:42');
  await expect(direct).toContainText('42 分钟');
  await expect(direct).toContainText('¥5');
  await expect(direct).not.toContainText('市内公共交通');
  await expect(direct).not.toContainText('换乘');
  await expect(direct).not.toContainText('直达');
  await expect(direct.getByTestId('transport-summary').locator('dt.sr-only')).toHaveCount(2);
  await expect(direct).not.toContainText('西安钟楼饭店');
  await expect(direct).not.toContainText('陕西历史博物馆');
  await expect(direct.locator('.transport-mode-icon')).toHaveCount(1);
  await expect(direct.getByTestId('transit-line-chain')).toHaveCount(0);
  await expect(direct.getByTestId('transport-rides')).toHaveCount(0);
  await expect(direct.getByTestId('transport-segments-toggle')).toHaveCount(0);
  const directOccurrence = page.locator('[data-itinerary-occurrence="d1-display-metro-direct"]');
  const directEntry = directOccurrence.getByTestId('transport-map-entry');
  await expect(directEntry).toHaveCount(1);
  await expect(directEntry).toHaveAttribute('role', 'button');
  await expect(directEntry).toHaveAttribute('aria-label', /地铁2号线/);
  await expect(directEntry).toHaveAttribute('aria-label', /钟楼站到小寨站/);
  await expect(directEntry).toHaveAttribute('aria-label', /在地图中查看/);
  await expect(directOccurrence.getByRole('button', { name: '查看路线', exact: true })).toHaveCount(0);
  await directEntry.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('map-place-detail')).toBeVisible();
  await expect(page.getByTestId('map-place-detail')).toContainText('地铁2号线');
  await page.getByRole('button', { name: '关闭地点详情', exact: true }).click();
  await expect(page.getByTestId('map-place-detail')).toHaveCount(0);
  await expect(directEntry).toBeFocused();

  const transfer = page.getByTestId('transport-card-leg-display-metro-transfer');
  await expect(transfer).toContainText('地铁2号线');
  await expect(transfer).toContainText('地铁4号线');
  await expect(transfer).toContainText('北大街站（地铁2号线·4号线换乘）');
  await expect(transfer).toContainText('大雁塔站（雁塔北路南口）');
  await expect(transfer).toContainText('15:00–15:38');
  await expect(transfer).toContainText('¥6');
  await expect(transfer).not.toContainText('换乘 1 次');
  await expect(transfer).not.toContainText('市内公共交通');
  await expect(transfer.getByTestId('transport-summary').locator('dt.sr-only')).toHaveCount(2);
  const chain = transfer.getByTestId('transit-line-chain');
  await expect(chain).toHaveAttribute('aria-expanded', 'false');
  await expect(transfer.getByTestId('transport-rides')).toBeHidden();

  const mixed = page.getByTestId('transport-card-leg-display-metro-mixed');
  await expect(mixed).toContainText('地铁2号线');
  await expect(mixed).toContainText('公交5路');
  await expect(mixed).toContainText('地铁4号线');
  await expect(mixed).not.toContainText('地铁 / 公交');
  await expect(mixed).not.toContainText('地铁 北大街站');
  await expect(mixed).not.toContainText('换乘 1 次');
  await expect(mixed).not.toContainText('换乘 2 次');
  await expect(mixed.getByTestId('transit-line-chain')).toBeVisible();

  const tram = page.getByTestId('transport-card-leg-display-tram');
  await expect(tram).toContainText('103路');
  await expect(tram).toContainText('往神武门站');
  await expect(tram).toContainText('东安门大街站');
  await expect(tram).toContainText('神武门站');
  await expect(tram).toContainText('09:20–09:58');
  await expect(tram).toContainText('38 分钟');
  await expect(tram).toContainText('¥2');
  await expect(tram).not.toContainText('北京站西');
  await expect(tram.getByTestId('transit-line-chain')).toHaveCount(0);
  await expect(tram.getByTestId('transport-rides')).toHaveCount(0);

  const noLine = page.getByTestId('transport-card-leg-display-metro-noline');
  await expect(noLine).toContainText('地铁');
  await expect(noLine).toContainText('往大雁塔站（雁塔北路南口）');
  await expect(noLine).toContainText('钟楼站');
  await expect(noLine).toContainText('24 分钟');
  await expect(noLine).toContainText('¥4');
  await expect(noLine.getByTestId('transit-line-chain')).toHaveCount(0);

  const unproven = page.getByTestId('transport-card-leg-display-metro-unproven');
  await expect(unproven).toContainText('地铁4号线');
  await expect(unproven).toContainText('27 分钟');
  await expect(unproven).not.toContainText('陕西历史博物馆');
  await expect(unproven).not.toContainText('子午路张记肉夹馍（小寨店）');
  await expect(unproven).not.toContainText('¥0');
  await expect(unproven.getByTestId('transit-direction')).toHaveCount(0);

  const pending = page.getByTestId('transport-card-leg-display-metro-pending');
  await expect(pending).toContainText('路线正在更新。');
  await expect(pending.getByTestId('transport-stations')).toHaveCount(0);
  await expect(pending.getByTestId('transport-summary')).toHaveCount(0);

  await expect(page.getByText('查看路线', { exact: true })).toHaveCount(0);

  await page.screenshot({ path: `${evidenceDir}/transit-desktop-1440.png`, fullPage: true });

  await transfer.evaluate((node) => {
    const scroller = node.closest('.journey-content-scroll');
    if (!scroller) return;
    const nodeRect = node.getBoundingClientRect();
    const scrollerRect = scroller.getBoundingClientRect();
    scroller.scrollTop += nodeRect.top - scrollerRect.top - 120;
  });
  await expect(transfer).toBeInViewport();
  await page.screenshot({ path: `${evidenceDir}/transit-transfer-collapsed-1440.png`, fullPage: true });

  await chain.click();
  await expect(chain).toHaveAttribute('aria-expanded', 'true');
  const rides = transfer.getByTestId('transport-rides');
  await expect(rides).toBeVisible();
  await expect(rides.locator(':scope > li')).toHaveCount(2);
  await expect(rides).not.toContainText('步行');
  await expect(rides).toContainText('北大街站（地铁2号线·4号线换乘） → 小寨站');
  await expect(rides).toContainText('小寨站 → 大雁塔站（雁塔北路南口）');
  await expect(page.getByTestId('map-place-detail')).toHaveCount(0);
  await page.screenshot({ path: `${evidenceDir}/transit-transfer-expanded-1440.png`, fullPage: true });

  await transfer.getByTestId('transport-stations').click();
  const detail = page.getByTestId('map-place-detail');
  await expect(detail).toBeVisible();
  await expect(detail).toContainText('地铁4号线');
  await page.screenshot({ path: `${evidenceDir}/transit-map-detail-1440.png`, fullPage: true });
  await page.getByRole('button', { name: '关闭地点详情', exact: true }).click();
  await expect(detail).toHaveCount(0);
  await expect(page.locator('[data-itinerary-occurrence="d1-display-metro-transfer"]').getByTestId('transport-map-entry')).toBeFocused();

  await tram.evaluate((node) => {
    const scroller = node.closest('.journey-content-scroll');
    if (!scroller) return;
    const nodeRect = node.getBoundingClientRect();
    const scrollerRect = scroller.getBoundingClientRect();
    scroller.scrollTop += nodeRect.top - scrollerRect.top - 120;
  });
  await expect(tram).toBeInViewport();
  await page.screenshot({ path: `${evidenceDir}/transit-tram-1440.png`, fullPage: true });

  await pending.evaluate((node) => {
    const scroller = node.closest('.journey-content-scroll');
    if (!scroller) return;
    const nodeRect = node.getBoundingClientRect();
    const scrollerRect = scroller.getBoundingClientRect();
    scroller.scrollTop += nodeRect.top - scrollerRect.top - 120;
  });
  await expect(pending).toBeInViewport();
  await page.screenshot({ path: `${evidenceDir}/transit-degraded-1440.png`, fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByTestId('canvas-pill').click();
  const sheet = page.getByTestId('canvas-sheet');
  await sheet.getByTestId('sheet-handle').click();
  await expect(sheet).toHaveAttribute('data-detent', '92');
  await sheet.getByTestId('day-summary-card-day-1').click();
  const phoneTransfer = sheet.getByTestId('transport-card-leg-display-metro-transfer');
  await expect(phoneTransfer).toBeVisible();
  await expect(phoneTransfer.getByTestId('transit-line-chain')).toBeVisible();
  await expect(phoneTransfer).toContainText('地铁2号线');
  await expect(phoneTransfer).toContainText('地铁4号线');
  await page.waitForTimeout(600);
  await phoneTransfer.evaluate((node) => {
    const scroller = node.closest('.journey-content-scroll');
    if (!scroller) return;
    const nodeRect = node.getBoundingClientRect();
    const scrollerRect = scroller.getBoundingClientRect();
    scroller.scrollTop += nodeRect.top - scrollerRect.top - 120;
  });
  await expect(phoneTransfer).toBeInViewport();
  await phoneTransfer.getByTestId('transit-line-chain').click();
  await expect(phoneTransfer.getByTestId('transport-rides')).toBeVisible();
  await expect(phoneTransfer.getByTestId('transport-rides').locator(':scope > li')).toHaveCount(2);
  expect(await sheet.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${evidenceDir}/transit-phone-390.png`, fullPage: true });

  const phoneTram = sheet.getByTestId('transport-card-leg-display-tram');
  await phoneTram.evaluate((node) => {
    const scroller = node.closest('.journey-content-scroll');
    if (!scroller) return;
    const nodeRect = node.getBoundingClientRect();
    const scrollerRect = scroller.getBoundingClientRect();
    scroller.scrollTop += nodeRect.top - scrollerRect.top - 120;
  });
  await expect(phoneTram).toBeInViewport();
  await page.screenshot({ path: `${evidenceDir}/transit-tram-phone-390.png`, fullPage: true });

  const phonePending = sheet.getByTestId('transport-card-leg-display-metro-pending');
  await phonePending.evaluate((node) => {
    const scroller = node.closest('.journey-content-scroll');
    if (!scroller) return;
    const nodeRect = node.getBoundingClientRect();
    const scrollerRect = scroller.getBoundingClientRect();
    scroller.scrollTop += nodeRect.top - scrollerRect.top - 120;
  });
  await expect(phonePending).toBeInViewport();
  await page.screenshot({ path: `${evidenceDir}/transit-degraded-phone-390.png`, fullPage: true });

  const phoneDirect = sheet.getByTestId('transport-card-leg-display-metro-direct');
  await phoneDirect.evaluate((node) => {
    const scroller = node.closest('.journey-content-scroll');
    if (!scroller) return;
    const nodeRect = node.getBoundingClientRect();
    const scrollerRect = scroller.getBoundingClientRect();
    scroller.scrollTop += nodeRect.top - scrollerRect.top - 120;
  });
  await expect(phoneDirect).toBeInViewport();
  await phoneDirect.getByTestId('transport-stations').click();
  await expect(page.getByTestId('canvas-sheet')).toHaveCount(0);
  await expect(page.getByTestId('map-place-detail')).toBeVisible();
  await page.screenshot({ path: `${evidenceDir}/transit-map-detail-phone-390.png`, fullPage: true });
  await assertOffline(page, fixture);
});

test('keyboard focus stays within the mobile itinerary sheet', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  const opener = page.getByTestId('canvas-pill');
  await opener.click();
  const sheet = page.getByRole('dialog', { name: '行程详情' });
  const handle = sheet.getByRole('button', { name: '展开行程详情' });
  await expect(sheet).toBeFocused();
  await handle.evaluate((node) => {
    const hiddenPanel = document.createElement('div');
    hiddenPanel.inert = true;
    const hiddenButton = document.createElement('button');
    hiddenButton.textContent = '隐藏面板中的按钮';
    hiddenPanel.append(hiddenButton);
    node.after(hiddenPanel);
  });
  await handle.focus();
  await page.keyboard.press('Tab');
  expect(await sheet.evaluate((node) => node.contains(document.activeElement))).toBe(true);
  await expect(handle).not.toBeFocused();
  await handle.focus();
  await page.keyboard.press('Shift+Tab');
  expect(await sheet.evaluate((node) => node.contains(document.activeElement))).toBe(true);
  await page.keyboard.press('Tab');
  await expect(handle).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(sheet).toHaveAttribute('data-detent', '92');
  await page.keyboard.press('Escape');
  await expect(sheet).toHaveCount(0);
  await expect(opener).toBeFocused();
  await assertOffline(page, fixture);
});

test('tooltip associates its description with the focused control', async ({ page }) => {
  const fixture = await offlineApp(page);
  await page.goto('/');
  await page.getByTestId('brief-input').fill('希望安排轻松的旅行');
  await page.getByTestId('send-button').click();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'error', message: '离线模拟错误' }], true);
  const trigger = page.getByTestId('error-inspect');
  await trigger.focus();
  await expect(page.getByRole('tooltip')).toHaveText('技术详情');
  await expect(trigger).toHaveAccessibleDescription('技术详情');
  await page.getByTestId('brief-input').focus();
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await assertOffline(page, fixture);
});

test('confirm action returns focus after cancellation', async ({ page }) => {
  const fixture = await offlineApp(page, { memoryFact: true });
  await page.goto('/?view=user-preferences');
  const row = page.getByTestId('memory-fact');
  await expect(row).toContainText('偏好靠窗座位');
  const trigger = row.locator('[data-confirm-action] > button');
  await trigger.focus();
  await trigger.press('Enter');
  await expect(row.getByRole('button', { name: '删除', exact: true })).toBeFocused();
  await row.getByRole('button', { name: '取消', exact: true }).click();
  await expect(trigger).toBeFocused();
  const deleteAll = page.getByTestId('memory-delete-all');
  await deleteAll.click();
  const dialog = page.getByRole('dialog', { name: '删除全部记忆？' });
  await expect(dialog).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true);
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', { name: '关闭', exact: true })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(deleteAll).toBeFocused();
  await assertOffline(page, fixture);
});

test('conversation restores focus to its newly rendered trigger on Escape and return', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  const adjust = page.getByRole('button', { name: '调整', exact: true });
  await adjust.click();
  const composer = page.getByRole('textbox', { name: '旅行需求', exact: true });
  await expect(composer).toBeFocused();
  await composer.press('Escape');
  await expect(adjust).toBeFocused();
  await adjust.click();
  await page.getByRole('button', { name: '返回日程', exact: true }).click();
  await expect(adjust).toBeFocused();
  await assertOffline(page, fixture);
});

test('phone card selection closes the sheet and reveals the selected map place', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.getByTestId('canvas-pill').click();
  const sheet = page.getByTestId('canvas-sheet');
  await expect(sheet.getByTestId('itinerary-card-flow')).toHaveCount(0);
  await sheet.getByTestId('day-summary-card-day-1').click();
  await expect(sheet.getByTestId('itinerary-card-flow')).toBeVisible();
  const dayan = sheet.locator('[data-itinerary-occurrence="d1-dayan"]');
  await dayan.scrollIntoViewIfNeeded();
  await dayan.getByRole('button', { name: '在地图查看', exact: true }).click();
  await expect(sheet).toHaveCount(0);
  await expect(page.getByTestId('map-place-detail')).toContainText('大雁塔');
  await expect(page.locator('[data-bundle-map-entity="visit-dayan"]')).toBeVisible();
  await page.getByRole('button', { name: '关闭地点详情', exact: true }).click();
  await page.getByTestId('canvas-pill').click();
  await expect(sheet.getByTestId('itinerary-card-flow')).toBeVisible();
  await sheet.screenshot({ path: test.info().outputPath('phone-xian-card-sheet.png') });
  await assertOffline(page, fixture);
});

const gateFrame = (revision = 0) => ({
  type: 'approval_gate_raised', run_id: 'run-A', gate: 'plan', run_status: 'awaiting_input',
  payload: { gate: 'plan', approval_token: `test-token-A-${revision}`, revision, revision_limit: 2, decision_options: ['approve', 'supplement', 'cancel'],
    plan_text: '核对本次目的地通行与休息安排。',
    plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '核对通行条件' } }] },
    recognized_requirements: { hard: [], preferences: [], attention: [] }, unresolved_requirement_ids: [] },
});
async function start(page: Page) {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  const fixture = await offlineApp(page, { terminalStatus: 'failed' });
  await page.goto('/');
  const input = page.getByTestId('generation-followup-composer').getByTestId('brief-input');
  await input.fill('继续完善这趟旅行');
  await input.press('Enter');
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'chat_start', session_id: 'A', run_id: 'run-A', message_id: 'review-live', route_decision: { route: 'trip_refinement' } }]);
  return fixture;
}
async function openGate(page: Page) {
  await sendFrames(page, [gateFrame(), { type: 'chat_complete', run_id: 'run-A', run_status: 'awaiting_input', ts_ms: Date.now() }], true);
  await expect(page.getByTestId('trip-brief-plan-gate')).toBeVisible();
}

test('stale approval requires refreshing the current plan before a new decision', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { planGate: true });
  await page.goto('/');
  const gate = page.getByTestId('trip-brief-plan-gate');
  await expect(gate).toBeVisible();
  await expect.poll(() => fixture.requests.filter(request => request.startsWith('GET /api/trip-runs/run-A?')).length).toBeGreaterThanOrEqual(2);
  fixture.advancePlanGate();
  await page.evaluate(() => { (window as FixtureWindow).__offlineStaleGateOnce = true; });
  await gate.getByRole('button', { name: '确认并开始生成' }).click();
  await expect(gate.getByRole('alert')).toContainText('计划版本已变化');
  await expect(gate.getByRole('button', { name: '确认并开始生成' })).toBeDisabled();
  expect((await lastChatBody(page))?.gate_decision).toEqual({ action: 'approve', content: '', approval_token: 'test-token-A-0' });
  expect(await page.evaluate(() => (window as FixtureWindow).__offlineChatBodies?.length)).toBe(1);
  await gate.getByRole('button', { name: '刷新当前计划' }).click();
  await expect(gate.getByRole('button', { name: '确认并开始生成' })).toBeEnabled();
  expect(await page.evaluate(() => (window as FixtureWindow).__offlineChatBodies?.length)).toBe(1);
  await gate.getByRole('button', { name: '确认并开始生成' }).click();
  await expect.poll(async () => (await lastChatBody(page))?.gate_decision).toEqual({ action: 'approve', content: '', approval_token: 'test-token-A-1' });
  await assertOffline(page, fixture);
});

test('stale gate remains locked when cancellation fails', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { planGate: true });
  await page.goto('/');
  const gate = page.getByTestId('trip-brief-plan-gate');
  await expect(gate).toBeVisible();
  await page.evaluate(() => { (window as FixtureWindow).__offlineStaleGateOnce = true; });
  await gate.getByRole('button', { name: '确认并开始生成' }).click();
  await expect(gate.getByRole('button', { name: '刷新当前计划' })).toBeVisible();
  await page.evaluate(() => { (window as FixtureWindow).__offlineFailChatAttempts = 3; });
  await gate.getByRole('button', { name: '取消规划' }).click();
  await expect(gate.getByRole('alert')).toContainText('计划版本已变化');
  await expect(gate.getByRole('button', { name: '确认并开始生成' })).toBeDisabled();
  await expect(gate.getByRole('button', { name: '刷新当前计划' })).toBeVisible();
  await assertOffline(page, fixture);
});

test('refreshing a stale gate respects a cancelled run', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { planGate: true });
  await page.goto('/');
  const gate = page.getByTestId('trip-brief-plan-gate');
  await expect(gate).toBeVisible();
  await expect.poll(() => fixture.requests.filter(request => request.startsWith('GET /api/trip-runs/run-A?')).length).toBeGreaterThanOrEqual(2);
  await page.evaluate(() => { (window as FixtureWindow).__offlineStaleGateOnce = true; });
  await gate.getByRole('button', { name: '确认并开始生成' }).click();
  await expect(gate.getByRole('button', { name: '刷新当前计划' })).toBeVisible();
  fixture.cancelPlanGate();
  await gate.getByRole('button', { name: '刷新当前计划' }).click();
  await expect(gate).toHaveCount(0);
  await expect(page.getByTestId('generation-journey-panel').locator('.generation-progress > h2')).toHaveText('旅行规划已取消');
  expect(await page.evaluate(() => (window as FixtureWindow).__offlineChatBodies?.length)).toBe(1);
  await assertOffline(page, fixture);
});

test('repeated stale-plan refresh failures restore error focus', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { planGate: true });
  await page.goto('/');
  const gate = page.getByTestId('trip-brief-plan-gate');
  await expect(gate).toBeVisible();
  await expect.poll(() => fixture.requests.filter(request => request.startsWith('GET /api/trip-runs/run-A?')).length).toBeGreaterThanOrEqual(2);
  await page.evaluate(() => { (window as FixtureWindow).__offlineStaleGateOnce = true; });
  await gate.getByRole('button', { name: '确认并开始生成' }).click();
  const refresh = gate.getByRole('button', { name: '刷新当前计划' });
  await expect(refresh).toBeVisible();
  fixture.setGateDetailUnavailable(true);
  await refresh.click();
  await expect(gate.getByRole('alert')).toHaveText('暂时无法刷新计划，请重试或取消规划。');
  await expect(gate.getByRole('alert')).toBeFocused();
  await refresh.focus();
  await page.keyboard.press('Enter');
  await expect(gate.getByRole('alert')).toBeFocused();
  await expect(gate.getByRole('button', { name: '确认并开始生成' })).toBeDisabled();
  await assertOffline(page, fixture);
});

test('gate stays editable when an opened decision stream fails before acceptance', async ({ page }) => {
  const fixture = await start(page);
  await openGate(page);
  const gate = page.getByTestId('trip-brief-plan-gate');
  await gate.getByRole('button', { name: '补充或调整旅行要求' }).click();
  await gate.getByLabel('想改哪里？').fill('午后留出休息时间');
  await gate.getByTestId('plan-gate-supplement').click();
  await sendFrames(page, [{ type: 'chat_start', session_id: 'A', run_id: 'run-A', message_id: 'failed-decision', route_decision: { route: 'trip_refinement' } }]);
  await page.waitForTimeout(400);
  await expect(gate).toBeVisible();
  await sendFrames(page, [{ type: 'error', message: '暂时无法继续', run_status: 'awaiting_input' }], true);
  await expect(gate).toBeVisible();
  await expect(gate.getByLabel('想改哪里？')).toHaveValue('午后留出休息时间');
  await expect(gate.getByTestId('plan-gate-supplement')).toBeEnabled();
  await expect(gate.getByRole('alert')).toBeFocused();
  await assertOffline(page, fixture);
});

test('review live gate must receive heading focus after expansion', async ({ page }) => {
  const fixture = await start(page);
  await openGate(page);
  await sampleHandoffHeights(page);
  console.log('FOCUS', await page.evaluate(() => ({ active: document.activeElement?.tagName, gateInert: (document.querySelector('.generation-handoff-gate') as HTMLElement)?.inert })));
  await assertOffline(page, fixture);
  await expect(page.getByRole('heading', { name: '确认研究方案', exact: true })).toBeFocused({ timeout: 1000 });
});

test('review currentFocus remains visible in actual research stage', async ({ page }) => {
  const fixture = await start(page);
  await sendFrames(page, [
    { type: 'thinking', message_id: 'review-live', agent_name: '交通查询', step_name: '核对衔接', content: '核对可执行的到站衔接', ts_ms: Date.now(), progress_status: 'running' },
    { type: 'trip_summary_card', summary_card: { headline: '离线测试', summary: '调研进行中', current_focus: '正在核对末班接驳车与无障碍换乘', compact_line: '离线样例', facts: [], priorities: [] } },
  ]);
  await expect(page.locator('.generation-progress li.is-active .generation-stage-title')).toHaveText('查找旅行资料');
  await assertOffline(page, fixture);
  await expect(page.locator('.generation-progress li.is-active')).toContainText('正在核对末班接驳车与无障碍换乘', { timeout: 1000 });
});

test('review process manually opened before gate collapses again on approval', async ({ page }) => {
  const fixture = await start(page);
  const heading = page.getByTestId('thinking-chain').locator('.research-panel-heading');
  await expect(heading).toHaveAttribute('aria-expanded', 'false');
  await heading.click();
  await expect(heading).toHaveAttribute('aria-expanded', 'true');
  await openGate(page);
  await page.getByRole('button', { name: '确认并开始生成', exact: true }).click();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'chat_start', session_id: 'A', run_id: 'run-A', message_id: 'review-approved', route_decision: { route: 'trip_refinement' } }]);
  await expect(page.getByTestId('trip-brief-plan-gate')).toBeVisible();
  await sendFrames(page, [{ type: 'thinking', agent_name: 'planner', content: '正在准备研究计划' }]);
  await expect(page.getByTestId('trip-brief-plan-gate')).toHaveCount(0);
  await assertOffline(page, fixture);
  await expect(heading).toHaveAttribute('aria-expanded', 'false', { timeout: 1000 });
});

test('review event recovery must go directly to restored gate without expansion', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  const fixture = await offlineApp(page, { recovery: true });
  await page.goto('/');
  const handoff = page.getByTestId('generation-handoff');
  await expect(handoff).toHaveAttribute('data-phase', 'process');
  const compact = await handoff.evaluate(el => el.getBoundingClientRect().height);
  const sampling = sampleHandoffHeights(page, 1600);
  fixture.recoverPlanGate();
  const frames = await sampling;
  await expect(page.getByTestId('trip-brief-plan-gate')).toBeVisible();
  const final = await handoff.evaluate(el => el.getBoundingClientRect().height);
  const intermediate = frames.filter(f => f.height > compact + 8 && f.height < final - 8);
  console.log('RECOVERY', JSON.stringify({ compact, final, intermediate }));
  await test.info().attach('recovery-geometry', { body: JSON.stringify({ compact, final, frames }), contentType: 'application/json' });
  await assertOffline(page, fixture);
  expect(intermediate).toHaveLength(0);
});

test('review compact -> large gate samples must not drop to zero first', async ({ page }) => {
  const fixture = await start(page);
  const handoff = page.getByTestId('generation-handoff');
  const before = await handoff.evaluate(el => el.getBoundingClientRect().height);
  const samples = sampleHandoffHeights(page);
  await openGate(page);
  const frames = await samples;
  console.log('EXPANSION', JSON.stringify({ before, frames }));
  await test.info().attach('expansion-geometry', { body: JSON.stringify({ before, frames }), contentType: 'application/json' });
  await assertOffline(page, fixture);
  expect(Math.min(...frames.map(frame => frame.height))).toBeGreaterThanOrEqual(before - 1);
});

test('review new Run after live gate cancellation starts compact instead of carrying old UI state', async ({ page }) => {
  const fixture = await start(page);
  await openGate(page);
  await page.getByRole('button', { name: '取消规划', exact: true }).click();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'run_cancelled', run_id: 'run-A', final_content: '已取消当前规划。', ts_ms: Date.now() }], true);
  await expect(page.getByTestId('trip-brief-plan-gate')).toHaveCount(0);
  const handoff = page.getByTestId('generation-handoff');
  await handoff.evaluate(el => el.setAttribute('data-review-mounted', 'kept'));
  const input = page.getByTestId('generation-followup-composer').getByTestId('brief-input');
  await input.fill('重新整理新旅行');
  await input.press('Enter');
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'chat_start', session_id: 'A', run_id: 'run-followup', message_id: 'review-new-run', route_decision: { route: 'trip_planning' } }]);
  await expect(handoff).toHaveAttribute('data-review-mounted', 'kept');
  const heading = page.getByTestId('thinking-chain').locator('.research-panel-heading');
  await expect(heading).toHaveAttribute('aria-controls', 'generation-thinking-run-followup');
  await assertOffline(page, fixture);
  await expect(heading).toHaveAttribute('aria-expanded', 'false', { timeout: 1000 });
});

test('review fast new revision reopens with keyboard focus on the current gate', async ({ page }) => {
  const fixture = await start(page);
  await openGate(page);
  const gate = page.getByTestId('trip-brief-plan-gate');
  await gate.getByRole('button', { name: '补充或调整旅行要求', exact: true }).click();
  await gate.getByLabel('想改哪里？').fill('午后留出休息时间');
  await gate.getByTestId('plan-gate-supplement').click();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'chat_start', session_id: 'A', run_id: 'run-A', message_id: 'review-revision', route_decision: { route: 'trip_refinement' } }]);
  await expect(page.getByTestId('generation-handoff')).toHaveAttribute('data-phase', 'gate');
  await sendFrames(page, [{ type: 'thinking', agent_name: 'request_contract_normalizer', content: '正在重新整理' }]);
  await expect(page.getByTestId('generation-handoff')).toHaveAttribute('data-phase', 'process');
  await sendFrames(page, [gateFrame(1), { type: 'chat_complete', run_id: 'run-A', run_status: 'awaiting_input', ts_ms: Date.now() }], true);
  await expect(gate).toBeVisible();
  await expect(gate.getByLabel('想改哪里？')).toHaveValue('');
  await sampleHandoffHeights(page);
  await assertOffline(page, fixture);
  await expect(gate.getByRole('heading', { name: '确认研究方案', exact: true })).toBeFocused({ timeout: 1000 });
});
