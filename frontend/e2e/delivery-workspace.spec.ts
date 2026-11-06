import { test, expect, type Page } from '@playwright/test';
import { xianLayoutBundle } from './fixtures/xianBundle';
import { sessionDetail, sessionSummary } from './fixtures/sessionData';

async function openDelivery(page: Page, options: { days?: number; readonly?: boolean; tilesFail?: boolean; longTitle?: boolean } = {}) {
  const errors: string[] = [];
  const bundle = xianLayoutBundle({ dayCount: options.days ?? 14, longTitle: options.longTitle });
  bundle.workspace.itinerary.unresolved = ['第 2 天下午尚未安排具体活动。'];
  bundle.report_projection.document.unresolved = [...bundle.workspace.itinerary.unresolved];
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
    else if (path === '/user/sessions/A') body = sessionDetail('A');
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
  await expect(page.getByTestId('bundle-leaflet-map')).toBeVisible().catch(async (error) => {
    console.log({ errors, text: (await page.locator('body').innerText()).slice(0, 1800) });
    throw error;
  });
  return { errors, bundle };
}

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

test('mobile sheet keeps the map reachable and provides direct day selection', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { errors } = await openDelivery(page);
  const opener = page.getByTestId('canvas-pill');
  await opener.click();
  const sheet = page.getByTestId('canvas-sheet');
  await expect(sheet).toHaveAttribute('data-detent', '55');
  await expect(page.getByTestId('sheet-scrim')).toHaveCount(0);
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
  await page.locator('[data-itinerary-occurrence="d1-terracotta"]').getByRole('button', { name: '在地图查看', exact: true }).click();
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
  await expect(page.getByTestId('bundle-map-basemap-state')).toContainText('底图暂时没加载出来');
  expect(await page.locator('[data-bundle-map-entity], [data-bundle-map-group]').count()).toBeGreaterThan(0);
  await page.getByRole('button', { name: '阅读版', exact: true }).click();
  await page.getByTestId('download-current-pdf').click();
  await expect(page.getByRole('alert')).toContainText('PDF 暂时无法生成');
  expect(errors).toEqual([]);
});

test('links cards and clustered markers and restores focus after selection', async ({ page }) => {
  const { errors } = await openDelivery(page, { days: 2 });
  await page.getByTestId('day-summary-card-day-1').click();
  const occurrence = page.locator('[data-itinerary-occurrence="d1-terracotta"]');
  await occurrence.hover();
  await expect(page.locator('[data-bundle-map-entity][data-linked="on"], [data-bundle-map-group][data-linked="on"]').first()).toBeVisible();
  const trigger = occurrence.getByRole('button', { name: '在地图查看', exact: true });
  await trigger.click();
  await expect(page.getByTestId('map-place-detail')).toContainText('秦始皇帝陵博物院');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('map-place-detail')).toHaveCount(0);
  await expect(trigger).toBeFocused();
  expect(errors).toEqual([]);
});
