import { expect, test, type Locator, type Page } from '@playwright/test';

const plannerConfiguration = {
  primary_styles: [
    { id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] },
    { id: 'slow', label: '轻松慢游', is_default: false, inference_keywords: ['轻松'] },
    { id: 'food', label: '当地美食', is_default: false, inference_keywords: ['美食'] },
    { id: 'culture', label: '人文体验', is_default: false, inference_keywords: ['人文'] },
    { id: 'outdoors', label: '户外自然', is_default: false, inference_keywords: ['户外'] },
    { id: 'family', label: '亲子友好', is_default: false, inference_keywords: ['亲子'] },
  ],
  secondary_interests: [
    { id: 'photography', label: '摄影', is_default: false, inference_keywords: [] },
  ],
  default_adults: 2,
  default_children: 0,
  default_elderly_companions: false,
  default_accessibility_required: false,
  max_secondary_interests: 3,
  inspiration_rotation_ms: 5000,
  inspiration_prompts: ['秋天想带爸妈去一个不太累、吃得好的地方，大约 6 天'],
};

async function openHome(page: Page, viewport = { width: 1440, height: 900 }, configurationUnavailable = false) {
  let configurationAvailable = !configurationUnavailable;
  const pageErrors: string[] = [];
  const unmocked: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.setViewportSize(viewport);
  await page.addInitScript(() => {
    localStorage.setItem('journeypilot.last-session-id', 'home-e2e');
  });
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.slice(4);
    const json = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
    if (path === '/user/sessions') {
      return json([{
        session_id: 'home-e2e',
        title: '首页示例',
        status: 'active',
        mode: 'deep',
        last_message_preview: '',
        created_at: '2026-10-27T08:00:00Z',
        updated_at: '2026-10-27T08:00:00Z',
      }]);
    }
    if (path === '/user/sessions/home-e2e') {
      return json({
        session_id: 'home-e2e',
        title: '首页示例',
        status: 'active',
        mode: 'deep',
        last_message_preview: '',
        created_at: '2026-10-27T08:00:00Z',
        updated_at: '2026-10-27T08:00:00Z',
        messages: [],
        next_before: null,
        has_more: false,
      });
    }
    if (path === '/trip-runs') return json({ runs: [], total: 0 });
    if (path === '/product/trip-planner') {
      if (!configurationAvailable) return json({ detail: 'Service temporarily unavailable' }, 503);
      return json(plannerConfiguration);
    }
    if (path === '/user/default-origin') return json({ place: null });
    if (path === '/places/search') {
      const query = (url.searchParams.get('q') || '').trim();
      const name = query.replace(/[市\s]/g, '') || '候选城市';
      return json({ candidates: [{ place: { place_id: `osm:relation:${encodeURIComponent(name)}`, provider: 'osm', kind: 'city', name, display_name: `${name}，中国`, country_code: 'CN', latitude: 31.2, longitude: 121.4, admin_path: ['中国', name] }, confidence: 1, requires_confirmation: true }] });
    }
    if (path === '/presets') return json([]);
    if (path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: [] });
    if (path === '/knowledge/collections/travel_knowledge/stats') return json({ total: 0, sources: 0, source_details: [] });
    unmocked.push(`${route.request().method()} ${path}`);
    return json({ detail: 'Unmocked API request' }, 501);
  });
  await page.goto('/');
  await expect(page.getByTestId('natural-trip-input')).toBeVisible();
  await expect(page.getByTestId('travel-atlas')).toHaveAttribute('data-scene', 'northwest');
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(500);
  return { pageErrors, unmocked, recoverConfiguration: () => { configurationAvailable = true; } };
}

function expectCleanFixture(fixture: { pageErrors: string[]; unmocked: string[] }) {
  expect(fixture.pageErrors).toEqual([]);
  expect(fixture.unmocked).toEqual([]);
}

test('同一视图内后退后，切换视图仍同步地址栏', async ({ page }) => {
  await openHome(page);
  await page.evaluate(() => {
    window.history.pushState(null, '', '?view=chat&position=first');
    window.history.pushState(null, '', '?view=chat&position=second');
  });
  await page.goBack();
  await expect(page).toHaveURL(/position=first/);
  await page.getByRole('link', { name: '偏好与资料', exact: true }).first().click();
  await expect(page).toHaveURL(/view=user-preferences/);
});

test('素材延迟或失败时整组保留，快速选择只采用最后一次主题', async ({ page }) => {
  const fixture = await openHome(page);
  let releaseImage: () => void = () => {};
  const waiting = new Promise<void>((resolve) => { releaseImage = resolve; });
  await page.route('**/*jiangnan.webp*', async (route) => {
    if (route.request().resourceType() === 'image') await waiting;
    await route.continue();
  });
  await page.getByTestId('atlas-tab-jiangnan').click();
  await expect(page.getByTestId('travel-atlas')).toHaveAttribute('aria-busy', 'true');
  await expect(page.getByTestId('travel-atlas')).toHaveAttribute('data-scene', 'northwest');
  await expect(page.locator('.home-landscape')).toHaveAttribute('data-theme', 'northwest');
  await page.getByTestId('atlas-tab-island').click();
  await expect(page.getByTestId('travel-atlas')).toHaveAttribute('data-scene', 'island');
  releaseImage();
  await page.waitForTimeout(100);
  await expect(page.getByTestId('atlas-use-alternate')).toHaveAttribute('data-theme', 'island');
  await page.route('**/*northwest.webp*', (route) => route.request().resourceType() === 'image' ? route.abort() : route.continue());
  await page.getByTestId('atlas-tab-northwest').click();
  await expect(page.getByTestId('travel-atlas')).not.toHaveAttribute('aria-busy', 'true');
  await expect(page.getByTestId('travel-atlas')).toHaveAttribute('data-scene', 'island');
  await expect(page.locator('.home-landscape')).toHaveAttribute('data-theme', 'island');
  expectCleanFixture(fixture);
});

test('常见桌面窗口完整展示精简的条件规划表单', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await openHome(page);
  const hero = page.getByTestId('new-trip-hero');
  const planner = page.getByRole('region', { name: '旅行规划卡' });
  const attribution = hero.getByRole('link', { name: '© OpenStreetMap contributors' });
  await page.getByTestId('planner-structured-tab').click();
  await expect(page.getByRole('textbox', { name: '出发地', exact: true })).toBeVisible();
  await expect(planner.getByText('地点数据', { exact: false })).toHaveCount(0);
  await expect(attribution).toBeVisible();
  await expect(attribution).toHaveAttribute('href', 'https://www.openstreetmap.org/copyright');

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1366, height: 768 },
    { width: 1366, height: 700 },
    { width: 1280, height: 720 },
  ]) {
    await page.setViewportSize(viewport);
    await expect.poll(() => hero.evaluate((element) => Math.max(element.scrollHeight - element.clientHeight, element.querySelector('.home-place-attribution')!.getBoundingClientRect().bottom - element.getBoundingClientRect().bottom)), JSON.stringify(viewport)).toBeLessThanOrEqual(1);
    const bounds = await hero.evaluate((element) => {
      const viewport = element.getBoundingClientRect();
      const card = element.querySelector('.planner-card')!.getBoundingClientRect();
      const action = element.querySelector('.planner-main-action')!.getBoundingClientRect();
      const credit = element.querySelector('.home-place-attribution')!.getBoundingClientRect();
      return { viewport: { top: viewport.top, bottom: viewport.bottom }, card: { top: card.top, right: card.right, bottom: card.bottom }, action: { top: action.top, bottom: action.bottom }, credit: { top: credit.top, left: credit.left, bottom: credit.bottom } };
    });
    expect(bounds.card.top, JSON.stringify(viewport)).toBeGreaterThanOrEqual(bounds.viewport.top);
    expect(bounds.card.bottom, JSON.stringify(viewport)).toBeLessThanOrEqual(bounds.viewport.bottom);
    expect(bounds.action.bottom, JSON.stringify(viewport)).toBeLessThanOrEqual(bounds.viewport.bottom);
    expect(bounds.credit.top >= bounds.card.bottom || bounds.credit.left >= bounds.card.right, JSON.stringify(viewport)).toBe(true);
    expect(bounds.credit.bottom, JSON.stringify(viewport)).toBeLessThanOrEqual(bounds.viewport.bottom);
  }

  const fields = await page.locator('.planner-condition-fields').evaluate((element) => {
    const [date, traveler, budget, style] = Array.from(element.children).map((child) => child.getBoundingClientRect());
    return { date: date.top, traveler: traveler.top, budget: budget.top, style: style.top };
  });
  expect(Math.abs(fields.date - fields.traveler)).toBeLessThan(1);
  expect(Math.abs(fields.budget - fields.style)).toBeLessThan(1);
  expect(fields.budget).toBeGreaterThan(fields.date);

  await page.getByRole('button', { name: '更多偏好' }).click();
  await expect(page.getByRole('button', { name: '长辈同行' })).toBeVisible();
  await expect.poll(() => hero.evaluate((element) => element.scrollHeight - element.clientHeight)).toBeGreaterThan(1);
  await page.getByRole('button', { name: '长辈同行' }).scrollIntoViewIfNeeded();
  await page.getByRole('button', { name: '长辈同行' }).click();
  await expect(page.getByRole('button', { name: '长辈同行' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: '更多偏好' }).click();
  for (const [trigger, dialog] of [['date-range-trigger', 'date-range-dialog'], ['traveler-picker-trigger', 'traveler-picker-dialog']]) {
    await page.getByTestId(trigger).click();
    await expect(page.getByTestId(dialog)).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByTestId(dialog)).toBeHidden();
  }
  expectCleanFixture(fixture);
});

test('配置失败不阻塞一句话输入，条件规划可以重试并保留草稿', async ({ page }) => {
  const fixture = await openHome(page, { width: 1440, height: 900 }, true);
  const input = page.getByTestId('natural-trip-input');
  await input.fill('带爸妈去杭州，步行少一点。');
  await page.getByTestId('planner-structured-tab').click();
  await expect(page.getByTestId('request-failure-notice')).toBeVisible();
  await page.getByTestId('planner-natural-tab').click();
  await expect(input).toHaveValue('带爸妈去杭州，步行少一点。');
  fixture.recoverConfiguration();
  await page.getByTestId('planner-structured-tab').click();
  await page.getByTestId('request-failure-action').click();
  await expect(page.getByRole('textbox', { name: '出发地' })).toBeVisible();
  await expect(page.getByTestId('request-failure-notice')).toHaveCount(0);
  await page.getByTestId('planner-natural-tab').click();
  await expect(input).toHaveValue('带爸妈去杭州，步行少一点。');
  expectCleanFixture(fixture);
});

test('手动选择整组主题，键盘导航同步选中态和焦点', async ({ page }) => {
  const fixture = await openHome(page);
  const tabs = page.locator('.atlas-scene-tabs > button');
  const panelIds = await tabs.evaluateAll((elements) => elements.map((element) => element.getAttribute('aria-controls')));
  expect(new Set(panelIds).size).toBe(1);
  await expect(page.locator('.atlas-examples')).toHaveAttribute('id', panelIds[0]!);
  const northwest = page.getByTestId('atlas-tab-northwest');
  await northwest.focus();
  await northwest.press('ArrowRight');
  const island = page.getByTestId('atlas-tab-island');
  await expect(island).toHaveAttribute('aria-selected', 'true');
  await expect(island).toBeFocused();
  await island.press('Home');
  const southwest = page.getByTestId('atlas-tab-southwest');
  await expect(southwest).toHaveAttribute('aria-selected', 'true');
  await expect(southwest).toBeFocused();
  await southwest.press('End');
  await expect(island).toBeFocused();
  expectCleanFixture(fixture);
});

test('首页轮播进度在真实时间递增，悬停暂停并从原处继续', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  const fixture = await openHome(page);
  const atlas = page.getByTestId('travel-atlas');
  const progress = page.getByTestId('atlas-progress');
  await expect(atlas).toHaveAttribute('data-autoplay', 'running');
  await expect.poll(() => progress.evaluate((element) => element.getAnimations().length)).toBe(1);
  const timing = await progress.evaluate((element) => {
    const effect = element.getAnimations()[0]!.effect!;
    return { duration: effect.getTiming().duration, easing: effect.getTiming().easing };
  });
  expect(timing).toEqual({ duration: 6500, easing: 'linear' });

  const sampleProgress = () => progress.evaluate((element) => ({
    value: new DOMMatrixReadOnly(getComputedStyle(element).transform).a,
    time: performance.now(),
  }));
  const first = await sampleProgress();
  await page.waitForTimeout(450);
  const second = await sampleProgress();
  await page.waitForTimeout(450);
  const third = await sampleProgress();
  expect(first.value).toBeGreaterThanOrEqual(0);
  expect(second.value).toBeGreaterThan(first.value + 0.025);
  expect(third.value).toBeGreaterThan(second.value + 0.025);
  expect(Math.abs((third.value - first.value) - (third.time - first.time) / 6500)).toBeLessThan(0.04);

  await atlas.hover();
  await expect(atlas).toHaveAttribute('data-autoplay', 'paused');
  await page.waitForTimeout(100);
  const paused = await sampleProgress();
  await page.waitForTimeout(650);
  const stillPaused = await sampleProgress();
  expect(paused.value).toBeGreaterThanOrEqual(third.value - 0.005);
  expect(Math.abs(stillPaused.value - paused.value)).toBeLessThan(0.005);

  await page.mouse.move(0, 0);
  await expect(atlas).toHaveAttribute('data-autoplay', 'running');
  const resumed = await sampleProgress();
  expect(resumed.value).toBeGreaterThanOrEqual(stillPaused.value - 0.005);
  expect(resumed.value).toBeLessThan(stillPaused.value + 0.05);
  await page.waitForTimeout(450);
  const continued = await sampleProgress();
  expect(continued.value).toBeGreaterThan(resumed.value + 0.025);
  await expect(atlas).toHaveAttribute('data-scene', 'northwest');
  expectCleanFixture(fixture);
});

test('首页轮播自动向前切换并首尾循环', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.clock.install();
  const fixture = await openHome(page);
  const atlas = page.getByTestId('travel-atlas');
  await expect(atlas).toHaveAttribute('data-autoplay', 'running');

  for (const scene of ['island', 'southwest', 'jiangnan', 'northwest']) {
    await page.clock.fastForward(6500);
    await expect(atlas).toHaveAttribute('data-scene', scene);
    await expect(atlas).toHaveAttribute('data-direction', 'forward');
    await expect(atlas).toHaveAttribute('data-autoplay', 'running');
    await expect(page.getByTestId(`atlas-tab-${scene}`)).toHaveAttribute('aria-selected', 'true');
    await page.waitForTimeout(100);
  }
  expectCleanFixture(fixture);
});

test('首页轮播自动目标解码快速失败后重新计时并重试', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.addInitScript(() => {
    const originalDecode = HTMLImageElement.prototype.decode;
    const state = { fail: true, failures: 0, attempts: 0 };
    Object.assign(window, { atlasDecodeFixture: state });
    HTMLImageElement.prototype.decode = function () {
      if (/\/island(?:-[^/]*)?\.webp$/.test(new URL(this.src).pathname)) {
        state.attempts += 1;
        if (state.fail) {
          state.failures += 1;
          return Promise.reject(new DOMException('Image decode failed', 'EncodingError'));
        }
      }
      return originalDecode.call(this);
    };
  });
  await page.clock.install();
  const fixture = await openHome(page);
  const atlas = page.getByTestId('travel-atlas');
  const state = () => page.evaluate(() => (window as any).atlasDecodeFixture as { fail: boolean; failures: number; attempts: number });

  await page.clock.fastForward(1300);
  await expect.poll(async () => (await state()).failures).toBeGreaterThanOrEqual(1);
  await page.clock.fastForward(6500);
  await expect.poll(async () => (await state()).failures).toBeGreaterThanOrEqual(2);
  await expect(atlas).toHaveAttribute('data-scene', 'northwest');
  await expect(atlas).toHaveAttribute('data-autoplay', 'running');
  const progress = page.getByTestId('atlas-progress');
  await expect.poll(() => progress.evaluate((element) => element.getAnimations().length)).toBe(1);
  const sampleProgress = () => progress.evaluate((element) => new DOMMatrixReadOnly(getComputedStyle(element).transform).a);
  const restarted = await sampleProgress();
  expect(restarted).toBeLessThan(0.15);
  await page.waitForTimeout(500);
  expect(await sampleProgress()).toBeGreaterThan(restarted + 0.03);

  await page.evaluate(() => { (window as any).atlasDecodeFixture.fail = false; });
  await page.clock.fastForward(6500);
  await expect(atlas).toHaveAttribute('data-scene', 'island');
  await expect(atlas).toHaveAttribute('data-direction', 'forward');
  expect((await state()).attempts).toBeGreaterThanOrEqual(3);
  expectCleanFixture(fixture);
});

test('首页轮播点击按标签位置切换，左右键按方向首尾循环', async ({ page }) => {
  const fixture = await openHome(page);
  const atlas = page.getByTestId('travel-atlas');
  const southwest = page.getByTestId('atlas-tab-southwest');
  const island = page.getByTestId('atlas-tab-island');
  await expect(page.locator('.atlas-scene-tabs > button')).toHaveText(['巴蜀', '江南', '西北', '海岛']);
  await expect(page.getByRole('button', { name: '暂停自动轮播' })).toHaveCount(0);
  const expectScene = async (scene: string, direction: string) => {
    await expect(atlas).toHaveAttribute('data-scene', scene);
    await expect(atlas).toHaveAttribute('data-direction', direction);
    await expect(page.getByTestId(`atlas-tab-${scene}`)).toHaveAttribute('aria-selected', 'true');
  };

  await southwest.click();
  await expectScene('southwest', 'backward');
  await island.click();
  await expectScene('island', 'forward');
  await southwest.click();
  await expectScene('southwest', 'backward');
  await island.click();
  await expectScene('island', 'forward');

  await island.press('ArrowRight');
  await expectScene('southwest', 'forward');
  await expect(southwest).toBeFocused();
  await southwest.press('ArrowLeft');
  await expectScene('island', 'backward');
  await expect(island).toBeFocused();
  expectCleanFixture(fixture);
});

test('首页轮播快速回切时最新背景位于顶层并渐入', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  const fixture = await openHome(page);
  const atlas = page.getByTestId('travel-atlas');
  const landscape = page.locator('.home-landscape');
  const northwest = page.getByTestId('atlas-tab-northwest');
  const island = page.getByTestId('atlas-tab-island');

  await island.click();
  await expect(atlas).toHaveAttribute('data-scene', 'island');
  await northwest.click();
  await expect(atlas).toHaveAttribute('data-scene', 'northwest');
  await expect(landscape.locator('.atlas-scene')).toHaveCount(1);

  const islandBox = (await island.boundingBox())!;
  const northwestBox = (await northwest.boundingBox())!;
  const started = Date.now();
  await page.mouse.click(islandBox.x + islandBox.width / 2, islandBox.y + islandBox.height / 2);
  await expect(atlas).toHaveAttribute('data-scene', 'island');
  await page.mouse.click(northwestBox.x + northwestBox.width / 2, northwestBox.y + northwestBox.height / 2);
  await expect(atlas).toHaveAttribute('data-scene', 'northwest');
  expect(Date.now() - started).toBeLessThan(300);

  const snapshot = await landscape.locator('.atlas-scene').evaluateAll((layers) => layers.map((layer) => ({
    source: (layer.querySelector('img') as HTMLImageElement).src,
    opacity: Number(getComputedStyle(layer).opacity),
  })));
  expect(snapshot.length).toBeGreaterThanOrEqual(2);
  expect(snapshot[snapshot.length - 2]!.source).toMatch(/\/island[-.]/);
  expect(snapshot[snapshot.length - 1]!.source).toMatch(/\/northwest[-.]/);
  expect(snapshot[snapshot.length - 1]!.opacity).toBeLessThan(1);
  await page.waitForTimeout(100);
  const laterOpacity = await landscape.locator('.atlas-scene').last().evaluate((layer) => Number(getComputedStyle(layer).opacity));
  expect(laterOpacity).toBeGreaterThan(snapshot[snapshot.length - 1]!.opacity);
  await expect(landscape.locator('.atlas-scene')).toHaveCount(1);
  expectCleanFixture(fixture);
});

test('首页轮播在运行时切换减少动态效果后暂停和恢复', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.clock.install();
  const fixture = await openHome(page);
  const atlas = page.getByTestId('travel-atlas');
  const progress = page.getByTestId('atlas-progress');
  const sampleProgress = () => progress.evaluate((element) => new DOMMatrixReadOnly(getComputedStyle(element).transform).a);
  await expect(atlas).toHaveAttribute('data-autoplay', 'paused');
  await page.clock.fastForward(20000);
  await page.waitForTimeout(100);
  await expect(atlas).toHaveAttribute('data-scene', 'northwest');
  await expect(atlas).toHaveAttribute('data-autoplay', 'paused');
  await expect(page.getByTestId('atlas-tab-northwest')).toHaveAttribute('aria-selected', 'true');
  await expect(progress).toHaveCSS('transform', 'matrix(0, 0, 0, 1, 0, 0)');

  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await expect(atlas).toHaveAttribute('data-autoplay', 'running');
  const started = await sampleProgress();
  await page.waitForTimeout(450);
  expect(await sampleProgress()).toBeGreaterThan(started + 0.025);

  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(atlas).toHaveAttribute('data-autoplay', 'paused');
  const paused = await sampleProgress();
  expect(paused).toBeGreaterThan(started + 0.025);
  await page.clock.fastForward(14000);
  await page.waitForTimeout(250);
  await expect(atlas).toHaveAttribute('data-scene', 'northwest');
  expect(Math.abs(await sampleProgress() - paused)).toBeLessThan(0.005);

  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await expect(atlas).toHaveAttribute('data-autoplay', 'running');
  const resumed = await sampleProgress();
  expect(resumed).toBeGreaterThanOrEqual(paused - 0.005);
  expect(resumed).toBeLessThan(paused + 0.05);
  await page.waitForTimeout(450);
  expect(await sampleProgress()).toBeGreaterThan(resumed + 0.025);
  expectCleanFixture(fixture);
});

for (const { label, viewport, paper } of [
  { label: '桌面', viewport: { width: 1440, height: 900 }, paper: 'tag-luggage' },
  { label: '390px', viewport: { width: 390, height: 844 }, paper: 'tag-luggage-wide' },
]) {
  test(`首页轮播${label}纸品、图片和背景主题同步`, async ({ page }) => {
    const fixture = await openHome(page, viewport);
    const atlas = page.getByTestId('travel-atlas');
    const landscape = page.locator('.home-landscape');
    const primary = page.getByTestId('atlas-use-example');
    const alternate = page.getByTestId('atlas-use-alternate');
    const scenes = [
      { id: 'northwest', destination: '敦煌', moment: '石窟' },
      { id: 'southwest', destination: '成都', moment: '茶馆' },
      { id: 'jiangnan', destination: '苏州', moment: '水巷' },
      { id: 'island', destination: '海口', moment: '早市' },
    ];

    for (const { id, destination, moment } of scenes) {
      if (id !== 'northwest') await page.getByTestId(`atlas-tab-${id}`).click();
      await expect(atlas).toHaveAttribute('data-scene', id);
      await expect(page.getByTestId(`atlas-tab-${id}`)).toHaveAttribute('aria-selected', 'true');
      await expect(landscape).toHaveAttribute('data-theme', id);
      await expect(primary).toHaveAttribute('data-theme', id);
      await expect(alternate).toHaveAttribute('data-theme', id);
      await expect(primary).toContainText(destination);
      await expect(alternate).toContainText(moment);
      await expect(landscape.locator('.atlas-scene').last().locator('.atlas-artwork'))
        .toHaveAttribute('src', new RegExp(`/${id}[-.]`));
      await expect(alternate.locator('.atlas-place-print'))
        .toHaveAttribute('src', new RegExp(`/print-${id}[-.]`));
      await expect.poll(() => alternate.locator('.atlas-paper').evaluate((element: HTMLImageElement) => element.currentSrc))
        .toMatch(new RegExp(`/${paper}[-.]`));
    }
    expectCleanFixture(fixture);
  });
}

async function plannerFocusStyles(planner: Locator) {
  return planner.evaluate((element) => {
    const card = getComputedStyle(element);
    const border = getComputedStyle(element, '::before');
    const inputWrapper = element.querySelector('.planner-natural-input')!;
    const input = inputWrapper.querySelector('textarea')!;
    const cardRect = element.getBoundingClientRect();
    const inputRect = inputWrapper.getBoundingClientRect();
    return {
      focusWithin: element.matches(':focus-within'),
      boxShadow: card.boxShadow,
      outlineStyle: card.outlineStyle,
      outlineWidth: card.outlineWidth,
      outlineColor: card.outlineColor,
      inputOutlineStyle: getComputedStyle(inputWrapper).outlineStyle,
      textareaOutlineStyle: getComputedStyle(input).outlineStyle,
      borderOpacity: Number(border.opacity),
      borderDisplay: border.display,
      borderBackground: border.backgroundImage,
      borderAnimation: border.animationName,
      borderPointerEvents: border.pointerEvents,
      borderBounds: {
        top: cardRect.top + parseFloat(border.top),
        right: cardRect.left + parseFloat(border.left) + parseFloat(border.width),
        bottom: cardRect.top + parseFloat(border.top) + parseFloat(border.height),
        left: cardRect.left + parseFloat(border.left),
      },
      cardBounds: { top: cardRect.top, right: cardRect.right, bottom: cardRect.bottom, left: cardRect.left },
      inputBounds: { top: inputRect.top, right: inputRect.right, bottom: inputRect.bottom, left: inputRect.left },
    };
  });
}

for (const { label, viewport } of [
  { label: '桌面', viewport: { width: 1440, height: 900 } },
  { label: '390px', viewport: { width: 390, height: 844 } },
]) {
  test(`规划卡焦点外框 ${label} 点击和键盘进入、移焦与切换模式`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference', forcedColors: 'none' });
    const fixture = await openHome(page, viewport);
    const planner = page.locator('.new-trip-content .planner-card');
    const input = page.getByRole('textbox', { name: '一句话描述旅行', exact: true });
    const natural = page.getByRole('tab', { name: '一句话规划', exact: true });
    const structured = page.getByRole('tab', { name: '按条件规划', exact: true });
    const naturalPanel = page.locator('.planner-panel-natural');
    const structuredPanel = page.locator('.planner-panel-structured');
    const text = '想去杭州，步行少一点。';

    await expect(planner).toHaveAccessibleName('旅行规划卡');
    await expect(input).toHaveAttribute('maxlength', '500');
    await expect(natural).toHaveAttribute('aria-selected', 'true');
    await expect(structured).toHaveAttribute('aria-selected', 'false');
    await expect(naturalPanel).toBeVisible();
    await expect(structuredPanel).toBeHidden();
    expect(await natural.getAttribute('aria-controls')).toBe(await naturalPanel.getAttribute('id'));
    expect(await naturalPanel.getAttribute('aria-labelledby')).toBe(await natural.getAttribute('id'));
    expect(await structured.getAttribute('aria-controls')).toBe(await structuredPanel.getAttribute('id'));
    expect(await structuredPanel.getAttribute('aria-labelledby')).toBe(await structured.getAttribute('id'));

    const initial = await plannerFocusStyles(planner);
    expect(initial.focusWithin).toBe(false);
    expect(initial.borderOpacity).toBe(0);
    expect(initial.borderBackground).toContain('gradient');
    expect(initial.borderPointerEvents).toBe('none');
    expect(initial.inputOutlineStyle).toBe('none');
    for (const edge of ['top', 'right', 'bottom', 'left'] as const) {
      expect(Math.abs(initial.borderBounds[edge] - initial.cardBounds[edge])).toBeLessThanOrEqual(4);
    }
    expect(initial.borderBounds.left).toBeLessThan(initial.inputBounds.left);
    expect(initial.borderBounds.right).toBeGreaterThan(initial.inputBounds.right);
    expect(initial.borderBounds.top).toBeLessThan(initial.inputBounds.top);
    expect(initial.borderBounds.bottom).toBeGreaterThan(initial.inputBounds.bottom);
    await input.hover();
    await page.waitForTimeout(300);
    const hovered = await plannerFocusStyles(planner);
    expect(hovered.focusWithin).toBe(false);
    expect(hovered.borderOpacity).toBe(0);
    expect(hovered.boxShadow).toBe(initial.boxShadow);

    await input.click();
    await expect(input).toBeFocused();
    await expect.poll(async () => (await plannerFocusStyles(planner)).focusWithin).toBe(true);
    await expect.poll(async () => (await plannerFocusStyles(planner)).borderOpacity).toBeGreaterThanOrEqual(0.7);
    await expect.poll(async () => (await plannerFocusStyles(planner)).boxShadow).not.toBe(initial.boxShadow);
    const focused = await plannerFocusStyles(planner);
    expect(focused.borderOpacity).toBeLessThanOrEqual(1);
    expect(focused.inputOutlineStyle).toBe('none');
    expect(focused.textareaOutlineStyle).toBe('none');
    await input.fill(text);
    await expect(input).toHaveValue(text);

    // 同一卡片内的焦点转移不应结束整体焦点态。
    await page.keyboard.press('Tab');
    await expect(input).not.toBeFocused();
    expect(await plannerFocusStyles(planner)).toMatchObject({ focusWithin: true, inputOutlineStyle: 'none' });

    // 点击卡片外的静态标题，等 CSS 过渡结束后再检查恢复值。
    await page.locator('.new-trip-copy h1').click();
    await expect.poll(async () => (await plannerFocusStyles(planner)).focusWithin).toBe(false);
    await expect.poll(async () => (await plannerFocusStyles(planner)).borderOpacity).toBe(0);
    await expect.poll(async () => (await plannerFocusStyles(planner)).boxShadow).toBe(initial.boxShadow);
    await expect(input).toHaveValue(text);

    // 当前选中的 tab 是 tablist 中唯一的制表位，下一次 Tab 进入输入框。
    await natural.focus();
    await expect(natural).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(input).toBeFocused();
    expect(await plannerFocusStyles(planner)).toMatchObject({ focusWithin: true, inputOutlineStyle: 'none' });
    await expect.poll(async () => (await plannerFocusStyles(planner)).borderOpacity).toBeGreaterThanOrEqual(0.7);
    await expect.poll(async () => (await plannerFocusStyles(planner)).boxShadow).not.toBe(initial.boxShadow);

    await structured.click();
    await expect(structured).toHaveAttribute('aria-selected', 'true');
    await expect(natural).toHaveAttribute('aria-selected', 'false');
    await expect(naturalPanel).toBeHidden();
    await expect(structuredPanel).toBeVisible();
    await expect(page.getByRole('textbox', { name: '出发地', exact: true })).toBeVisible();
    expect((await plannerFocusStyles(planner)).focusWithin).toBe(true);
    await natural.click();
    await expect(natural).toHaveAttribute('aria-selected', 'true');
    await expect(naturalPanel).toBeVisible();
    await expect(structuredPanel).toBeHidden();
    await expect(input).toHaveValue(text);
    expectCleanFixture(fixture);
  });

  test(`规划卡焦点外框 ${label} 减少动态效果保持静态外框`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce', forcedColors: 'none' });
    const fixture = await openHome(page, viewport);
    const planner = page.locator('.new-trip-content .planner-card');
    const input = page.getByTestId('natural-trip-input');
    const initial = await plannerFocusStyles(planner);
    expect(initial.focusWithin).toBe(false);
    expect(initial.borderOpacity).toBe(0);

    await input.click();
    await expect(input).toBeFocused();
    await expect.poll(async () => (await plannerFocusStyles(planner)).borderOpacity).toBe(1);
    await expect.poll(async () => (await plannerFocusStyles(planner)).boxShadow).not.toBe(initial.boxShadow);
    const focused = await plannerFocusStyles(planner);
    expect(focused).toMatchObject({ focusWithin: true, inputOutlineStyle: 'none', textareaOutlineStyle: 'none', borderAnimation: 'none' });
    expect(focused.borderBackground).toContain('gradient');
    await page.waitForTimeout(500);
    expect((await plannerFocusStyles(planner)).borderOpacity).toBe(1);

    await page.locator('.new-trip-copy h1').click();
    await expect.poll(async () => (await plannerFocusStyles(planner)).focusWithin).toBe(false);
    await expect.poll(async () => (await plannerFocusStyles(planner)).borderOpacity).toBe(0);
    await expect.poll(async () => (await plannerFocusStyles(planner)).boxShadow).toBe(initial.boxShadow);
    expectCleanFixture(fixture);
  });

  test(`规划卡焦点外框 ${label} 强制颜色使用系统高亮`, async ({ page }) => {
    await page.emulateMedia({ forcedColors: 'active' });
    const fixture = await openHome(page, viewport);
    const planner = page.locator('.new-trip-content .planner-card');
    const input = page.getByTestId('natural-trip-input');
    const initial = await plannerFocusStyles(planner);
    expect(initial.focusWithin).toBe(false);
    expect(initial.outlineStyle).toBe('none');
    expect(initial.borderDisplay).toBe('none');

    await input.click();
    await expect(input).toBeFocused();
    await expect.poll(async () => (await plannerFocusStyles(planner)).focusWithin).toBe(true);
    const focused = await plannerFocusStyles(planner);
    const highlight = await planner.evaluate((element) => {
      const probe = document.createElement('span');
      probe.style.color = 'Highlight';
      element.appendChild(probe);
      const color = getComputedStyle(probe).color;
      probe.remove();
      return color;
    });
    expect(focused).toMatchObject({
      outlineStyle: 'solid', outlineWidth: '2px', outlineColor: highlight,
      inputOutlineStyle: 'none', textareaOutlineStyle: 'none', borderDisplay: 'none', boxShadow: 'none',
    });

    await page.locator('.new-trip-copy h1').click();
    await expect.poll(async () => (await plannerFocusStyles(planner)).focusWithin).toBe(false);
    await expect.poll(async () => (await plannerFocusStyles(planner)).outlineStyle).toBe('none');
    expect((await plannerFocusStyles(planner)).borderDisplay).toBe('none');
    expectCleanFixture(fixture);
  });
}

async function samplePlannerSwitch(page: Page, target: 'natural' | 'structured', reverseAtHeight?: number, probeCandidates = false) {
  return page.evaluate(async ({ target, reverseAtHeight, probeCandidates }) => {
    const hero = document.querySelector<HTMLElement>('.new-trip-hero')!;
    const card = hero.querySelector<HTMLElement>('.planner-card')!;
    const panels = card.querySelector<HTMLElement>('.planner-panels')!;
    const heading = hero.querySelector<HTMLElement>('.new-trip-copy h1')!;
    const action = card.querySelector<HTMLElement>('.planner-main-action')!;
    const naturalPanel = card.querySelector<HTMLElement>('.planner-panel-natural')!;
    const structuredPanel = card.querySelector<HTMLElement>('.planner-panel-structured')!;
    const tab = (mode: 'natural' | 'structured') => card.querySelector<HTMLButtonElement>(`[data-testid="planner-${mode}-tab"]`)!;
    const hidden = (panel: HTMLElement) => panel.hidden && getComputedStyle(panel).display === 'none';
    const snapshot = () => ({
      mode: card.dataset.mode,
      panelsHeight: panels.getBoundingClientRect().height,
      cardHeight: card.getBoundingClientRect().height,
      cardTop: card.getBoundingClientRect().top,
      headingTop: heading.getBoundingClientRect().top,
      actionTop: action.getBoundingClientRect().top,
      scrollTop: hero.scrollTop,
      maxScroll: Math.max(0, hero.scrollHeight - hero.clientHeight),
      naturalHidden: hidden(naturalPanel),
      structuredHidden: hidden(structuredPanel),
      heightAnimating: panels.getAnimations().some((animation) => (
        animation.playState === 'running'
        && 'transitionProperty' in animation
        && animation.transitionProperty === 'height'
      )),
    });
    const frames = [snapshot()];
    const initialMode = frames[0]!.mode as 'natural' | 'structured';
    let lastMode: string | undefined = initialMode;
    const focusFailures: string[] = [];
    let reversed = false;
    let reverseIndex = -1;
    let settledFrames = 0;
    let candidateChecked = false;
    let candidateReachable = false;
    let candidateTriggered = false;
    tab(target).focus({ preventScroll: true });
    tab(target).click();

    const started = performance.now();
    while (performance.now() - started < 3000) {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      const frame = snapshot();
      frames.push(frame);
      if (frame.mode && frame.mode !== lastMode) {
        lastMode = frame.mode;
        const inactive = frame.mode === 'natural' ? structuredPanel : naturalPanel;
        const input = inactive.querySelector<HTMLElement>('textarea, input, select, button');
        input?.focus({ preventScroll: true });
        if (document.activeElement === input) focusFailures.push(frame.mode);
        tab(frame.mode as 'natural' | 'structured').focus({ preventScroll: true });
      }
      if (probeCandidates && frame.mode === 'structured' && (frame.heightAnimating || candidateTriggered) && !candidateChecked) {
        if (!candidateTriggered) {
          const input = structuredPanel.querySelector<HTMLInputElement>('.destination-search input')!;
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, '苏州');
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.focus({ preventScroll: true });
          candidateTriggered = true;
        }
        const candidate = document.querySelector<HTMLElement>('[data-testid="destination-candidates"] button');
        if (candidate) {
          const rect = candidate.getBoundingClientRect();
          const x = rect.left + rect.width / 2;
          const y = rect.top + rect.height / 2;
          const hit = document.elementFromPoint(x, y);
          candidateChecked = true;
          candidateReachable = rect.width > 0 && rect.height > 0 && y < innerHeight && Boolean(hit && candidate.contains(hit));
          tab('structured').focus({ preventScroll: true });
        }
      }
      if (reverseAtHeight !== undefined && !reversed && frame.mode === target) {
        const progress = (frame.panelsHeight - frames[0]!.panelsHeight) / (reverseAtHeight - frames[0]!.panelsHeight);
        if (progress > 0.08 && progress < 0.92) {
          tab(initialMode).click();
          reversed = true;
          reverseIndex = frames.length - 1;
          settledFrames = 0;
          continue;
        }
      }
      const finalMode = reversed ? initialMode : target;
      if (frame.mode === finalMode && !frame.heightAnimating) settledFrames += 1;
      else settledFrames = 0;
      if (settledFrames >= 2 && (!probeCandidates || candidateChecked)) break;
    }
    return { frames, reversed, reverseIndex, focusFailures, candidateChecked, candidateReachable, settled: settledFrames >= 2 };
  }, { target, reverseAtHeight, probeCandidates });
}

test('规划模式高度逐帧连续，快速回切可逆且保留草稿', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  const fixture = await openHome(page, { width: 1440, height: 650 });
  const input = page.getByTestId('natural-trip-input');
  const draft = '想去杭州，保留这份旅行草稿。';
  await input.fill(draft);
  await expect(page.locator('.planner-panel-structured input[aria-label="出发地"]')).toHaveCount(1);
  const hero = page.locator('.new-trip-hero');
  const initialScroll = await hero.evaluate((element) => {
    element.scrollTop = Math.min(32, Math.floor((element.scrollHeight - element.clientHeight) / 2));
    return element.scrollTop;
  });
  expect(initialScroll).toBeGreaterThan(0);

  const assertFrames = (result: Awaited<ReturnType<typeof samplePlannerSwitch>>, transition: boolean) => {
    expect(result.settled).toBe(true);
    expect(result.focusFailures).toEqual([]);
    const first = result.frames[0]!;
    const last = result.frames[result.frames.length - 1]!;
    let expectedScroll = first.scrollTop;
    for (const frame of result.frames) {
      expect(frame.naturalHidden).toBe(frame.mode !== 'natural');
      expect(frame.structuredHidden).toBe(frame.mode !== 'structured');
      // 浏览器只能在滚动范围收缩时自然夹紧位置。
      expectedScroll = Math.min(expectedScroll, frame.maxScroll);
      expect(Math.abs(frame.scrollTop - expectedScroll)).toBeLessThanOrEqual(2);
      expect(Math.abs((frame.cardHeight - first.cardHeight) - (frame.panelsHeight - first.panelsHeight))).toBeLessThan(2);
      expect(Math.abs((frame.actionTop - frame.cardTop) - (first.actionTop - first.cardTop) - (frame.panelsHeight - first.panelsHeight))).toBeLessThan(2);
      expect(Math.abs((frame.cardTop - frame.headingTop) - (first.cardTop - first.headingTop))).toBeLessThan(2);
      if (frame !== first) {
        const previous = result.frames[result.frames.indexOf(frame) - 1]!;
        const heightChange = Math.abs(frame.panelsHeight - previous.panelsHeight);
        const scrollChange = Math.abs(frame.scrollTop - previous.scrollTop);
        for (const key of ['headingTop', 'cardTop'] as const) {
          expect(Math.abs(frame[key] - previous[key])).toBeLessThanOrEqual(heightChange + scrollChange + 3);
        }
        expect(Math.abs(frame.actionTop - previous.actionTop)).toBeLessThanOrEqual(2 * heightChange + scrollChange + 3);
      }
    }
    if (transition) {
      const delta = last.panelsHeight - first.panelsHeight;
      expect(Math.abs(delta)).toBeGreaterThan(60);
      expect(result.frames.some((frame) => {
        const progress = (frame.panelsHeight - first.panelsHeight) / delta;
        return progress > 0.08 && progress < 0.92;
      })).toBe(true);
      for (const key of ['headingTop', 'cardTop', 'actionTop'] as const) {
        const low = Math.min(first[key], last[key]) - 3;
        const high = Math.max(first[key], last[key]) + 3;
        for (const frame of result.frames) {
          expect(frame[key]).toBeGreaterThanOrEqual(low);
          expect(frame[key]).toBeLessThanOrEqual(high);
        }
      }
    }
  };

  const expanded = await samplePlannerSwitch(page, 'structured');
  assertFrames(expanded, true);
  await page.getByLabel('预算（可选）').fill('4567');
  const collapsed = await samplePlannerSwitch(page, 'natural');
  assertFrames(collapsed, true);
  await expect(input).toHaveValue(draft);

  const reversed = await samplePlannerSwitch(page, 'structured', expanded.frames[expanded.frames.length - 1]!.panelsHeight);
  assertFrames(reversed, false);
  expect(reversed.reversed).toBe(true);
  expect(reversed.frames[reversed.frames.length - 1]!.mode).toBe('natural');
  const reversedStart = reversed.frames[reversed.reverseIndex]!;
  const reversedEnd = reversed.frames[reversed.frames.length - 1]!;
  expect(Math.abs(reversedEnd.panelsHeight - reversed.frames[0]!.panelsHeight)).toBeLessThan(2);
  expect(reversedStart.panelsHeight).toBeGreaterThan(reversedEnd.panelsHeight + 3);
  expect(reversed.frames.slice(reversed.reverseIndex + 1).some((frame) => (
    frame.panelsHeight < reversedStart.panelsHeight - 1 && frame.panelsHeight > reversedEnd.panelsHeight + 1
  ))).toBe(true);
  await expect(input).toHaveValue(draft);
  const interaction = await samplePlannerSwitch(page, 'structured', undefined, true);
  expect(interaction.settled).toBe(true);
  expect(interaction.candidateChecked).toBe(true);
  expect(interaction.candidateReachable).toBe(true);
  await expect(page.getByLabel('预算（可选）')).toHaveValue('4567');

  for (const [triggerId, dialogId] of [
    ['date-range-trigger', 'date-range-dialog'],
    ['traveler-picker-trigger', 'traveler-picker-dialog'],
  ]) {
    await page.getByTestId(triggerId).click();
    const dialog = page.getByTestId(dialogId);
    await expect(dialog).toBeVisible();
    await expect.poll(() => dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
    await page.getByTestId('planner-structured-tab').focus();
    await page.keyboard.press('ArrowLeft');
    await expect(page.getByTestId('planner-natural-tab')).toBeFocused();
    await expect(page.locator('.planner-panel-structured')).toHaveAttribute('hidden', '');
    await expect(dialog).toBeHidden();
    await expect(page.getByTestId('planner-natural-tab')).toBeFocused();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByTestId('planner-structured-tab')).toBeFocused();
    await expect(page.getByTestId(triggerId)).toHaveAttribute('aria-expanded', 'false');
  }
  expectCleanFixture(fixture);
});

test('390px 键盘切换与减少动态效果不妨碍长内容滚动', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await openHome(page, { width: 390, height: 844 });
  const hero = page.locator('.new-trip-hero');
  const planner = page.getByRole('region', { name: '旅行规划卡' });
  const natural = page.getByTestId('planner-natural-tab');
  const structured = page.getByTestId('planner-structured-tab');
  const input = page.getByTestId('natural-trip-input');
  const draft = '想沿途慢慢旅行，体验当地生活。'.repeat(25);
  await input.fill(draft);
  await expect(page.locator('.planner-panel-structured input[aria-label="出发地"]')).toHaveCount(1);
  await natural.focus();

  await page.evaluate(() => {
    const card = document.querySelector<HTMLElement>('.new-trip-content .planner-card')!;
    const panels = card.querySelector<HTMLElement>('.planner-panels')!;
    const probe = { running: true, frames: [] as Array<{ mode: string | undefined; height: number; contentHeight: number; animating: boolean }> };
    Object.assign(window, { plannerReducedMotionProbe: probe });
    const sample = () => {
      if (!probe.running) return;
      probe.frames.push({
        mode: card.dataset.mode,
        height: panels.getBoundingClientRect().height,
        contentHeight: panels.firstElementChild!.getBoundingClientRect().height,
        animating: panels.getAnimations().some((animation) => animation.playState === 'running'),
      });
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
  const assertInstant = async (mode: 'natural' | 'structured', since: number) => {
    await page.waitForFunction(({ expected, since }) => (
      (window as any).plannerReducedMotionProbe.frames.slice(since).filter((frame: { mode: string }) => frame.mode === expected).length >= 3
    ), { expected: mode, since });
    const frames = await page.evaluate(({ expected, since }) => (
      (window as any).plannerReducedMotionProbe.frames.slice(since).filter((frame: { mode: string }) => frame.mode === expected).slice(0, 3)
    ), { expected: mode, since }) as Array<{ height: number; contentHeight: number; animating: boolean }>;
    for (const frame of frames) {
      expect(frame.animating).toBe(false);
      expect(Math.abs(frame.height - frame.contentHeight)).toBeLessThan(2);
      expect(Math.abs(frame.height - frames[0]!.height)).toBeLessThan(2);
    }
  };
  const assertNoHorizontalScroll = async () => {
    const widths = await hero.evaluate((element) => ({
      hero: element.scrollWidth - element.clientWidth,
      document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    }));
    expect(widths.hero).toBeLessThanOrEqual(1);
    expect(widths.document).toBeLessThanOrEqual(1);
  };
  const assertActionReachable = async () => {
    const action = page.getByRole('button', { name: '开始规划', exact: true });
    await action.scrollIntoViewIfNeeded();
    const position = await action.evaluate((element) => {
      const hero = element.closest<HTMLElement>('.new-trip-hero')!;
      const button = element.getBoundingClientRect();
      const viewport = hero.getBoundingClientRect();
      return { scrollTop: hero.scrollTop, buttonTop: button.top, buttonBottom: button.bottom, viewportTop: viewport.top, viewportBottom: viewport.bottom };
    });
    expect(position.scrollTop).toBeGreaterThan(0);
    expect(position.buttonTop).toBeGreaterThanOrEqual(position.viewportTop - 1);
    expect(position.buttonBottom).toBeLessThanOrEqual(position.viewportBottom + 1);
  };

  const beforeStructured = await page.evaluate(() => (window as any).plannerReducedMotionProbe.frames.length as number);
  await natural.press('ArrowRight');
  await expect(structured).toBeFocused();
  await expect(structured).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.planner-panel-natural')).toHaveAttribute('hidden', '');
  await expect(planner.getByText('地点数据', { exact: false })).toHaveCount(0);
  const attribution = hero.getByRole('link', { name: '© OpenStreetMap contributors' });
  await attribution.scrollIntoViewIfNeeded();
  await expect(attribution).toBeVisible();
  await assertInstant('structured', beforeStructured);
  await assertNoHorizontalScroll();
  await assertActionReachable();

  await structured.focus();
  const beforeNatural = await page.evaluate(() => (window as any).plannerReducedMotionProbe.frames.length as number);
  await structured.press('ArrowLeft');
  await expect(natural).toBeFocused();
  await expect(natural).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.planner-panel-structured')).toHaveAttribute('hidden', '');
  await expect(input).toHaveValue(draft);
  await assertInstant('natural', beforeNatural);
  await page.evaluate(() => { (window as any).plannerReducedMotionProbe.running = false; });
  await assertNoHorizontalScroll();
  expect(await input.evaluate((element) => element.scrollHeight - element.clientHeight)).toBeLessThanOrEqual(1);
  await assertActionReachable();
  expectCleanFixture(fixture);
});

test('两种规划各自保留草稿，灵感仅填入当前模式', async ({ page }) => {
  const fixture = await openHome(page);
  const input = page.getByTestId('natural-trip-input');
  const planner = page.locator('.planner-card');
  await input.fill('我想保留这句话，喜欢当地美食。');
  const naturalHeight = (await planner.boundingBox())!.height;
  await page.getByTestId('planner-structured-tab').click();
  await expect(page.locator('.planner-panel-natural')).toBeHidden();
  await page.getByRole('textbox', { name: '出发地' }).fill('深圳');
  await page.getByLabel('预算（可选）').fill('4567');
  await page.getByTestId('traveler-picker-trigger').click();
  await page.getByRole('button', { name: '3 位成人', exact: true }).click();
  await page.getByRole('button', { name: '完成', exact: true }).click();
  await page.getByRole('combobox', { name: '旅行风格', exact: true }).selectOption({ label: '人文体验' });
  await page.getByTestId('planner-natural-tab').click();
  await expect(input).toHaveValue('我想保留这句话，喜欢当地美食。');
  await expect(page.getByRole('button', { name: '更多偏好' })).toHaveCount(0);
  await expect(page.locator('.planner-panel-structured')).toBeHidden();
  await page.getByTestId('planner-structured-tab').click();
  await expect(page.getByLabel('预算（可选）')).toHaveValue('4567');
  await expect(page.getByRole('combobox', { name: '旅行风格', exact: true })).toHaveValue('人文体验');
  await expect.poll(async () => (await planner.boundingBox())!.height).toBeGreaterThan(naturalHeight + 60);
  await page.getByTestId('atlas-tab-island').click();
  await page.getByTestId('atlas-use-example').click();
  await expect(page.getByTestId('planner-structured-tab')).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('textbox', { name: '出发地' })).toHaveValue('广州');
  await expect(page.getByTestId('destination-token-0')).toContainText('海口');
  await expect(page.getByTestId('destination-token-1')).toContainText('三亚');
  await expect(page.getByLabel('预算（可选）')).toHaveValue('8000');
  await expect(page.getByTestId('date-range-trigger')).toBeFocused();
  await page.getByTestId('planner-natural-tab').click();
  await expect(input).toHaveValue('我想保留这句话，喜欢当地美食。');
  expectCleanFixture(fixture);
});

test('人数用选项和自填确认，取消不改变草稿，提交保留成人儿童', async ({ browser }) => {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport, deviceScaleFactor: 2 });
    const page = await context.newPage();
    const fixture = await openHome(page, viewport);
    await page.getByTestId('planner-structured-tab').click();
    await page.locator('.planner-card').scrollIntoViewIfNeeded();
    const trigger = page.getByTestId('traveler-picker-trigger');
    await trigger.click();
    const dialog = page.getByTestId('traveler-picker-dialog');
    await expect(page.getByRole('button', { name: '9 位成人', exact: true })).toBeVisible();
    await page.getByRole('button', { name: '6 位成人', exact: true }).click();
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toHaveAccessibleName('同行人数：2 位成人，0 位儿童');
    await expect(trigger).toBeFocused();
    await trigger.click();
    await page.getByRole('textbox', { name: '自填成人', exact: true }).fill('21');
    await expect(page.getByRole('button', { name: '完成', exact: true })).toBeDisabled();
    await page.getByRole('textbox', { name: '自填成人', exact: true }).fill('10');
    await page.getByRole('button', { name: '2 位儿童', exact: true }).click();
    await page.getByRole('button', { name: '完成', exact: true }).click();
    await expect(trigger).toHaveAccessibleName('同行人数：10 位成人，2 位儿童');
    await page.getByTestId('planner-natural-tab').click();
    await page.getByTestId('planner-structured-tab').click();
    await expect(trigger).toHaveAccessibleName('同行人数：10 位成人，2 位儿童');
    await page.getByRole('textbox', { name: '出发地', exact: true }).fill('北京');
    await page.getByLabel('预算（可选）').fill('12,000');
    let submitted: Record<string, any> | null = null;
    await page.route('**/api/chat-stream', async (route) => {
      submitted = route.request().postDataJSON();
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"fixture failure"}' });
    });
    await page.getByRole('button', { name: '开始规划', exact: true }).click();
    await expect.poll(() => submitted).not.toBeNull();
    expect(submitted!.controlled_trip_identity.party).toMatchObject({ adults: 10, children: 2, total: 12 });
    expect(submitted!.messages[0].content).toContain('总预算约 12,000 元');
    expectCleanFixture(fixture);
    await context.close();
  }
});

test('一句话提交只发送文字，等待和失败均保留用户需求', async ({ browser }) => {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    const fixture = await openHome(page, viewport);
    await page.getByTestId('planner-structured-tab').click();
    await page.getByRole('combobox', { name: '旅行风格', exact: true }).selectOption({ label: '人文体验' });
    await page.getByLabel('预算（可选）').fill('8000');
    await page.getByTestId('planner-natural-tab').click();
    const text = '想从北京去成都，7 天，带爸妈同行，多留休息时间，喜欢当地美食。';
    await page.getByTestId('natural-trip-input').fill(text);
    let requestBody: Record<string, any> | null = null;
    let release: () => void = () => {};
    const pending = new Promise<void>((resolve) => { release = resolve; });
    await page.route('**/api/chat-stream', async (route) => {
      requestBody = route.request().postDataJSON();
      await pending;
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'data: {"type":"error","message":"Service unavailable: internal-provider-debug"}\n\n' });
    });
    await page.getByRole('button', { name: '开始规划', exact: true }).click();
    await expect.poll(() => requestBody).not.toBeNull();
    expect(requestBody!.messages[0].content).toBe(text);
    expect(requestBody).not.toHaveProperty('controlled_trip_identity');
    await expect(page.getByTestId('new-trip-hero')).toHaveCount(0);
    await expect(page.getByText(text, { exact: true })).toBeVisible();
    release();
    await expect(page.getByRole('button', { name: '再试一次', exact: true })).toBeVisible();
    await expect(page.getByText(text, { exact: true })).toBeVisible();
    await expect(page.getByText('Service unavailable: internal-provider-debug', { exact: true })).toHaveCount(0);
    expectCleanFixture(fixture);
    await context.close();
  }
});

test('目的地可添加、删除并排序', async ({ page }) => {
  const fixture = await openHome(page);
  await page.getByRole('tab', { name: '按条件规划' }).click();

  const tokens = page.locator('.destination-token');
  const add = page.getByTestId('add-destination');
  const search = () => page.locator('.destination-search input');
  const candidates = page.getByTestId('destination-candidates');
  const addDestination = async (name: string) => {
    if (await search().count() === 0) await add.click();
    await search().fill(name);
    await candidates.getByRole('button').filter({ hasText: name }).first().click();
  };
  const dragToken = async (from: number, to: number) => {
    const handle = (await page.getByTestId(`destination-token-${from}`).boundingBox())!;
    const target = (await page.getByTestId(`destination-token-${to}`).boundingBox())!;
    await page.mouse.move(handle.x + 10, handle.y + handle.height / 2);
    await page.mouse.down();
    await page.mouse.move(target.x + target.width / 2, target.y + target.height / 2, { steps: 8 });
    await page.mouse.up();
  };

  await addDestination('苏州');
  await expect(tokens).toHaveCount(1);
  await addDestination('杭州');
  await expect(tokens).toHaveCount(2);

  await dragToken(1, 0);
  await expect(page.locator('.destination-token-name')).toHaveText(['杭州', '苏州']);
  await page.getByTestId('destination-token-1').focus();
  await page.getByTestId('destination-token-1').press('ArrowUp');
  await expect(page.locator('.destination-token-name')).toHaveText(['苏州', '杭州']);

  await page.getByTestId('destination-token-1').locator('.destination-token-remove').click();
  await expect(tokens).toHaveCount(1);
  await expect(page.getByTestId('destination-token-0')).toContainText('苏州');
  expectCleanFixture(fixture);
});

async function expectDestinationPlacement(page: Page, side: 'above' | 'below') {
  const candidates = page.getByTestId('destination-candidates');
  const input = page.locator('.destination-search');
  await expect(candidates).toBeVisible();
  await expect.poll(async () => {
    const field = (await input.boundingBox())!;
    const panel = (await candidates.boundingBox())!;
    return side === 'below' ? panel.y - field.y - field.height : field.y - panel.y - panel.height;
  }).toBeGreaterThanOrEqual(5);
  await expect.poll(async () => {
    const field = (await input.boundingBox())!;
    const panel = (await candidates.boundingBox())!;
    return side === 'below' ? panel.y - field.y - field.height : field.y - panel.y - panel.height;
  }).toBeLessThanOrEqual(7);
  const panel = (await candidates.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(panel.y).toBeGreaterThanOrEqual(11);
  expect(panel.y + panel.height).toBeLessThanOrEqual(viewport.height - 11);
  expect(panel.x).toBeGreaterThanOrEqual(11);
  expect(panel.x + panel.width).toBeLessThanOrEqual(viewport.width - 11);
}

test('目的地单条候选贴近新增输入框并随窗口变化翻转', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await openHome(page, { width: 1440, height: 900 });
  await page.getByTestId('planner-structured-tab').click();
  await page.getByRole('textbox', { name: '目的地，搜索城市或区域' }).fill('苏州');
  await page.getByTestId('destination-candidates').getByRole('button', { name: /^苏州(?:\s|$)/ }).click();
  await page.getByTestId('add-destination').click();
  const input = page.getByRole('textbox', { name: '新增目的地，搜索城市或区域' });
  await input.fill('杭州');
  const candidates = page.getByTestId('destination-candidates');
  await expect(candidates.getByRole('button')).toHaveCount(1);
  await expectDestinationPlacement(page, 'below');

  await page.setViewportSize({ width: 1440, height: 600 });
  await expectDestinationPlacement(page, 'above');
  await page.setViewportSize({ width: 1440, height: 900 });
  await expectDestinationPlacement(page, 'below');
  await candidates.getByRole('button', { name: /^杭州(?:\s|$)/ }).first().click();
  await expect(page.getByTestId('destination-token-1')).toContainText('杭州');
  expectCleanFixture(fixture);
});

test('目的地候选随结果和滚动变化贴边并限制高度', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await openHome(page, { width: 1440, height: 900 });
  let releaseRemote: () => void = () => {};
  const delay = new Promise<void>((resolve) => { releaseRemote = resolve; });
  await page.route('**/api/places/search**', async (route) => {
    if (new URL(route.request().url()).searchParams.get('q') !== '杭州') return route.fallback();
    await delay;
    return route.fulfill({
      status: 200,
      json: { candidates: Array.from({ length: 10 }, (_, index) => ({
        place: { place_id: `mock:杭州-${index}`, provider: 'osm', kind: 'administrative_area', name: `杭州区域${index}`, display_name: `杭州区域${index}，中国`, country_code: 'CN', latitude: 30.2 + index / 100, longitude: 120.1, admin_path: ['中国', '浙江'] },
        confidence: 1,
        requires_confirmation: true,
      })) },
    });
  });
  await page.getByTestId('planner-structured-tab').click();
  await page.getByRole('textbox', { name: '目的地，搜索城市或区域' }).fill('苏州');
  await page.getByTestId('destination-candidates').getByRole('button', { name: /^苏州(?:\s|$)/ }).click();
  await page.getByTestId('add-destination').click();
  await page.getByRole('textbox', { name: '新增目的地，搜索城市或区域' }).fill('杭州');
  const candidates = page.getByTestId('destination-candidates');
  await expect(candidates.getByRole('button')).toHaveCount(1);
  await expectDestinationPlacement(page, 'below');
  releaseRemote();
  await expect(candidates.getByRole('button')).toHaveCount(11);
  await page.setViewportSize({ width: 1440, height: 700 });
  await expectDestinationPlacement(page, 'above');
  expect(await candidates.evaluate((element) => element.scrollHeight - element.clientHeight)).toBeGreaterThan(0);

  await page.setViewportSize({ width: 1440, height: 400 });
  await page.getByRole('textbox', { name: '新增目的地，搜索城市或区域' }).scrollIntoViewIfNeeded();
  await expectDestinationPlacement(page, 'above');
  expect((await candidates.boundingBox())!.height).toBeLessThan(280);
  const hero = page.getByTestId('new-trip-hero');
  await hero.evaluate((element) => { element.scrollTop = 0; });
  await expect.poll(() => candidates.evaluate((element) => getComputedStyle(element).visibility)).toBe('hidden');
  await page.getByRole('textbox', { name: '新增目的地，搜索城市或区域' }).scrollIntoViewIfNeeded();
  await expectDestinationPlacement(page, 'above');
  await candidates.getByRole('button', { name: /^杭州区域9(?:\s|$)/ }).click();
  await expect(page.getByTestId('destination-token-1')).toContainText('杭州区域9');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole('textbox', { name: '新增目的地，搜索城市或区域' }).fill('杭州');
  await expect(candidates.getByRole('button')).toHaveCount(10);
  await expectDestinationPlacement(page, 'below');
  expect((await candidates.boundingBox())!.height).toBe(280);
  expectCleanFixture(fixture);
});

test('移动端目的地候选保持贴边并可选择', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await openHome(page, { width: 390, height: 844 });
  await page.getByTestId('planner-structured-tab').click();
  await page.getByRole('textbox', { name: '目的地，搜索城市或区域' }).fill('苏州');
  await page.getByTestId('destination-candidates').getByRole('button', { name: /^苏州(?:\s|$)/ }).click();
  await page.getByTestId('add-destination').click();
  const input = page.getByRole('textbox', { name: '新增目的地，搜索城市或区域' });
  await input.fill('杭州');
  await input.scrollIntoViewIfNeeded();
  await expectDestinationPlacement(page, 'below');
  await page.getByTestId('destination-candidates').getByRole('button', { name: /^杭州(?:\s|$)/ }).click();
  await expect(page.getByTestId('destination-token-1')).toContainText('杭州');
  expectCleanFixture(fixture);
});

test('本地候选立即显示，自动搜索合并远程结果并复用缓存', async ({ page }) => {
  await page.clock.install();
  const fixture = await openHome(page);
  await page.getByRole('tab', { name: '按条件规划' }).click();
  const origin = page.getByRole('textbox', { name: '出发地', exact: true });
  const destination = page.getByRole('textbox', { name: '目的地，搜索城市或区域', exact: true });
  const candidates = page.getByTestId('destination-candidates');
  const localCandidate = candidates.getByRole('button', { name: /^苏州(?:\s|$)/ });
  const remoteCandidate = candidates.getByRole('button', { name: /^苏州新区(?:\s|$)/ });
  await expect(origin).toHaveAttribute('placeholder', '选择城市');
  await expect(destination).toHaveAttribute('placeholder', '搜索城市或区域');
  await expect(page.getByRole('button', { name: '搜索出发地', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '搜索目的地', exact: true })).toHaveCount(0);

  await page.evaluate(() => {
    const original = window.fetch.bind(window);
    const queries: Array<{ query: string | null; role: string | null }> = [];
    Object.assign(window, { placeSearchProbe: queries });
    window.fetch = (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname.endsWith('/places/search')) {
        queries.push({ query: url.searchParams.get('q'), role: url.searchParams.get('role') });
      }
      return original(input, init);
    };
  });
  const requests = () => page.evaluate(() => (window as any).placeSearchProbe as Array<{ query: string | null; role: string | null }>);
  let releaseRemote: () => void = () => {};
  const remoteGate = new Promise<void>((resolve) => { releaseRemote = resolve; });
  await page.route('**/api/places/search**', async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get('q') !== '苏州' || url.searchParams.get('role') !== 'destination') return route.fallback();
    await remoteGate;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ candidates: [{
        place: { place_id: 'mock:suzhou-extra', provider: 'osm', kind: 'administrative_area', name: '苏州新区', display_name: '苏州新区，测试候选', country_code: 'CN', latitude: 31.3, longitude: 120.6, admin_path: ['中国', '江苏'] },
        confidence: 1,
        requires_confirmation: true,
      }] }),
    });
  });

  // 暂停时钟并延迟远程响应，确认本地候选不依赖防抖或网络。
  await page.clock.pauseAt(await page.evaluate(() => Date.now() + 100));
  await destination.fill('苏州甲');
  await destination.fill('苏州');
  await expect(localCandidate).toBeVisible();
  expect(await requests()).toEqual([]);
  await page.clock.runFor(100);
  expect(await requests()).toEqual([]);
  await page.clock.runFor(900);
  await expect.poll(requests).toEqual([{ query: '苏州', role: 'destination' }]);
  await expect(localCandidate).toBeVisible();
  await expect(remoteCandidate).toHaveCount(0);
  releaseRemote();
  await expect(remoteCandidate).toBeVisible();
  await expect(localCandidate).toBeVisible();

  await destination.fill('杭州');
  await destination.fill('苏州');
  await expect(remoteCandidate).toBeVisible();
  await page.clock.runFor(1000);
  expect(await requests()).toEqual([{ query: '苏州', role: 'destination' }]);

  await origin.fill('上海');
  await expect(page.getByRole('button', { name: /^上海(?:\s|$)/ }).first()).toBeVisible();
  expect(await requests()).toEqual([{ query: '苏州', role: 'destination' }]);
  await page.clock.runFor(1000);
  await expect.poll(requests).toEqual([
    { query: '苏州', role: 'destination' },
    { query: '上海', role: 'origin' },
  ]);
  await page.clock.resume();
  expectCleanFixture(fixture);
});

test('新输入取消旧搜索，输入法组合结束后才自动搜索', async ({ page }) => {
  await page.clock.install();
  const fixture = await openHome(page);
  await page.getByRole('tab', { name: '按条件规划' }).click();
  const input = page.getByRole('textbox', { name: '目的地，搜索城市或区域', exact: true });
  const candidates = page.getByTestId('destination-candidates');
  await page.evaluate(() => {
    const original = window.fetch.bind(window);
    const state = { queries: [] as string[], aborted: false, delivered: false, release: () => {} };
    Object.assign(window, { delayedPlaceSearch: state });
    window.fetch = (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (!url.pathname.endsWith('/places/search')) return original(input, init);
      const query = url.searchParams.get('q') || '';
      state.queries.push(query);
      if (query !== '甲地' || state.queries.filter((item) => item === '甲地').length > 1) return original(input, init);
      const signal = init?.signal ?? (input instanceof Request ? input.signal : null);
      if (signal) {
        state.aborted = signal.aborted;
        signal.addEventListener('abort', () => { state.aborted = true; }, { once: true });
      }
      // 模拟忽略取消信号的迟到响应。
      return new Promise<Response>((resolve) => {
        state.release = () => resolve(new Response(JSON.stringify({
          candidates: [{
            place: { place_id: 'offline:甲地', provider: 'osm', kind: 'city', name: '甲地', display_name: '甲地，中国', country_code: 'CN', latitude: 31.2, longitude: 121.4, admin_path: ['中国', '甲地'] },
            confidence: 1,
            requires_confirmation: true,
          }],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
      }).then((response) => {
        state.delivered = true;
        return response;
      });
    };
  });
  const requests = () => page.evaluate(() => (window as any).delayedPlaceSearch.queries as string[]);
  await input.focus();
  await page.clock.pauseAt(await page.evaluate(() => Date.now() + 100));
  await input.fill('甲地');
  await page.clock.runFor(1000);
  await expect.poll(requests).toEqual(['甲地']);

  await input.fill('苏州');
  await expect.poll(() => page.evaluate(() => (window as any).delayedPlaceSearch.aborted)).toBe(true);
  await expect(candidates.getByRole('button', { name: /^苏州(?:\s|$)/ })).toBeVisible();
  await input.press('ControlOrMeta+A');
  await input.dispatchEvent('compositionstart', { data: '' });
  await page.keyboard.insertText('乙地');
  await input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, isComposing: true });
  await input.dispatchEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, isComposing: true });
  await page.clock.runFor(1000);
  expect(await requests()).toEqual(['甲地']);
  await expect(input).toHaveValue('乙地');

  await input.dispatchEvent('compositionend', { data: '乙地' });
  await page.clock.runFor(1000);
  await expect.poll(requests).toEqual(['甲地', '乙地']);
  const currentCandidate = candidates.getByRole('button').filter({ hasText: '乙地' }).first();
  await expect(currentCandidate).toBeVisible();
  await page.evaluate(() => (window as any).delayedPlaceSearch.release());
  await expect.poll(() => page.evaluate(() => (window as any).delayedPlaceSearch.delivered)).toBe(true);
  await expect(currentCandidate).toBeVisible();
  await expect(candidates.getByRole('button').filter({ hasText: '甲地' })).toHaveCount(0);

  await page.clock.resume();
  await input.fill('甲地');
  await page.clock.pauseAt(await page.evaluate(() => Date.now() + 100));
  await expect(candidates.getByRole('button').filter({ hasText: '甲地' })).toHaveCount(0);
  await page.clock.runFor(1000);
  await expect.poll(requests).toEqual(['甲地', '乙地', '甲地']);
  await expect(candidates.getByRole('button').filter({ hasText: '甲地' }).first()).toBeVisible();
  await page.clock.resume();
  expectCleanFixture(fixture);
});

test('关闭新增后延迟候选不会重新展开', async ({ page }) => {
  const fixture = await openHome(page, { width: 1440, height: 900 });
  await page.getByRole('tab', { name: '按条件规划' }).click();
  const add = page.getByTestId('add-destination');
  const search = () => page.locator('.destination-search input');
  const candidates = page.getByTestId('destination-candidates');

  await search().fill('苏州');
  await candidates.getByRole('button').filter({ hasText: '苏州' }).first().click();
  await expect(page.getByTestId('destination-token-0')).toContainText('苏州');
  await expect(search()).toHaveCount(0);

  await add.click();
  let releaseDelay: () => void = () => {};
  const delay = new Promise<void>((resolve) => { releaseDelay = resolve; });
  let finishResponse: () => void = () => {};
  const responseSettled = new Promise<void>((resolve) => { finishResponse = resolve; });
  let delayed = false;
  let delayedStarted = false;
  await page.route('**/api/places/search**', async (route) => {
    const query = new URL(route.request().url()).searchParams.get('q') || '';
    if (!delayed || query !== '甲地') return route.fallback();
    delayed = false;
    delayedStarted = true;
    const name = query.replace(/[市\s]/g, '') || '甲地';
    await delay;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        candidates: [{
          place: { place_id: `osm:relation:${encodeURIComponent(name)}`, provider: 'osm', kind: 'city', name, display_name: `${name}，中国`, country_code: 'CN', latitude: 31.2, longitude: 121.4, admin_path: ['中国', name] },
          confidence: 1,
          requires_confirmation: true,
        }],
      }),
    }).catch(() => undefined);
    finishResponse();
  });

  delayed = true;
  await search().fill('甲地');
  await expect.poll(() => delayedStarted).toBe(true);
  await add.click();
  await expect(search()).toHaveCount(0);
  releaseDelay();
  await responseSettled;
  await expect(candidates).toHaveCount(0);
  await expect(search()).toHaveCount(0);
  await expect(page.locator('.destination-token')).toHaveCount(1);

  await add.click();
  await search().fill('甲地');
  await candidates.getByRole('button').filter({ hasText: '甲地' }).first().click();
  await expect(page.getByTestId('destination-token-1')).toContainText('甲地');
  expectCleanFixture(fixture);
});

async function openPlannerCalendar(page: Page) {
  await page.getByRole('tab', { name: '按条件规划' }).click();
  await expect(page.getByRole('textbox', { name: '出发地' })).toBeVisible();
  await page.getByTestId('date-range-trigger').click();
  const dialog = page.getByTestId('date-range-dialog');
  await expect(dialog).toBeVisible();
  await page.waitForTimeout(300);
  return dialog;
}

function calendarDay(page: Page, value: string) {
  return page.getByTestId('date-range-dialog').getByRole('button', { name: new RegExp(`^选择 ${value}`) });
}

test('日历标记今天、禁用过去并限制跨月 14 天边界', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-10-29T10:00:00+08:00'));
  const fixture = await openHome(page, { width: 2000, height: 880 });
  const dialog = await openPlannerCalendar(page);
  const trigger = page.getByTestId('date-range-trigger');
  const today = calendarDay(page, '2026-10-29');
  const past = calendarDay(page, '2026-10-28');

  await expect(page.getByRole('heading', { name: '2026 年 10 月', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '2026 年 11 月', exact: true })).toBeVisible();
  await expect(today).toHaveAttribute('aria-current', 'date');
  await expect(past).toBeDisabled();
  await expect(calendarDay(page, '2026-10-01')).toBeDisabled();

  await past.evaluate((element) => (element as HTMLButtonElement).click());
  await expect(trigger).toHaveAttribute('aria-label', '旅行日期：开始日期 → 结束日期');

  await today.click();
  await expect(today).toHaveAttribute('aria-pressed', 'true');
  await expect(calendarDay(page, '2026-11-11')).toBeEnabled();
  await expect(calendarDay(page, '2026-11-12')).toBeDisabled();
  await calendarDay(page, '2026-11-12').evaluate((element) => (element as HTMLButtonElement).click());
  await expect(trigger).toHaveAttribute('aria-label', '旅行日期：2026-10-29 → 结束日期');

  await calendarDay(page, '2026-11-11').click();
  await expect(trigger).toHaveAttribute('aria-label', '旅行日期：2026-10-29 → 2026-11-11 · 14 天 13 晚');
  await expect(dialog.getByRole('button', { name: '确认日期 · 14 天 13 晚', exact: true })).toBeEnabled();

  await dialog.getByRole('button', { name: '清除日期', exact: true }).click();
  await expect(trigger).toHaveAttribute('aria-label', '旅行日期：开始日期 → 结束日期');
  await expect(calendarDay(page, '2026-10-28')).toBeDisabled();
  await today.click();
  await today.click();
  await expect(trigger).toHaveAttribute('aria-label', '旅行日期：2026-10-29 → 2026-10-29 · 1 天 0 晚');
  await expect(dialog.getByRole('button', { name: '确认日期 · 1 天 0 晚', exact: true })).toBeEnabled();

  await dialog.getByRole('button', { name: '下个月', exact: true }).click();
  await calendarDay(page, '2026-11-20').click();
  await expect(trigger).toHaveAttribute('aria-label', '旅行日期：2026-11-20 → 结束日期');
  await calendarDay(page, '2026-11-05').click();
  await expect(trigger).toHaveAttribute('aria-label', '旅行日期：2026-11-05 → 结束日期');
  await page.getByRole('button', { name: '关闭日期选择', exact: true }).click();
  await expect(dialog).toBeHidden();
  await trigger.click();
  await expect(page.getByRole('heading', { name: '2026 年 11 月', exact: true })).toBeVisible();

  await dialog.getByRole('button', { name: '清除日期', exact: true }).click();
  await page.getByRole('button', { name: '关闭日期选择', exact: true }).click();
  await trigger.click();
  await expect(page.getByRole('heading', { name: '2026 年 10 月', exact: true })).toBeVisible();
  expectCleanFixture(fixture);
});

test('日历跨年边界与重新打开定位有效起点', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-12-25T10:00:00+08:00'));
  const fixture = await openHome(page, { width: 1440, height: 900 });
  const dialog = await openPlannerCalendar(page);
  const trigger = page.getByTestId('date-range-trigger');

  await expect(page.getByRole('heading', { name: '2026 年 12 月', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '2027 年 1 月', exact: true })).toBeVisible();
  await expect(calendarDay(page, '2026-12-25')).toHaveAttribute('aria-current', 'date');
  await calendarDay(page, '2026-12-25').click();
  await expect(calendarDay(page, '2027-01-07')).toBeEnabled();
  await expect(calendarDay(page, '2027-01-08')).toBeDisabled();
  await calendarDay(page, '2027-01-07').click();
  await expect(trigger).toHaveAttribute('aria-label', '旅行日期：2026-12-25 → 2027-01-07 · 14 天 13 晚');

  await dialog.getByRole('button', { name: '关闭日期选择', exact: true }).click();
  await trigger.click();
  await expect(page.getByRole('heading', { name: '2026 年 12 月', exact: true })).toBeVisible();
  expectCleanFixture(fixture);
});

test.describe('夏令时日历边界', () => {
  test.use({ timezoneId: 'America/New_York' });

  test('夏令时切换不改变 14 天边界', async ({ page }) => {
    await page.clock.setFixedTime(new Date('2027-03-10T12:00:00-05:00'));
    const fixture = await openHome(page, { width: 1440, height: 900 });
    await openPlannerCalendar(page);
    await expect(page.getByRole('heading', { name: '2027 年 3 月', exact: true })).toBeVisible();
    await expect(calendarDay(page, '2027-03-10')).toHaveAttribute('aria-current', 'date');
    await calendarDay(page, '2027-03-10').click();
    await expect(calendarDay(page, '2027-03-23')).toBeEnabled();
    await expect(calendarDay(page, '2027-03-24')).toBeDisabled();
    await calendarDay(page, '2027-03-23').click();
    await expect(page.getByTestId('date-range-trigger')).toHaveAttribute('aria-label', '旅行日期：2027-03-10 → 2027-03-23 · 14 天 13 晚');
    expectCleanFixture(fixture);
  });
});

test('移动端日期保留今天与 14 天禁用边界', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-10-29T10:00:00+08:00'));
  const fixture = await openHome(page, { width: 390, height: 844 });
  const dialog = await openPlannerCalendar(page);
  const today = calendarDay(page, '2026-10-29');

  await expect(page.getByRole('heading', { name: '2026 年 10 月', exact: true })).toBeVisible();
  await expect(today).toHaveAttribute('aria-current', 'date');
  await expect(calendarDay(page, '2026-10-28')).toBeDisabled();

  await today.click();
  await dialog.getByRole('button', { name: '下个月', exact: true }).click();
  await expect(page.getByRole('heading', { name: '2026 年 11 月', exact: true })).toBeVisible();
  await expect(calendarDay(page, '2026-11-11')).toBeEnabled();
  await expect(calendarDay(page, '2026-11-12')).toBeDisabled();
  expectCleanFixture(fixture);
});

test('390px 真实触摸可从非排序区滚动并按住目的地同排与跨行排序', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  const fixture = await openHome(page, { width: 390, height: 844 });
  await page.getByRole('tab', { name: '按条件规划' }).click();

  const choose = async (name: string, expectFocused = true) => {
    const input = page.locator('.destination-search input');
    if (expectFocused) await expect(input).toBeFocused();
    else await input.tap();
    await input.fill(name);
    await page.getByTestId('destination-candidates').getByRole('button').filter({ hasText: name }).first().tap();
  };

  await choose('苏州', false);
  await page.getByTestId('add-destination').tap();
  await choose('杭州');
  await expect(page.locator('.destination-token')).toHaveCount(2);
  const client = await context.newCDPSession(page);
  const touch = async (type: 'touchStart' | 'touchMove' | 'touchEnd', x?: number, y?: number) => {
    await client.send('Input.dispatchTouchEvent', {
      type,
      touchPoints: type === 'touchEnd' ? [] : [{ x: x!, y: y!, id: 1 }],
    });
  };

  const scrollBefore = await page.evaluate(() => ({
    window: window.scrollY,
    hero: (document.querySelector('.new-trip-hero') as HTMLElement | null)?.scrollTop ?? 0,
  }));
  await touch('touchStart', 12, 200);
  await touch('touchMove', 12, 120);
  await touch('touchMove', 12, 50);
  await page.waitForTimeout(120);
  await touch('touchEnd');
  await expect.poll(() => page.evaluate((before) => {
    const windowScroll = window.scrollY;
    const heroScroll = (document.querySelector('.new-trip-hero') as HTMLElement | null)?.scrollTop ?? 0;
    return windowScroll > before.window || heroScroll > before.hero + 10;
  }, scrollBefore)).toBe(true);
  await expect(page.getByTestId('destination-token-0')).toContainText('苏州');

  await page.getByTestId('destination-token-0').scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  const handle = (await page.getByTestId('destination-token-0').boundingBox())!;
  const secondAfterScroll = (await page.getByTestId('destination-token-1').boundingBox())!;
  await touch('touchStart', handle.x + 10, handle.y + handle.height / 2);
  await page.waitForTimeout(240);
  await expect(page.getByTestId('destination-token-0')).toHaveClass(/is-dragging/);
  const sameRowTarget = { x: secondAfterScroll.x + secondAfterScroll.width / 2, y: secondAfterScroll.y + secondAfterScroll.height / 2 };
  for (const ratio of [0.25, 0.5, 0.75, 1]) {
    await touch('touchMove', handle.x + 10 + (sameRowTarget.x - handle.x - 10) * ratio, sameRowTarget.y);
  }
  await expect(page.getByTestId('destination-token-1')).toHaveClass(/is-drop-target/);
  await page.waitForTimeout(60);
  await touch('touchEnd');
  await expect(page.getByTestId('destination-token-0')).toContainText('杭州');
  await expect(page.getByTestId('destination-token-1')).toContainText('苏州');
  const sameRowTouchOrder = await page.locator('.destination-token-name').allTextContents();
  expect(sameRowTouchOrder).toEqual(['杭州', '苏州']);

  for (const name of ['甲地', '乙地', '丙地']) await choose(name, false);
  await expect(page.locator('.destination-token')).toHaveCount(5);
  await expect(page.locator('.destination-search')).toHaveCount(0);
  await expect(page.getByTestId('add-destination')).toHaveText('目的地到达上限');
  await expect(page.getByTestId('add-destination')).toBeDisabled();
  expect(await page.locator('.destination-token-name').allTextContents()).toEqual(['杭州', '苏州', '甲地', '乙地', '丙地']);

  await page.getByTestId('destination-token-0').scrollIntoViewIfNeeded();
  const fullHandle = (await page.getByTestId('destination-token-0').boundingBox())!;
  const fullFourth = (await page.getByTestId('destination-token-3').boundingBox())!;
  await touch('touchStart', fullHandle.x + 10, fullHandle.y + fullHandle.height / 2);
  await page.waitForTimeout(240);
  await expect(page.getByTestId('destination-token-0')).toHaveClass(/is-dragging/);
  const crossStart = { x: fullHandle.x + 10, y: fullHandle.y + fullHandle.height / 2 };
  const crossRowTarget = { x: fullFourth.x + fullFourth.width / 2, y: fullFourth.y + fullFourth.height / 2 };
  for (const ratio of [0.25, 0.5, 0.75, 1]) {
    await touch('touchMove', crossStart.x + (crossRowTarget.x - crossStart.x) * ratio, crossStart.y + (crossRowTarget.y - crossStart.y) * ratio);
  }
  await expect(page.getByTestId('destination-token-3')).toHaveClass(/is-drop-target/);
  await page.waitForTimeout(60);
  await touch('touchEnd');
  const crossRowTouchOrder = await page.locator('.destination-token-name').allTextContents();
  expect(crossRowTouchOrder).toEqual(['苏州', '甲地', '乙地', '杭州', '丙地']);

  expectCleanFixture(fixture);
  await context.close();
});

test('目的地候选在 Escape、外部操作和切换模式后收起且旧搜索不重开', async ({ page }) => {
  const fixture = await openHome(page, { width: 1440, height: 900 });
  await page.getByRole('tab', { name: '按条件规划' }).click();
  const input = page.locator('.destination-search input');
  const candidates = page.getByTestId('destination-candidates');

  await input.click();
  await input.fill('苏州');
  await input.press('Escape');
  await expect(candidates).toHaveCount(0);
  await page.waitForTimeout(600);
  await expect(candidates).toHaveCount(0);

  await input.fill('');
  await input.fill('苏州');
  await expect(candidates).toBeVisible();
  await page.getByRole('tab', { name: '一句话规划' }).click();
  await expect(candidates).toHaveCount(0);
  await page.waitForTimeout(600);
  await expect(candidates).toHaveCount(0);
  await page.getByRole('tab', { name: '按条件规划' }).click();
  await expect(candidates).toHaveCount(0);
  await page.waitForTimeout(600);
  await expect(candidates).toHaveCount(0);

  await input.focus();
  await expect(candidates).toBeVisible();
  await input.press('Tab');
  await expect(candidates).toHaveCount(0);

  await input.focus();
  await input.fill('');
  await input.fill('苏州');
  const candidate = candidates.getByRole('button').filter({ hasText: '苏州' }).first();
  await expect(candidate).toBeVisible();
  await candidate.click();
  await expect(page.getByTestId('destination-token-0')).toContainText('苏州');
  await expect(candidates).toHaveCount(0);
  expectCleanFixture(fixture);
});
