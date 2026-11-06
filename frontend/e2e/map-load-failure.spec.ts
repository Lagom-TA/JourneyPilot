import { expect, test, type Page } from '@playwright/test';

// 在独立 Vite dev server 下运行：
//   JP_MAP_LOAD_FAILURE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:5174 \
//     npx playwright test e2e/map-load-failure.spec.ts
// 页面只加载本地合成 Bundle；/api 与地图瓦片全部在浏览器内拦截，不读写真实行程。
test.skip(process.env.JP_MAP_LOAD_FAILURE_E2E !== '1', 'Explicit offline map-load opt-in required');
const baseURL = process.env.JOURNEYPILOT_APP_URL || '';
if (process.env.JP_MAP_LOAD_FAILURE_E2E === '1' && !/^http:\/\/127\.0\.0\.1:\d+$/.test(baseURL)) {
  throw new Error('Offline suite requires an explicit loopback Vite URL');
}

const TILE_PATTERN = /^https:\/\/webrd0[1-4]\.is\.autonavi\.com\/appmaptile/;
// Vite 的依赖缓存目录可自定义，包含 /@fs/ 路径时仍需拦截地图依赖。
const DEP_PATTERN = /\/deps\/(?:react-leaflet|leaflet)\.js$/;

type DepFailure = { failing: boolean; remaining: number };

type OfflineFixture = {
  pageErrors: string[];
  apiRequests: string[];
  escapes: string[];
  depResponses: Array<{ url: string; status: number }>;
  depFailure: DepFailure;
};

async function mountFixture(
  page: Page,
  options: { depFailure?: Partial<DepFailure> } = {},
): Promise<OfflineFixture> {
  const fixture: OfflineFixture = {
    pageErrors: [],
    apiRequests: [],
    escapes: [],
    depResponses: [],
    depFailure: { failing: false, remaining: 0, ...options.depFailure },
  };
  page.on('pageerror', (error) => fixture.pageErrors.push(error.message));
  page.on('response', (response) => {
    const url = new URL(response.url());
    if (url.origin === baseURL && DEP_PATTERN.test(url.pathname)) {
      fixture.depResponses.push({ url: url.pathname, status: response.status() });
    }
  });
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== baseURL) {
      if (TILE_PATTERN.test(url.href)) {
        await route.fulfill({
          status: 200,
          contentType: 'image/svg+xml',
          body: '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e9e8df"/></svg>',
        });
        return;
      }
      fixture.escapes.push(url.href);
      await route.abort('blockedbyclient');
      return;
    }
    if (url.pathname.startsWith('/api/')) {
      fixture.apiRequests.push(`${request.method()} ${url.pathname}`);
      await route.fulfill({ status: 501, contentType: 'application/json', body: '{"detail":"unmocked offline API"}' });
      return;
    }
    if (DEP_PATTERN.test(url.pathname) && (fixture.depFailure.failing || fixture.depFailure.remaining > 0)) {
      if (!fixture.depFailure.failing) fixture.depFailure.remaining -= 1;
      await route.fulfill({ status: 504, contentType: 'text/plain', headers: { 'cache-control': 'no-store' }, body: '' });
      return;
    }
    await route.continue();
  });
  await page.goto('/e2e/fixtures/map-load-failure.html');
  await expect(page.getByTestId('interactive-itinerary')).toBeVisible();
  return fixture;
}

function assertOfflineBoundaries(fixture: OfflineFixture, options: { allowModuleLoadErrors?: boolean } = {}) {
  const unexpectedPageErrors = options.allowModuleLoadErrors
    ? fixture.pageErrors.filter((message) => !/Failed to fetch dynamically imported module/.test(message))
    : fixture.pageErrors;
  expect(unexpectedPageErrors).toEqual([]);
  expect(fixture.escapes).toEqual([]);
  expect(fixture.apiRequests).toEqual([]);
}

test('地图离线夹具：已交付行程的地图与日程联动', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await mountFixture(page);
  const map = page.getByTestId('bundle-leaflet-map');
  await expect(map).toBeVisible();
  await expect(map).toHaveAttribute('data-basemap-state', 'ready', { timeout: 10_000 });
  // 全程总览先进入单日对页，日期按钮才出现。
  await page.getByTestId('day-summary-card-day-1').click();
  await expect(page.locator('[data-bundle-map-entity]')).toHaveCount(4);
  await expect(page.locator('.leaflet-overlay-pane path[data-route-entity]')).toHaveCount(3);

  await page.getByRole('button', { name: '第 2 天', exact: true }).click();
  await expect(page.locator('[data-bundle-map-entity]')).toHaveCount(4);
  await page.getByRole('button', { name: '图层', exact: true }).click();
  await page.getByRole('checkbox', { name: '餐饮', exact: true }).uncheck();
  await expect(page.locator('[data-bundle-map-entity]')).toHaveCount(3);
  await page.keyboard.press('Escape');

  await page.locator('[data-bundle-map-entity="visit-shaanxi-museum"]').click();
  await expect(page.getByTestId('map-place-detail')).toContainText('陕西历史博物馆');
  await page.getByRole('button', { name: '关闭地点详情', exact: true }).click();
  await expect(page.getByTestId('map-place-detail')).toHaveCount(0);
  await expect(page.getByTestId('bundle-map-basemap-state')).toHaveCount(0);

  assertOfflineBoundaries(fixture);
});

test('地图离线夹具：加载失败时准确提示、保留日程并通过重新加载恢复', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 900 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await mountFixture(page, { depFailure: { failing: true } });
  await expect.poll(
    () => fixture.depResponses.filter(({ status }) => status === 504).length,
    { message: '地图依赖请求应被拦截并返回 504', timeout: 15_000 },
  ).toBeGreaterThan(0);
  const failure = page.getByTestId('lazy-view-failure');
  await expect(failure).toBeVisible({ timeout: 15_000 });
  await expect(failure).not.toContainText('网络中断');
  await expect(page.getByTestId('interactive-itinerary')).toBeVisible();
  await expect(page.locator('.journey-title-row h1')).toHaveText('西安两日 · 秦唐风物');

  // 地图失败不影响左侧日程：进入单日、切日与图层入口仍工作。
  await page.getByTestId('day-summary-card-day-1').click();
  await page.getByRole('button', { name: '第 2 天', exact: true }).click();
  const currentItinerary = page.locator('.journey-content-scene:not([aria-hidden="true"])').getByTestId('interactive-itinerary');
  await expect(currentItinerary).toContainText('陕西历史博物馆');
  await expect(page.locator('.journey-content-scene')).toHaveCount(1);
  await page.getByRole('button', { name: '图层', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '旅行路线', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  const depResponsesBeforeReload = [...fixture.depResponses];
  const failedDepPaths = new Set(depResponsesBeforeReload.filter(({ status }) => status === 504).map(({ url }) => url));

  // 故障解除后，重新加载页面必须真正恢复地图，而不是只验证按钮可点。
  fixture.depFailure.failing = false;
  const map = page.getByTestId('bundle-leaflet-map');
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
    failure.getByRole('button', { name: '重新加载页面', exact: true }).click(),
  ]);
  await expect(map).toBeVisible({ timeout: 10_000 });
  await expect(map).toHaveAttribute('data-basemap-state', 'ready', { timeout: 10_000 });
  await expect(page.getByTestId('lazy-view-failure')).toHaveCount(0);
  await expect.poll(
    () => fixture.depResponses.slice(depResponsesBeforeReload.length)
      .some(({ url, status }) => status === 200 && failedDepPaths.has(url)),
    { message: '故障解除后同一地图依赖应重新加载成功' },
  ).toBe(true);

  assertOfflineBoundaries(fixture, { allowModuleLoadErrors: true });
});
