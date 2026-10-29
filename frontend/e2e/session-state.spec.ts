import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { deliveryBundle, sessionDetail, sessionSummary } from './fixtures/sessionData';
import { xianLayoutBundle, xianMixedTransportBundle, xianTransportDisplayBundle } from './fixtures/xianBundle';

test.skip(process.env.JP_SESSION_STATE_E2E !== '1', 'Explicit offline session-state opt-in required');
const baseURL = process.env.JOURNEYPILOT_APP_URL || '';
if (process.env.JP_SESSION_STATE_E2E === '1' && !/^http:\/\/127\.0\.0\.1:\d+$/.test(baseURL)) throw new Error('Offline suite requires an explicit loopback Vite URL');

type StreamHarness = { send: (events: unknown[]) => void; close: () => void };
type FixtureWindow = Window & { offlineStream?: StreamHarness; __offlineChatBodies?: unknown[]; __offlineFailChatAttempts?: number };

async function offlineApp(page: Page, options: { bundle?: boolean; recovery?: boolean; delayedA?: boolean; research?: boolean; planGate?: boolean; specialParty?: boolean; bundleData?: ReturnType<typeof deliveryBundle> } = {}) {
  const pageErrors: string[] = [], escapes: string[] = [], requests: string[] = [];
  let status: string = options.planGate ? 'awaiting_input' : options.bundle ? 'completed' : 'running';
  let recovered = false, releaseA: (() => void) | undefined;
  let aReads = 0;
  const aWait = new Promise<void>(resolve => { releaseA = resolve; });
  const bundle = options.bundleData ?? deliveryBundle();
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.addInitScript(() => {
    if (localStorage.getItem('sta_last_session_id') === null) {
      localStorage.setItem('sta_last_session_id', 'A');
    }
    const originalFetch = window.fetch.bind(window);
    const fixtureWindow = window as FixtureWindow;
    fixtureWindow.__offlineChatBodies = [];
    window.fetch = (input, init) => {
      const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
      if (url.pathname !== '/api/chat-stream') return originalFetch(input, init);
      try { fixtureWindow.__offlineChatBodies?.push(JSON.parse(String(init?.body ?? '{}'))); } catch { /* ignore non-JSON bodies */ }
      if ((fixtureWindow.__offlineFailChatAttempts ?? 0) > 0) {
        fixtureWindow.__offlineFailChatAttempts = (fixtureWindow.__offlineFailChatAttempts ?? 0) - 1;
        return Promise.resolve(new Response(JSON.stringify({ detail: '离线模拟提交失败' }), { status: 503, headers: { 'content-type': 'application/json' } }));
      }
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
          thinking_steps: [
            { step_id: 'research-start', agent_name: '目的地调研', step_name: '查询景点与体验', content: '正在整理厦门的海岸步道与市区体验', timestamp: '2026-10-25T08:00:00Z', progress_status: 'running' },
            { step_id: 'place-result', agent_name: '目的地调研', step_name: '地点搜索', content: '', timestamp: '2026-10-25T08:00:01Z', is_tool_call: true, tool_name: 'global_place_search', tool_args: '{"query":"厦门 海岸步道"}', tool_result: '找到 3 个适合安排进行程的地点', tool_status: 'completed', result_preview: [{ title: '环岛路海岸步道', detail: '适合安排半天散步与骑行，可串联曾厝垵和音乐广场。', url: 'https://example.org/xiamen-coast' }] },
            { step_id: 'transport-start', agent_name: '交通查询', step_name: '查询往返交通', content: '正在比较深圳到厦门的火车方案', timestamp: '2026-10-25T08:00:02Z', progress_status: 'running' },
            { step_id: 'route-result', agent_name: '交通查询', step_name: '火车查询', content: '', timestamp: '2026-10-25T08:00:03Z', is_tool_call: true, tool_name: 'train_search', tool_args: '{"from_name":"深圳北","to_name":"厦门北","date":"2026-11-01"}', tool_result: '已整理往返车次与到站衔接', tool_status: 'completed' },
            { step_id: 'stay-start', agent_name: '住宿查询', step_name: '查询住宿', content: '正在筛选交通方便的住宿区域', timestamp: '2026-10-25T08:00:04Z', progress_status: 'running' },
          ],
        }],
      } : sessionDetail(id));
    }
    if (path === '/trip-runs') {
      const id = url.searchParams.get('session_id');
      return json({ runs: id === 'A' && (options.bundle || options.recovery || options.planGate) ? [{ run_id: 'run-A', session_id: 'A', status, title: '离线运行', mode: 'deep', created_at: '2026-10-25T08:00:00Z', updated_at: '2026-10-25T08:00:00Z' }] : [], total: id === 'A' ? 1 : 0 });
    }
    if (path === '/trip-runs/run-A') return json({ run: { run_id: 'run-A', session_id: 'A', status }, state: { pending_user_choice: options.planGate ? {
      type: 'approval_gate', gate: 'plan', read_only: false, terminal_status: null,
      payload: { gate: 'plan', revision: 0, revision_limit: 2, decision_options: ['approve', 'supplement', 'cancel'], plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '安排适合放松的城市路线' } }] }, recognized_requirements: { hard: [], preferences: [{ requirement_id: 'slow', summary: '想慢一点，每天少走一些' }], attention: [] }, unresolved_requirement_ids: [] },
    } : null, latest_state_summary: {} }, execution: null, available_actions: [], events: [], controlled_trip_identity: { origin: { name: '北京' }, destinations: [{ name: '西安' }], start_date: '2026-11-01', end_date: '2026-11-02', party: options.specialParty ? { adults: 2, children: 1, elderly_companions: true, accessibility_required: true } : { adults: 1, children: 0, elderly_companions: false, accessibility_required: false }, style: { primary: '轻松', secondary_interests: ['当地美食'], source: 'current' } } });
    if (path === '/trip-runs/run-A/bundle/current') return options.bundle || recovered ? json(bundle) : json({ detail: 'not ready' }, 404);
    if (path === '/trip-runs/run-A/events') {
      const after = Number(url.searchParams.get('after_sequence'));
      const ready = options.bundle || recovered;
      const terminalReady = ready && !options.planGate;
      return json({ run_id: 'run-A', requested_after_sequence: after, replay_floor_sequence: 1, latest_sequence: terminalReady ? 2 : 0, next_after_sequence: terminalReady ? Math.max(after, 2) : after, window_expired: false, run_status: options.planGate ? 'awaiting_input' : ready ? 'completed' : status, current_bundle_id: terminalReady ? 'bundle-1' : null,
        events: terminalReady && after < 2 ? [{ event_id: 2, run_id: 'run-A', sequence: 2, event_type: 'run.terminal', payload: { status: 'completed', bundle_id: 'bundle-1' }, created_at: '2026-10-25T08:00:00Z' }] : [] });
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
  const fixture = await offlineApp(page);
  await page.goto('/');
  await expect(page.getByText('A 的历史回答', { exact: true })).toBeVisible();
  await page.getByTestId('brief-input').fill('离线取消测试'); await page.getByTestId('send-button').click();
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'chat_start', session_id: 'A', message_id: 'cancel-A', run_id: 'run-A', route_decision: { route: 'trip_planning' } }, { type: 'trip_summary_card', summary_card: { headline: '离线测试行程', summary: '准备调研', current_focus: '离线调研', compact_line: '本地夹具', facts: [], priorities: [] } }, { type: 'chat_chunk', content: '可保留的阶段内容' }]);
  await expect(page.getByText('可保留的阶段内容', { exact: true })).toBeVisible();
  await page.getByTestId('send-button').click();
  await expect(page.getByPlaceholder('告诉 JourneyPilot 这趟行程想怎么调整…')).toBeVisible();
  expect(fixture.requests.some(request => request.startsWith('POST /api/trip-runs/run-A/control'))).toBe(true);
  await expect(page.getByText('可保留的阶段内容', { exact: true })).toBeVisible();
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

test('restores staged research with formatted tool calls and results', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { recovery: true, research: true });
  await page.goto('/');
  const workspace = page.getByTestId('generation-journey-panel');
  await expect(workspace.getByTestId('research-agent-destination')).toContainText('找到 3 个适合安排进行程的地点');
  await expect(workspace.getByTestId('research-agent-destination').getByRole('button')).toHaveCount(0);
  await expect(workspace.getByTestId('research-agent-destination')).toContainText('厦门 海岸步道');
  await workspace.getByTestId('research-agent-destination').getByTestId('research-query').locator('summary').click();
  await expect(workspace.getByRole('link', { name: '环岛路海岸步道' })).toBeVisible();
  await expect(workspace.getByTestId('research-agent-transport')).toContainText('已整理往返车次与到站衔接');
  await expect(workspace.getByTestId('research-agent-transport')).toContainText('深圳北 -> 厦门北');
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
  await expect(workspace.locator('.generation-progress > h2')).toHaveText('等待确认旅行需求');
  await expect(gate).toBeVisible();
  await expect(gate).toContainText('想慢一点，每天少走一些');
  await expect(page.getByRole('heading', { name: '确认这趟旅行', exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '接下来，我们会这样安排', exact: true })).toHaveCount(0);
  await sidebar.evaluate(node => node.setAttribute('data-mount-probe', 'kept'));
  await page.screenshot({ path: '../output/polish/20261029-1817-unified-planning-workspace/workspace-2000-pending-gate.png', fullPage: true });

  await gate.getByRole('button', { name: '补充或调整旅行要求', exact: true }).click();
  const guide = gate.getByLabel('想改哪里？');
  await guide.fill('每天只安排一个主要景点，午后留出休息时间');
  await page.screenshot({ path: '../output/polish/20261029-1817-unified-planning-workspace/workspace-2000-gate-editing.png', fullPage: true });
  await page.evaluate(() => { (window as FixtureWindow).__offlineFailChatAttempts = 3; });
  await gate.getByTestId('plan-gate-supplement').click();
  await expect(gate.getByRole('alert')).toContainText('旅行信息和修改已保留');
  await expect(guide).toHaveValue('每天只安排一个主要景点，午后留出休息时间');
  await expect(sidebar).toHaveAttribute('data-mount-probe', 'kept');

  await gate.getByTestId('plan-gate-supplement').click();
  await expect.poll(() => page.evaluate(() => {
    const bodies = (window as FixtureWindow).__offlineChatBodies ?? [];
    return (bodies[bodies.length - 1] as { gate_decision?: { action?: string; content?: string } } | undefined)?.gate_decision;
  })).toEqual({ action: 'supplement', content: '每天只安排一个主要景点，午后留出休息时间' });
  await sendFrames(page, [
    { type: 'chat_start', session_id: 'A', run_id: 'run-A', message_id: 'gate-supplement', route_decision: { route: 'trip_refinement' } },
    { type: 'approval_gate_raised', run_id: 'run-A', gate: 'plan', run_status: 'awaiting_input', payload: { gate: 'plan', revision: 1, revision_limit: 2, decision_options: ['approve', 'supplement', 'cancel'], plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: {} }] }, recognized_requirements: { hard: [], preferences: [{ requirement_id: 'slow', summary: '每天只安排一个主要景点' }], attention: [] }, unresolved_requirement_ids: [] } },
    { type: 'chat_complete', run_id: 'run-A', run_status: 'awaiting_input', ts_ms: Date.now() },
  ], true);
  await expect(gate).toContainText('每天只安排一个主要景点');
  await expect(guide).toHaveValue('');
  await expect(sidebar).toHaveAttribute('data-mount-probe', 'kept');
  await expect(workspace.locator('.generation-progress > h2')).toHaveText('等待确认旅行需求');

  await gate.getByRole('button', { name: '确认并开始生成', exact: true }).click();
  await expect.poll(() => page.evaluate(() => {
    const bodies = (window as FixtureWindow).__offlineChatBodies ?? [];
    return (bodies[bodies.length - 1] as { gate_decision?: { action?: string } } | undefined)?.gate_decision?.action;
  })).toBe('approve');
  await sendFrames(page, [
    { type: 'chat_start', session_id: 'A', run_id: 'run-A', message_id: 'gate-approve', route_decision: { route: 'trip_refinement' } },
    { type: 'thinking', message_id: 'gate-approve', agent_name: '行程规划', content: '正在把景点和交通排进每天路线', step_name: '安排路线', ts_ms: Date.now() },
  ]);
  await expect(gate).toHaveCount(0);
  await expect(workspace.locator('.research-panel-title')).toHaveText('安排每天路线');
  await expect(sidebar).toHaveAttribute('data-mount-probe', 'kept');
  await expect(sidebar.locator('.generation-trip-card')).toBeVisible();
  await page.screenshot({ path: '../output/polish/20261029-1817-unified-planning-workspace/workspace-2000-approved-research.png', fullPage: true });
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
  await page.screenshot({ path: '../output/polish/20261029-1817-unified-planning-workspace/workspace-390-pending-gate.png', fullPage: true });

  await page.setViewportSize({ width: 2000, height: 880 });
  await page.reload();
  await expect(gate).toBeVisible();
  await expect(workspace.locator('.generation-progress > h2')).toHaveText('等待确认旅行需求');
  const sidebar = workspace.locator('.generation-planning-sidebar');
  await sidebar.evaluate(node => node.setAttribute('data-mount-probe', 'kept'));

  await gate.getByRole('button', { name: '取消规划', exact: true }).click();
  await expect.poll(() => page.evaluate(() => {
    const bodies = (window as FixtureWindow).__offlineChatBodies ?? [];
    return (bodies[bodies.length - 1] as { gate_decision?: { action?: string } } | undefined)?.gate_decision?.action;
  })).toBe('cancel');
  await expect.poll(() => page.evaluate(() => Boolean((window as FixtureWindow).offlineStream))).toBe(true);
  await sendFrames(page, [{ type: 'run_cancelled', run_id: 'run-A', final_content: '已取消当前规划。', ts_ms: Date.now() }]);
  await expect(gate).toHaveCount(0);
  await expect(workspace).toBeVisible();
  await expect(sidebar).toHaveAttribute('data-mount-probe', 'kept');
  await expect(workspace.locator('.generation-progress > h2')).toHaveText('旅行规划已取消');
  await expect(page.getByText('这次规划已取消。', { exact: true })).toBeVisible();
  await expect(page.getByTestId('new-trip-hero')).toHaveCount(0);
  await page.screenshot({ path: '../output/polish/20261029-1817-unified-planning-workspace/workspace-2000-cancelled.png', fullPage: true });
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
    await expect(gate).toContainText('有长辈同行');
    await expect(gate).toContainText('需要无障碍安排');
    await expect(workspace.locator('.generation-trip-card')).toContainText('1 位儿童');
    await expect(workspace.locator('.generation-trip-card')).toContainText('有长辈同行');
    await expect(workspace.locator('.generation-trip-card')).toContainText('需要无障碍安排');
    await expect(gate.getByRole('button', { name: '确认并开始生成', exact: true })).toBeVisible();
    await expect(gate.getByRole('button', { name: '确认并开始生成', exact: true })).toBeEnabled();
    await expect(gate.getByRole('button', { name: '取消规划', exact: true })).toBeVisible();
    await expect(gate.getByRole('button', { name: '取消规划', exact: true })).toBeEnabled();
    await assertGateGeometry();
    if (width === 640) await page.screenshot({ path: '../output/polish/20261029-1817-unified-planning-workspace/workspace-640-pending-gate-special.png', fullPage: true });
    await gate.getByRole('button', { name: '补充或调整旅行要求', exact: true }).click();
    const guide = gate.getByLabel('想改哪里？');
    await guide.fill('每天少走一些，预留无障碍休息点');
    await expect(gate.getByTestId('plan-gate-supplement')).toBeVisible();
    await expect(gate.getByTestId('plan-gate-supplement')).toBeEnabled();
    await assertGateGeometry();
  }

  await page.setViewportSize({ width: 640, height: 900 });
  await page.reload();
  const gate = page.getByTestId('trip-brief-plan-gate');
  const workspace = page.getByTestId('generation-journey-panel');
  await expect(gate).toBeVisible();
  await expect(gate).toContainText('有长辈同行');
  await expect(gate).toContainText('需要无障碍安排');
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

test('delivered trip refinement gate keeps party context and actions inside the narrow conversation', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await offlineApp(page, { bundle: true, planGate: true, specialParty: true });
  await page.goto('/');
  await expect(page.getByTestId('interactive-itinerary')).toBeVisible();
  await page.getByRole('button', { name: '调整', exact: true }).first().click();
  const gate = page.getByTestId('trip-brief-plan-gate');
  await expect(gate).toBeVisible();
  await expect(gate).toContainText('2 位成人');
  await expect(gate).toContainText('1 位儿童');
  await expect(gate).toContainText('有长辈同行');
  await expect(gate).toContainText('需要无障碍安排');
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
  await page.screenshot({ path: '../output/polish/20261029-1817-unified-planning-workspace/bundle-adjustment-gate-1280.png', fullPage: true });
  await gate.locator('.plan-gate-actions').scrollIntoViewIfNeeded();
  await expect(approve).toBeVisible();
  await expect(cancel).toBeVisible();
  expect(await gate.locator('.plan-gate-actions').evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return rect.top >= 0 && rect.bottom <= window.innerHeight;
  })).toBe(true);
  await page.screenshot({ path: '../output/polish/20261029-1817-unified-planning-workspace/bundle-adjustment-gate-actions-1280.png', fullPage: true });
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
  const contentScroll = page.getByTestId('interactive-itinerary');
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

  // 可画市内路线的显式操作也保留：点击“查看路线”才进入路线视野。
  await page.locator('[data-itinerary-occurrence="d1-transfer-lunch"]').getByRole('button', { name: '查看路线', exact: true }).click();
  await expect(page.getByTestId('map-place-detail')).toContainText('24 分钟');
  await expect(page.getByTestId('map-place-detail')).toContainText('9.2 公里');
  await expect.poll(async () => (await mapCamera(page, ['visit-terracotta'])).markers['visit-terracotta']).not.toEqual(initialCamera.markers['visit-terracotta']);
  const routeCamera = await settledCamera(page, ['visit-terracotta', 'visit-dayan']);
  await page.getByRole('button', { name: '关闭地点详情', exact: true }).click();
  await expect(page.getByTestId('map-place-detail')).toHaveCount(0);
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
  const evidenceDir = '../output/polish/20261029-1917-workspace-visual';
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
  const evidenceDir = '../output/polish/20261029-1917-workspace-visual';
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
  const evidenceDir = '../output/polish/20261029-1917-workspace-visual';
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
  const evidenceDir = '../output/polish/20261029-1917-workspace-visual';
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
  const evidenceDir = '../output/polish/20261029-1917-hover-intent';
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
  const evidenceDir = '../output/polish/20261029-1917-transport-display';
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
  await expect(railOccurrence.getByRole('button', { name: '查看路线', exact: true })).toHaveCount(0);

  const flight = page.getByTestId('transport-card-leg-display-flight');
  await expect(flight).toContainText('飞机');
  await expect(flight).toContainText('CA1234');
  await expect(flight).toContainText('PEK');
  await expect(flight).toContainText('XIY');
  await expect(flight.locator('.transport-mode-icon')).toHaveCount(1);
  await expect(flight).not.toContainText('班次');
  await expect(page.locator('[data-itinerary-occurrence="d1-display-flight"]').getByRole('button', { name: '查看路线', exact: true })).toHaveCount(0);

  const direct = page.getByTestId('transport-card-leg-display-metro-direct');
  await expect(direct).toContainText('钟楼站');
  await expect(direct).toContainText('小寨站');
  await expect(direct).toContainText('42 分钟');
  await expect(direct).toContainText('¥5');
  await expect(direct).not.toContainText('市内公共交通');
  await expect(direct).not.toContainText('换乘');
  await expect(direct).not.toContainText('直达');
  await expect(direct.getByTestId('transport-summary').locator('dt.sr-only')).toHaveCount(2);
  await expect(direct).not.toContainText('西安钟楼饭店');
  await expect(direct).not.toContainText('陕西历史博物馆');
  await expect(direct.locator('.transport-mode-icon')).toHaveCount(1);
  await expect(direct.getByTestId('transport-segments-toggle')).toContainText('展开 3 个路线步骤');

  const transfer = page.getByTestId('transport-card-leg-display-metro-transfer');
  await expect(transfer).toContainText('北大街站（地铁2号线·4号线换乘）');
  await expect(transfer).toContainText('大雁塔站（雁塔北路南口）');
  await expect(transfer).toContainText('换乘 1 次');
  await expect(transfer).toContainText('¥6');
  await expect(transfer).not.toContainText('市内公共交通');
  await expect(transfer.getByTestId('transport-summary').locator('dt.sr-only')).toHaveCount(2);

  const mixed = page.getByTestId('transport-card-leg-display-metro-mixed');
  await expect(mixed).toContainText('地铁 / 公交');
  await expect(mixed).toContainText('地铁 北大街站（地铁2号线·4号线换乘）');
  await expect(mixed).toContainText('地铁 钟楼站');
  await expect(mixed).not.toContainText('公交 钟楼站');
  await expect(mixed).not.toContainText('换乘 1 次');
  await expect(mixed).not.toContainText('换乘 2 次');

  const unproven = page.getByTestId('transport-card-leg-display-metro-unproven');
  await expect(unproven).toContainText('27 分钟');
  await expect(unproven).not.toContainText('陕西历史博物馆');
  await expect(unproven).not.toContainText('子午路张记肉夹馍（小寨店）');
  await expect(unproven).not.toContainText('¥0');
  await expect(unproven).not.toContainText('换乘');

  await page.screenshot({ path: `${evidenceDir}/transport-desktop-1440.png`, fullPage: true });

  await transfer.evaluate((node) => {
    const scroller = node.closest('.journey-content-scroll');
    if (!scroller) return;
    const nodeRect = node.getBoundingClientRect();
    const scrollerRect = scroller.getBoundingClientRect();
    scroller.scrollTop += nodeRect.top - scrollerRect.top - 120;
  });
  await expect(transfer).toBeInViewport();
  await page.screenshot({ path: `${evidenceDir}/transport-metro-desktop-1440.png`, fullPage: true });

  await direct.getByTestId('transport-segments-toggle').click();
  await expect(direct.getByTestId('transport-segments')).toBeVisible();
  await expect(direct).toContainText('地铁2号线');
  await expect(direct).not.toContainText('3 次换乘');
  await direct.getByTestId('transport-segments-toggle').click();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByTestId('canvas-pill').click();
  const sheet = page.getByTestId('canvas-sheet');
  await sheet.getByTestId('sheet-handle').click();
  await expect(sheet).toHaveAttribute('data-detent', '92');
  await sheet.getByTestId('day-summary-card-day-1').click();
  const phoneTransfer = sheet.getByTestId('transport-card-leg-display-metro-transfer');
  await expect(phoneTransfer).toBeVisible();
  await page.waitForTimeout(600);
  await phoneTransfer.evaluate((node) => {
    const scroller = node.closest('.journey-content-scroll');
    if (!scroller) return;
    const nodeRect = node.getBoundingClientRect();
    const scrollerRect = scroller.getBoundingClientRect();
    scroller.scrollTop += nodeRect.top - scrollerRect.top - 120;
  });
  await expect(phoneTransfer).toBeInViewport();
  expect(await sheet.evaluate((node) => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${evidenceDir}/transport-phone-390.png`, fullPage: true });
  await assertOffline(page, fixture);
});

test('conversation restores focus to its newly rendered trigger on Escape and return', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  const adjust = page.getByRole('button', { name: '调整', exact: true });
  await adjust.click();
  const composer = page.getByRole('textbox', { name: '告诉我想怎么改……', exact: true });
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
