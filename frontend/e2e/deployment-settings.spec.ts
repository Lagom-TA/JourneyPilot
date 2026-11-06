import { expect, test } from '@playwright/test';
import { sessionDetail, sessionSummary } from './fixtures/sessionData';

// 使用独立 Vite 服务验证子路径、自定义瓦片和非安全 HTTP 上下文。
const deploymentURL = process.env.JP_DEPLOYMENT_URL || '';
test.skip(!deploymentURL, 'Explicit deployment test server required');

test('subpath, custom tiles and LAN HTTP browser behavior', async ({ page }) => {
  const errors: string[] = [];
  const tileRequests: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/custom-tile/')) {
      tileRequests.push(url.pathname);
      return route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e9e8df"/></svg>' });
    }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.slice(4);
    let body: unknown = {};
    if (path === '/user/sessions') body = [sessionSummary('A')];
    else if (path === '/user/sessions/A') body = sessionDetail('A');
    else if (path === '/trip-runs') body = { runs: [], total: 0 };
    else if (path === '/user/default-origin') body = { place: null };
    else if (path === '/presets' || path === '/user/preference-options') body = [];
    else if (path === '/user/profile') body = { preferences: {} };
    else if (path === '/user/memory/facts') body = { facts: [] };
    else if (path === '/knowledge/collections/travel_knowledge/stats') body = { total: 0, sources: 0, source_details: [] };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  await page.goto(`${deploymentURL}/journeypilot/e2e/fixtures/map-load-failure.html`);
  const map = page.getByTestId('bundle-leaflet-map');
  await expect(map).toHaveAttribute('data-basemap-state', 'ready');
  await expect.poll(() => tileRequests.length).toBeGreaterThan(0);
  await expect(map).toContainText('Offline Tile');
  // 全程总览先进入单日对页，地图才展示当日实体。
  await page.getByTestId('day-summary-card-day-1').click();
  await expect(page.locator('[data-bundle-map-entity]')).toHaveCount(4);

  const platform = await page.evaluate(async () => {
    const modulePath = '/journeypilot/src/lib/platform.ts';
    const helpers = await import(/* @vite-ignore */ modulePath);
    return { secure: window.isSecureContext, randomUUID: typeof crypto.randomUUID, ids: [helpers.randomId(), helpers.randomId()], copied: await helpers.copyText('offline') };
  });
  expect(platform.secure).toBe(false);
  expect(platform.randomUUID).toBe('undefined');
  expect(platform.ids[0]).toBeTruthy();
  expect(platform.ids[0]).not.toBe(platform.ids[1]);
  expect(platform.copied).toBe(false);

  await page.addInitScript(() => localStorage.setItem('journeypilot.last-session-id', 'A'));
  await page.goto(`${deploymentURL}/journeypilot/`);
  await expect(page.getByText('A 的历史回答', { exact: true })).toBeVisible();
  const copy = page.getByTestId('copy-message');
  const feedback = copy.locator('[aria-live="polite"]');
  const previousFeedback = await feedback.textContent();
  await copy.click();
  await expect(feedback).not.toHaveText(previousFeedback ?? '');
  const trips = page.getByRole('link', { name: '我的行程', exact: true });
  await expect(trips).toHaveAttribute('href', '/journeypilot/?view=trips');
  await trips.click();
  await expect(page).toHaveURL(/\/journeypilot\/\?view=trips/);
  expect(errors).toEqual([]);
});
