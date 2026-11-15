import { test, expect, type Page } from '@playwright/test';
import { xianLayoutBundle } from './fixtures/xianBundle';
import { sessionDetail, sessionSummary } from './fixtures/sessionData';

type DeliveryFixture = ReturnType<typeof xianLayoutBundle>;

async function openDelivery(page: Page, options: { days?: number; readonly?: boolean; tilesFail?: boolean; longTitle?: boolean; messages?: ReturnType<typeof sessionDetail>['messages']; mutate?: (bundle: DeliveryFixture) => void } = {}) {
  const errors: string[] = [];
  const bundle = xianLayoutBundle({ dayCount: options.days ?? 14, longTitle: options.longTitle });
  bundle.workspace.itinerary.unresolved = ['第 2 天下午尚未安排具体活动。'];
  if (bundle.report_projection.document) bundle.report_projection.document.unresolved = [...bundle.workspace.itinerary.unresolved];
  options.mutate?.(bundle);
  page.on('pageerror', (error) => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('journeypilot.last-session-id', 'A'));
  await page.route('**/appmaptile?**', (route) => options.tilesFail
    ? route.abort()
    : route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e9e8df"/></svg>' }));
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.startsWith('/api/')) return route.continue();
    const path = pathname.slice(4);
    const run = { run_id: 'run-A', session_id: 'A', status: 'completed', title: '离线行程', mode: 'deep', created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z' };
    let body: unknown = [];
    let status = 200;
    if (path === '/user/sessions') body = [sessionSummary('A')];
    else if (path === '/user/sessions/A') body = { ...sessionDetail('A'), ...(options.messages ? { messages: options.messages } : {}) };
    else if (path === '/trip-runs') body = { runs: options.readonly ? [{ ...run, run_id: 'run-B', updated_at: '2026-11-02T00:00:00Z' }, run] : [run], total: options.readonly ? 2 : 1 };
    else if (path === '/trip-runs/run-A') body = { run, state: { pending_user_choice: null, latest_state_summary: {} }, execution: null, available_actions: [], events: [] };
    else if (path === '/trip-runs/run-A/bundle/current') body = bundle;
    else if (path === '/trip-runs/run-A/bundle/current/pdf') { status = 503; body = { detail: { code: 'pdf_temporarily_unavailable', message: '暂时不可用' } }; }
    else if (path.endsWith('/weather/refresh')) body = { refresh_id: route.request().postDataJSON().refresh_id, attempted: false, committed: false, used_previous_values: true, refusal_reason: null, bundle };
    else if (path.endsWith('/events')) body = { run_id: 'run-A', requested_after_sequence: 0, replay_floor_sequence: 1, latest_sequence: 0, next_after_sequence: 0, window_expired: false, run_status: 'completed', current_bundle_id: bundle.manifest.bundle_id, events: [] };
    else if (path === '/product/trip-planner') body = { primary_styles: [{ id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 14000, inspiration_prompts: [] };
    else if (path === '/user/default-origin') body = { place: null };
    else if (path.endsWith('/profile')) body = { preferences: {} };
    else if (path.endsWith('/facts')) body = { facts: [] };
    else if (path.endsWith('/stats')) body = { total: 0, sources: 0, source_details: [] };
    await route.fulfill({ status, json: body });
  });
  await page.goto('/?view=chat&session_id=A&run_id=run-A');
  await expect(page.getByTestId('bundle-leaflet-map')).toBeVisible();
  return { errors, bundle };
}

const savedNotice = '旅行方案已保存，可以查看完整行程。';
const researchNotice = {
  id: 'research-notice', role: 'assistant' as const, content: savedNotice, display_content: savedNotice,
  timestamp: '2026-10-25T08:00:00Z',
  thinking_steps: [{ id: 'research-step', agent_name: 'destination_researcher', content: '查阅目的地资料', step_name: '目的地调研', timestamp: '2026-10-25T08:00:00Z', end_time: '2026-10-25T08:00:02Z' }],
};

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`adjustment navigation and composer stay anchored at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const { errors } = await openDelivery(page, { days: 2, messages: [researchNotice] });
    if (viewport.width < 1024) await page.getByTestId('canvas-pill').click();
    const navigation = page.getByRole('complementary', { name: '旅行导航' });
    const adjust = navigation.getByRole('button', { name: '调整', exact: true });
    const before = await adjust.boundingBox();
    await adjust.click();
    const back = navigation.getByRole('button', { name: '返回日程', exact: true });
    await expect(back).toBeVisible();
    const [readingBox, todayBox, backBox] = await Promise.all([
      navigation.getByRole('button', { name: '阅读版', exact: true }).boundingBox(),
      navigation.getByRole('button', { name: '旅中查看', exact: true }).boundingBox(),
      back.boundingBox(),
    ]);
    expect(before && backBox && todayBox && readingBox).toBeTruthy();
    expect(Math.abs(backBox!.x - before!.x)).toBeLessThan(1);
    expect(Math.abs(backBox!.y - todayBox!.y)).toBeLessThan(2);
    expect(todayBox!.x).toBeGreaterThan(readingBox!.x);
    expect(backBox!.x).toBeGreaterThan(todayBox!.x);

    const conversation = page.getByRole('region', { name: '调整行程对话' });
    await expect(conversation.getByText(savedNotice, { exact: true })).toHaveCount(0);
    await expect(conversation.getByTestId('thinking-chain')).toBeVisible();
    await expect(conversation.getByTestId('copy-message')).toHaveCount(0);
    const input = conversation.getByTestId('brief-input');
    await expect(input).toBeVisible();
    const [inputBox, conversationBox] = await Promise.all([input.boundingBox(), conversation.boundingBox()]);
    expect(conversationBox!.y + conversationBox!.height - (inputBox!.y + inputBox!.height)).toBeLessThan(35);
    await back.click();
    await expect(adjust).toBeFocused();
    expect(errors).toEqual([]);
  });
}

test('long adjustment history scrolls independently of the composer', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const messages = Array.from({ length: 18 }, (_, index) => ({
    id: `answer-${index}`, role: 'assistant' as const,
    content: `对话记录 ${index}：${'慢慢游览并预留休息时间。'.repeat(8)}`,
    display_content: `对话记录 ${index}：${'慢慢游览并预留休息时间。'.repeat(8)}`,
    timestamp: '2026-10-25T08:00:00Z',
  }));
  const { errors } = await openDelivery(page, { days: 2, messages });
  await page.getByRole('button', { name: '调整', exact: true }).click();
  const conversation = page.getByRole('region', { name: '调整行程对话' });
  const input = conversation.getByTestId('brief-input');
  const scroll = conversation.locator('.overflow-y-auto').first();
  await expect(scroll).toHaveJSProperty('scrollTop', await scroll.evaluate((element) => element.scrollHeight - element.clientHeight));
  const before = await input.boundingBox();
  await scroll.evaluate((element) => { element.scrollTop = 0; });
  await expect(conversation.getByText(/^对话记录 0：/)).toBeVisible();
  const after = await input.boundingBox();
  expect(Math.abs(after!.y - before!.y)).toBeLessThan(1);
  await expect(input).toBeVisible();
  expect(errors).toEqual([]);
});

test('city navigation reaches day fourteen and restores the directory position', async ({ page }) => {
  const { errors } = await openDelivery(page, { longTitle: true });
  await expect(page.getByTestId('itinerary-route-nav')).toBeVisible();
  await page.getByTestId('day-summary-card-day-14').click();
  await expect(page.getByTestId('itinerary-route-nav').getByRole('button', { name: '全程', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByRole('button', { name: '第 14 天', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByTestId('day-overview-back').click();
  await expect(page.getByTestId('day-summary-card-day-14')).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('keeps unresolved items across day and reading views without replacing the map', async ({ page }) => {
  const { errors } = await openDelivery(page, { days: 2 });
  const map = page.getByTestId('bundle-leaflet-map');
  await map.evaluate((element) => { element.dataset.retainedMap = 'yes'; });
  await page.getByTestId('day-summary-card-day-2').click();
  await expect(page.getByTestId('itinerary-card-flow').getByText('第 2 天下午尚未安排具体活动。', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '阅读版', exact: true }).click();
  await expect(page.getByTestId('full-report').getByText('第 2 天下午尚未安排具体活动。', { exact: true })).toHaveCount(1);
  await page.getByRole('button', { name: '返回地图', exact: true }).click();
  await expect(map).toHaveAttribute('data-retained-map', 'yes');
  expect(errors).toEqual([]);
});

test('shows useful sources and omits empty search placeholders', async ({ page }) => {
  const entityRef = { entity_type: 'visit_stop' as const, entity_id: 'visit-terracotta' };
  const { errors } = await openDelivery(page, { days: 2, mutate: (bundle) => {
    Object.assign(bundle.source_index.content, { citations: [
      {
        citation_id: 'generic', entity_ref: entityRef, field_paths: ['name'], fact_status: 'verified',
        supported_values: [{ label: 'name', value: '秦始皇帝陵博物院', unit: null, currency: null }],
        sources: [{ source_record_id: 'generic-search', source_kind: 'external_tool', title: '地点搜索结果', public_excerpt: '找到 1 个结果', canonical_url: null, retrieved_at: '2026-10-25T08:00:00Z', observed_at: null }],
      },
      {
        citation_id: 'official', entity_ref: entityRef, field_paths: ['opening_window'], fact_status: 'verified',
        supported_values: [{ label: 'opening_window', value: '08:30–17:00', unit: null, currency: null }],
        sources: [{ source_record_id: 'museum-site', source_kind: 'external_web', title: '博物院官网', public_excerpt: '参观时间和预约办法', canonical_url: 'https://example.org/visit', retrieved_at: '2026-10-25T08:00:00Z', observed_at: null }],
      },
    ] });
  } });
  await page.getByTestId('day-summary-card-day-1').click();
  const occurrence = page.locator('[data-itinerary-occurrence="d1-terracotta"]');
  await occurrence.getByText('资料来源', { exact: true }).click();
  await expect(occurrence.getByRole('link', { name: '博物院官网' })).toHaveAttribute('href', 'https://example.org/visit');
  await expect(occurrence).not.toContainText('地点搜索结果');
  await expect(page.getByTestId('map-place-detail')).toHaveCount(0);
  await page.getByRole('button', { name: '阅读版', exact: true }).click();
  const references = page.locator('#report-references');
  await expect(references.getByRole('link', { name: '博物院官网' })).toBeVisible();
  await expect(references).not.toContainText('地点搜索结果');
  expect(errors).toEqual([]);
});

test('mobile sheet keeps the map reachable and provides direct day selection', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { errors } = await openDelivery(page);
  const opener = page.getByTestId('canvas-pill');
  await opener.click();
  const sheet = page.getByTestId('canvas-sheet');
  await expect(sheet).toHaveAttribute('data-detent', '55');
  await sheet.getByTestId('day-summary-card-day-1').click();
  await sheet.getByRole('combobox', { name: '选择行程日期' }).selectOption('14');
  await expect(sheet.getByRole('combobox', { name: '选择行程日期' })).toHaveValue('14');
  await sheet.getByTestId('sheet-handle').click();
  await expect(sheet).toHaveAttribute('data-detent', '92');
  await page.keyboard.press('Escape');
  await expect(sheet).toHaveCount(0);
  await expect(opener).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('reading layer returns to the retained map when closed during entry', async ({ page }) => {
  const { errors } = await openDelivery(page, { days: 2 });
  const map = page.getByTestId('bundle-leaflet-map');
  await map.evaluate(element => { element.dataset.retainedMap = 'retained'; });
  await page.getByTestId('day-summary-card-day-1').click();
  await page.locator('[data-itinerary-occurrence="d1-terracotta"]').getByRole('button', { name: /^在地图查看/ }).click();
  const opener = page.getByRole('button', { name: '阅读版', exact: true });
  await opener.click();
  const reading = page.locator('.journey-reading-layer');
  await page.keyboard.press('Escape');
  await expect(reading).toHaveCount(0);
  await expect(map).toHaveAttribute('data-retained-map', 'retained');
  await expect(page.getByTestId('map-place-detail')).toBeVisible();
  await expect(opener).toBeFocused();
  expect(errors).toEqual([]);
});

test('mobile history identifies read-only results before opening the sheet', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { errors } = await openDelivery(page, { readonly: true, days: 1 });
  await expect(page.getByText('历史结果 · 只读', { exact: true })).toBeVisible();
  await page.getByTestId('canvas-pill').click();
  await expect(page.getByRole('button', { name: '调整', exact: true })).toHaveCount(0);
  await expect(page.getByText('历史结果 · 只读', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test('tile failures retain markers and PDF failures remain visible', async ({ page }) => {
  const { errors } = await openDelivery(page, { tilesFail: true, days: 2 });
  await expect(page.getByTestId('bundle-map-basemap-state')).toBeVisible();
  await expect(page.getByTestId('bundle-leaflet-map')).toHaveAttribute('data-basemap-state', 'degraded');
  expect(await page.locator('[data-bundle-map-entity], [data-bundle-map-group]').count()).toBeGreaterThan(0);
  await page.getByRole('button', { name: '阅读版', exact: true }).click();
  await page.getByTestId('download-current-pdf').click();
  await expect(page.getByRole('alert')).toBeVisible();
  expect(errors).toEqual([]);
});

test('links cards and clustered markers and restores focus after selection', async ({ page }) => {
  const { errors } = await openDelivery(page, { days: 2 });
  await page.getByTestId('day-summary-card-day-1').click();
  const occurrence = page.locator('[data-itinerary-occurrence="d1-terracotta"]');
  await occurrence.hover();
  await expect(page.locator('[data-bundle-map-entity][data-linked="on"], [data-bundle-map-group][data-linked="on"]').first()).toBeVisible();
  const trigger = occurrence.getByRole('button', { name: /^在地图查看/ });
  await expect(trigger).toHaveText('秦始皇帝陵博物院（兵马俑）');
  await expect(occurrence.getByText('秦始皇帝陵博物院（兵马俑）', { exact: true })).toHaveCount(1);
  await expect(occurrence).toContainText('陕西省西安市临潼区秦陵北路');
  await expect(occurrence).toContainText('08:30–17:00');
  await expect(occurrence.getByText('景点', { exact: true })).toHaveCount(0);
  await trigger.click();
  await expect(page.getByTestId('map-place-detail')).toContainText('秦始皇帝陵博物院');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('map-place-detail')).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await trigger.press('Enter');
  await expect(page.getByTestId('map-place-detail')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  await occurrence.locator('.journey-card-readouts').click();
  await expect(page.getByTestId('map-place-detail')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  expect(errors).toEqual([]);
});
