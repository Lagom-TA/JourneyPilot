import { expect, test, type Page } from '@playwright/test';
import { deliveryBundle, sessionDetail, sessionSummary } from './fixtures/sessionData';

test.skip(process.env.JP_SESSION_STATE_E2E !== '1', 'Explicit offline session-state opt-in required');
const baseURL = process.env.JOURNEYPILOT_APP_URL || '';
if (process.env.JP_SESSION_STATE_E2E === '1' && !/^http:\/\/127\.0\.0\.1:\d+$/.test(baseURL)) throw new Error('Offline suite requires an explicit loopback Vite URL');

type StreamHarness = { send: (events: unknown[]) => void; close: () => void };
type FixtureWindow = Window & { offlineStream?: StreamHarness };

async function offlineApp(page: Page, options: { bundle?: boolean; recovery?: boolean; delayedA?: boolean } = {}) {
  const pageErrors: string[] = [], escapes: string[] = [], requests: string[] = [];
  let status: string = options.bundle ? 'completed' : 'running';
  let recovered = false, releaseA: (() => void) | undefined;
  let aReads = 0;
  const aWait = new Promise<void>(resolve => { releaseA = resolve; });
  const bundle = deliveryBundle();
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.addInitScript(() => {
    if (localStorage.getItem('sta_last_session_id') === null) {
      localStorage.setItem('sta_last_session_id', 'A');
    }
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
      if (url.pathname !== '/api/chat-stream') return originalFetch(input, init);
      const encoder = new TextEncoder();
      const stream = new ReadableStream<Uint8Array>({ start(controller) {
        (window as FixtureWindow).offlineStream = {
          send(events) { for (const event of events) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`)); },
          close() { controller.close(); delete (window as FixtureWindow).offlineStream; },
        };
        init?.signal?.addEventListener('abort', () => { controller.error(new DOMException('Aborted', 'AbortError')); delete (window as FixtureWindow).offlineStream; }, { once: true });
      } });
      return Promise.resolve(new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } }));
    };
  });
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== baseURL) { escapes.push(request.url()); await route.abort('blockedbyclient'); return; }
    if (!url.pathname.startsWith('/api/')) { await route.continue(); return; }
    requests.push(`${request.method()} ${url.pathname}${url.search}`);
    const json = async (body: unknown, code = 200) => route.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify(body) });
    const path = url.pathname.slice(4);
    if (path === '/user/sessions') return json(['A', 'B'].map(sessionSummary));
    if (/^\/user\/sessions\/[AB]$/.test(path)) {
      const id = path.at(-1)!;
      if (id === 'A' && ++aReads > 1 && options.delayedA) await aWait;
      return json(sessionDetail(id));
    }
    if (path === '/trip-runs') {
      const id = url.searchParams.get('session_id');
      return json({ runs: id === 'A' && (options.bundle || options.recovery) ? [{ run_id: 'run-A', session_id: 'A', status, title: '离线运行', mode: 'deep' }] : [], total: id === 'A' ? 1 : 0 });
    }
    if (path === '/trip-runs/run-A') return json({ run: { run_id: 'run-A', session_id: 'A', status }, state: { pending_user_choice: null, latest_state_summary: {} }, execution: null, available_actions: [], events: [], controlled_trip_identity: { origin: { name: '北京' }, destinations: [{ name: '杭州' }], start_date: '2026-11-01', end_date: '2026-11-02', party: { adults: 1, children: 0, elderly_companions: false, accessibility_required: false }, style: { primary: '轻松', secondary_interests: [], source: 'current' } } });
    if (path === '/trip-runs/run-A/bundle/current') return options.bundle || recovered ? json(bundle) : json({ detail: 'not ready' }, 404);
    if (path === '/trip-runs/run-A/events') {
      const after = Number(url.searchParams.get('after_sequence'));
      const ready = options.bundle || recovered;
      return json({ run_id: 'run-A', requested_after_sequence: after, replay_floor_sequence: 1, latest_sequence: ready ? 2 : 0, next_after_sequence: ready ? Math.max(after, 2) : after, window_expired: false, run_status: ready ? 'completed' : status, current_bundle_id: ready ? 'bundle-1' : null,
        events: ready && after < 2 ? [{ event_id: 2, run_id: 'run-A', sequence: 2, event_type: 'run.terminal', payload: { status: 'completed', bundle_id: 'bundle-1' }, created_at: '2026-10-25T08:00:00Z' }] : [] });
    }
    if (path === '/trip-runs/run-A/control') { expect(request.postDataJSON()).toEqual({ action: 'cancel', session_id: 'A' }); status = 'cancelled'; return json({ accepted: true, run_status: 'cancelled', message: '已取消' }); }
    if (path === '/trip-runs/run-A/bundle/current/weather/refresh') return json({ refresh_id: request.postDataJSON().refresh_id, attempted: false, committed: false, used_previous_values: true, refusal_reason: null, bundle });
    if (path === '/trip-runs/run-A/workspace/undo-head') return json({ can_undo: false, mutation_id: null });
    if (path === '/presets') return json([]);
    if (path === '/user/default-origin') return json({ place: null });
    if (path === '/product/trip-planner') return json({ primary_styles: [{ id: 'relaxed', label: '轻松', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 5000, inspiration_prompts: [] });
    if (path === '/knowledge/collections/travel_knowledge/stats') return json({ total: 0, sources: 0, source_details: [] });
    if (path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: [] });
    escapes.push(request.url()); return json({ detail: 'Unmocked API request' }, 501);
  });
  return { pageErrors, escapes, requests, releaseA: () => releaseA?.(), completeRecovery: () => { recovered = true; status = 'completed'; } };
}
async function sendFrames(page: Page, events: unknown[], close = false) {
  await page.evaluate(({ events, close }) => { const stream = (window as FixtureWindow).offlineStream; if (!stream) throw new Error('No mocked SSE stream'); stream.send(events); if (close) stream.close(); }, { events, close });
}
async function selectSession(page: Page, id: string) {
  const open = page.getByRole('button', { name: '展开侧栏', exact: true });
  if (await open.isVisible()) await open.click();
  const mobile = page.getByTestId('sidebar-open');
  if (await mobile.isVisible()) await mobile.click();
  await page.getByText(`离线会话 ${id}`, { exact: true }).click();
}
async function assertOffline(page: Page, fixture: Awaited<ReturnType<typeof offlineApp>>) {
  expect(fixture.pageErrors).toEqual([]); expect(fixture.escapes).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await test.info().attach('offline-boundaries', { body: JSON.stringify(fixture, null, 2), contentType: 'application/json' });
}

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
  await expect.poll(() => page.evaluate(() => localStorage.getItem('sta_last_session_id'))).toBe('B');
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

test('cancels through HTTP control and leaves the composer usable', async ({ page }) => {
  const fixture = await offlineApp(page, { recovery: true });
  await page.goto('/');
  await expect(page.getByText('A 的历史回答', { exact: true })).toBeVisible();
  await page.getByTestId('brief-input').fill('离线取消测试'); await page.getByTestId('send-button').click();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'chat_start', session_id: 'A', message_id: 'cancel-A', run_id: 'run-A', route_decision: { route: 'trip_planning' } }, { type: 'trip_summary_card', summary_card: { headline: '离线测试行程', summary: '准备调研', current_focus: '离线调研', compact_line: '本地夹具', facts: [], priorities: [] } }, { type: 'chat_chunk', content: '可保留的阶段内容' }]);
  await expect(page.getByText('可保留的阶段内容', { exact: true })).toBeVisible();
  await page.getByTestId('boarding-pass-stop').click();
  await expect(page.getByPlaceholder('告诉 JourneyPilot 这趟行程想怎么调整…')).toBeVisible();
  expect(fixture.requests.some(request => request.startsWith('POST /api/trip-runs/run-A/control'))).toBe(true);
  await expect(page.getByText('可保留的阶段内容', { exact: true })).toBeVisible();
  await assertOffline(page, fixture);
});

test('recovers durable delivery without a stream and keeps recovery mounted across navigation', async ({ page }) => {
  const fixture = await offlineApp(page, { recovery: true });
  await page.goto('/');
  await expect(page.getByText('A 的历史回答', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: '资料来源', exact: true }).click();
  await expect(page.getByRole('heading', { name: '资料来源', exact: true })).toBeVisible();
  fixture.completeRecovery();
  await expect.poll(() => fixture.requests.filter(request => request.startsWith('GET /api/trip-runs/run-A/bundle/current')).length).toBeGreaterThan(1);
  await selectSession(page, 'A');
  await expect(page.getByTestId('workspace-canvas')).toBeVisible();
  await page.getByTestId('report-view-tab').click();
  await expect(page.getByTestId('full-report')).toBeVisible();
  await expect(page.getByText('离线旅行报告', { exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('desktop-session-report.png'), fullPage: true });
  await assertOffline(page, fixture);
});

test('phone restores the bundle without opening a sheet and navigates between lazy pages', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const fixture = await offlineApp(page, { bundle: true });
  await page.goto('/');
  await expect(page.getByText('A 的历史回答', { exact: true })).toBeVisible();
  await expect(page.getByTestId('canvas-pill')).toBeVisible();
  await expect(page.getByTestId('report-view-tab')).toHaveCount(0);
  await page.getByTestId('canvas-pill').click();
  await page.getByTestId('report-view-tab').click();
  await expect(page.getByTestId('full-report')).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('phone-session-report.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await page.getByTestId('sidebar-open').click();
  await page.getByRole('link', { name: '旅行风格', exact: true }).click();
  await expect(page.getByRole('heading', { name: '旅行风格', exact: true })).toBeVisible();
  await page.getByTestId('sidebar-open').click();
  await page.getByRole('link', { name: '我的偏好', exact: true }).click();
  await expect(page.getByRole('heading', { name: '我的偏好', exact: true })).toBeVisible();
  await assertOffline(page, fixture);
});
