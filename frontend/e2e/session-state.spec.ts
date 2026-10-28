import { expect, test, type Page } from '@playwright/test';
import { deliveryBundle, sessionDetail, sessionSummary } from './fixtures/sessionData';
import { xianMixedTransportBundle } from './fixtures/xianBundle';

test.skip(process.env.JP_SESSION_STATE_E2E !== '1', 'Explicit offline session-state opt-in required');
const baseURL = process.env.JOURNEYPILOT_APP_URL || '';
if (process.env.JP_SESSION_STATE_E2E === '1' && !/^http:\/\/127\.0\.0\.1:\d+$/.test(baseURL)) throw new Error('Offline suite requires an explicit loopback Vite URL');

type StreamHarness = { send: (events: unknown[]) => void; close: () => void };
type FixtureWindow = Window & { offlineStream?: StreamHarness };

async function offlineApp(page: Page, options: { bundle?: boolean; recovery?: boolean; delayedA?: boolean; bundleData?: ReturnType<typeof deliveryBundle> } = {}) {
  const pageErrors: string[] = [], escapes: string[] = [], requests: string[] = [];
  let status: string = options.bundle ? 'completed' : 'running';
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
      return json(sessionDetail(id));
    }
    if (path === '/trip-runs') {
      const id = url.searchParams.get('session_id');
      return json({ runs: id === 'A' && (options.bundle || options.recovery) ? [{ run_id: 'run-A', session_id: 'A', status, title: '离线运行', mode: 'deep', created_at: '2026-10-25T08:00:00Z', updated_at: '2026-10-25T08:00:00Z' }] : [], total: id === 'A' ? 1 : 0 });
    }
    if (path === '/trip-runs/run-A') return json({ run: { run_id: 'run-A', session_id: 'A', status }, state: { pending_user_choice: null, latest_state_summary: {} }, execution: null, available_actions: [], events: [], controlled_trip_identity: { origin: { name: '北京' }, destinations: [{ name: '西安' }], start_date: '2026-11-01', end_date: '2026-11-02', party: { adults: 1, children: 0, elderly_companions: false, accessibility_required: false }, style: { primary: '轻松', secondary_interests: [], source: 'current' } } });
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
  await expect(page.getByTestId('itinerary-card-flow')).toBeVisible();
  await expect(page.locator('[data-itinerary-occurrence]')).toHaveCount(14);
  await expect(page.locator('[data-bundle-map-entity]')).toHaveCount(7);
  await expect(page.locator('.leaflet-overlay-pane path[data-route-entity]')).toHaveCount(6);
  await expect(page.locator('.leaflet-overlay-pane path[data-route-geometry="provider"]')).toHaveCount(4);
  await expect(page.locator('.leaflet-overlay-pane path[data-route-geometry="endpoint"]')).toHaveCount(2);
  expect(await page.locator('[data-itinerary-occurrence]').evaluateAll(nodes => nodes.slice(0, 7).map(node => node.getAttribute('data-entity-id')))).toEqual([
    'visit-terracotta', 'leg-terracotta-lunch', 'dining-lintong', 'leg-lunch-dayan', 'visit-dayan', 'leg-dayan-hotel', 'stay-bell-tower',
  ]);
  expect(await page.locator('.leaflet-overlay-pane path').evaluateAll(paths => paths.flatMap(path => path.getAnimations()).length)).toBe(0);

  const terracotta = page.locator('[data-itinerary-occurrence="d1-terracotta"]');
  const marker = page.locator('[data-bundle-map-entity="visit-terracotta"]');
  const map = page.getByTestId('bundle-leaflet-map');
  await terracotta.hover();
  await expect(marker).toHaveAttribute('data-linked', 'on');
  await expect(terracotta).toHaveAttribute('data-linked', 'on');
  await expect.poll(async () => {
    const [mapBox, markerBox] = await Promise.all([map.boundingBox(), marker.boundingBox()]);
    if (!mapBox || !markerBox) return false;
    const markerCenterX = markerBox.x + markerBox.width / 2;
    const markerCenterY = markerBox.y + markerBox.height / 2;
    const mapCenterX = mapBox.x + mapBox.width / 2;
    const mapCenterY = mapBox.y + mapBox.height / 2;
    return Math.abs(markerCenterX - mapCenterX) < 40 && Math.abs(markerCenterY - mapCenterY) < 40;
  }).toBe(true);

  const mapTrigger = terracotta.getByRole('button', { name: '在地图查看', exact: true });
  await mapTrigger.click();
  await expect(page.getByTestId('map-place-detail')).toBeVisible();
  await expect(terracotta).toHaveAttribute('data-selected', 'on');
  await page.getByRole('button', { name: '关闭地点详情', exact: true }).click();
  await expect(mapTrigger).toBeFocused();

  await page.getByTestId('day-summary-card-day-2').click();
  await expect(page.locator('[data-itinerary-occurrence]')).toHaveCount(7);
  await expect(page.locator('[data-bundle-map-entity]')).toHaveCount(4);
  await expect(page.locator('.leaflet-overlay-pane path[data-route-entity]')).toHaveCount(3);
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
  await page.screenshot({ path: test.info().outputPath('desktop-xian-three-columns.png'), fullPage: true });
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
  await expect(page.locator('[data-itinerary-occurrence]')).toHaveCount(19);
  const contentEntityIds = await page.locator('[data-itinerary-occurrence]').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-entity-id') ?? ''));
  expect(contentEntityIds.slice(0, 3)).toEqual(['leg-flight-demo', 'leg-ride-demo', 'visit-terracotta']);
  expect(contentEntityIds.slice(-2)).toEqual(['leg-station-taxi-demo', 'leg-rail-demo']);
  await expect(page.locator('[data-bundle-map-kind="transport_endpoint"]')).toHaveCount(4);
  await expect(page.getByLabel('路线图例')).toHaveCount(0);
  await expect(page.getByTestId('map-unlocated-places')).toHaveCount(0);

  const paths = page.locator('.leaflet-overlay-pane path[data-route-entity]');
  await expect(paths).toHaveCount(10);
  const mappedEntityIds = await paths.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-route-entity') ?? '').sort());
  expect(mappedEntityIds).toEqual(contentEntityIds.filter(id => id.startsWith('leg-')).sort());
  await expect(page.locator('path[data-route-geometry="provider"]')).toHaveCount(7);
  await expect(page.locator('path[data-route-geometry="direct"]')).toHaveCount(1);
  await expect(page.locator('path[data-route-geometry="endpoint"]')).toHaveCount(2);
  await expect(page.locator('path[data-route-segment="segment-flight-demo"]')).toHaveCSS('stroke', 'rgb(108, 99, 206)');
  await expect(page.locator('path[data-route-segment="segment-rail-demo"]')).toHaveCSS('stroke', 'rgb(198, 75, 69)');
  await expect(page.locator('path[data-route-segment="segment-ride-demo"]')).toHaveAttribute('data-route-mode', 'ride_hailing');
  await expect(page.locator('path[data-route-segment="segment-ride-demo"]')).toHaveCSS('stroke', 'rgb(194, 106, 27)');
  await expect(page.locator('path[data-route-segment="segment-station-taxi-demo"]')).toHaveAttribute('data-route-mode', 'taxi');

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

test('conversation restores focus to its newly rendered trigger on Escape and return', async ({ page }) => {
  const fixture = await offlineApp(page, { bundle: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  const adjust = page.getByRole('button', { name: '告诉我想怎么改……', exact: true });
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
