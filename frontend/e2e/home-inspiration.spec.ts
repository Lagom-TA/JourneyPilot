import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

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
    localStorage.setItem('sta_last_session_id', 'home-e2e');
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
  if (configurationUnavailable) {
    await expect(page.getByTestId('request-failure-notice')).toBeVisible();
  } else {
    await expect(page.getByTestId('natural-trip-input')).toBeVisible();
  }
  await expect(page.getByTestId('travel-atlas')).toHaveAttribute('data-scene', 'southwest');
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(500);
  return { pageErrors, unmocked, recoverConfiguration: () => { configurationAvailable = true; } };
}

function expectCleanFixture(fixture: { pageErrors: string[]; unmocked: string[] }) {
  expect(fixture.pageErrors).toEqual([]);
  expect(fixture.unmocked).toEqual([]);
}

function writeDestinationEvidence(name: string, data: unknown) {
  const directory = '../output/polish/20261029-1252-destination-tokens';
  mkdirSync(directory, { recursive: true });
  writeFileSync(`${directory}/${name}`, JSON.stringify(data, null, 2));
}

async function destinationGeometry(page: Page) {
  return page.evaluate(() => {
    const list = document.querySelector('.destination-token-flow');
    const search = document.querySelector('.destination-search');
    const rowRects = Array.from(document.querySelectorAll('.destination-token')).map((element) => {
      const rect = element.getBoundingClientRect();
      return { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, width: rect.width, height: rect.height };
    });
    const searchRect = search?.getBoundingClientRect();
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      rows: rowRects,
      search: searchRect ? { top: searchRect.top, bottom: searchRect.bottom, left: searchRect.left, right: searchRect.right } : null,
      listClientWidth: list?.clientWidth ?? null,
      listScrollWidth: list?.scrollWidth ?? null,
      documentScrollWidth: document.documentElement.scrollWidth,
    };
  });
}

test('首页布局、四种示例与灵感回填', async ({ page }) => {
  const fixture = await openHome(page, { width: 2000, height: 880 });
  const removedCopy = [
    'LET’S GO SOMEWHERE',
    '说出目的地、时间和偏好，我帮你整理成每天都能照着走的旅行计划。',
    '这趟旅行，你想怎么过？',
    '不用组织得很完整，想到什么就说什么。',
    '⌘ / Ctrl＋Enter',
    '从一句想法，到一路的风景。',
  ];
  for (const text of removedCopy) await expect(page.getByText(text, { exact: true })).toHaveCount(0);

  const headingBox = await page.locator('.new-trip-copy').boundingBox();
  const plannerBox = await page.locator('.new-trip-content > .planner-card').boundingBox();
  expect(headingBox).not.toBeNull();
  expect(plannerBox).not.toBeNull();
  expect(plannerBox!.width).toBeGreaterThan(740);
  const topSpace = headingBox!.y - 64;
  const bottomSpace = 880 - (plannerBox!.y + plannerBox!.height);
  expect(Math.abs(topSpace - bottomSpace)).toBeLessThan(110);

  const scenes = [
    { id: 'jiangnan', title: '苏州＋杭州 4 日' },
    { id: 'northwest', title: '敦煌＋张掖 6 日' },
    { id: 'southwest', title: '成都＋重庆 7 日' },
    { id: 'island', title: '海口＋三亚 5 日' },
  ];
  for (const scene of scenes) {
    await page.getByTestId(`atlas-tab-${scene.id}`).click();
    await expect(page.getByTestId('travel-atlas')).toHaveAttribute('data-scene', scene.id);
    const example = page.getByRole('button', { name: `用这个灵感填入规划：${scene.title}`, exact: true });
    await expect(example).toBeVisible();
    await expect(example.locator('.atlas-example-title')).toHaveText(scene.title);
    await expect(page.locator('.atlas-scene')).toHaveCount(1);
  }
  await expect(page.locator('.atlas-heading, .atlas-city, .atlas-day-stamp, .atlas-example-count, .atlas-motion-toggle')).toHaveCount(0);

  const input = page.getByTestId('natural-trip-input');
  await page.getByRole('button', { name: '用这个灵感填入规划：海口＋三亚 5 日', exact: true }).click();
  await expect(input).toHaveValue('想从广州去海口和三亚，5 天，2 位成人，想看海、吃海鲜，住得舒服一点，总预算约 8000 元。');
  await expect(input).toBeFocused();
  await expect(page.getByRole('button', { name: '开始规划', exact: true })).toBeEnabled();
  expectCleanFixture(fixture);
});

test('配置读取失败保持完整规划卡并可重试恢复', async ({ page }) => {
  const fixture = await openHome(page, { width: 1440, height: 900 }, true);
  const planner = page.locator('.new-trip-content > .planner-card');
  await expect(page.getByRole('tab', { name: '一句话规划' })).toBeVisible();
  await expect(page.getByRole('tab', { name: '按条件规划' })).toBeVisible();
  await expect(page.getByText('暂时无法开始规划', { exact: true })).toBeVisible();
  await expect(page.getByText('重试不会清空已经填写的内容', { exact: true })).toBeVisible();
  const box = await planner.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.height).toBeGreaterThan(400);
  fixture.recoverConfiguration();
  await page.getByTestId('request-failure-action').click();
  await expect(page.getByTestId('natural-trip-input')).toBeVisible();
  await expect(page.getByTestId('request-failure-notice')).toHaveCount(0);
  expectCleanFixture(fixture);
});

test('自动轮播进度与场景键盘导航', async ({ page }) => {
  const fixture = await openHome(page);
  const tabs = page.locator('.atlas-scene-tabs > button');
  const panelIds = await tabs.evaluateAll((elements) => elements.map((element) => element.getAttribute('aria-controls')));
  expect(new Set(panelIds).size).toBe(1);
  expect(panelIds[0]).toBeTruthy();
  await expect(page.locator('.atlas-panel')).toHaveAttribute('id', panelIds[0]!);
  await expect(page.getByTestId('atlas-motion-toggle')).toHaveCount(0);

  const atlas = page.getByTestId('travel-atlas');
  await expect.poll(() => atlas.evaluate((element) => Number(element.style.getPropertyValue('--atlas-progress')))).toBeGreaterThan(0.2);
  await expect.poll(() => atlas.evaluate((element) => Number.parseFloat(element.style.getPropertyValue('--atlas-frost')))).toBeGreaterThan(4);
  await expect(atlas).toHaveAttribute('data-scene', 'jiangnan', { timeout: 8000 });

  const southwest = page.getByTestId('atlas-tab-southwest');
  await southwest.focus();
  await southwest.press('ArrowRight');
  const jiangnan = page.getByTestId('atlas-tab-jiangnan');
  await expect(jiangnan).toHaveAttribute('aria-selected', 'true');
  await expect(jiangnan).toBeFocused();
  await jiangnan.press('End');
  const island = page.getByTestId('atlas-tab-island');
  await expect(island).toHaveAttribute('aria-selected', 'true');
  await expect(island).toBeFocused();
  await island.press('Home');
  await expect(southwest).toHaveAttribute('aria-selected', 'true');
  await expect(southwest).toBeFocused();
  await southwest.press('ArrowLeft');
  await expect(island).toHaveAttribute('aria-selected', 'true');
  await expect(island).toBeFocused();
  expectCleanFixture(fixture);
});

test('双模式保留草稿、共享高度并按当前模式回填', async ({ page }) => {
  const fixture = await openHome(page, { width: 1600, height: 960 });
  const naturalInput = page.getByTestId('natural-trip-input');
  const naturalTab = page.getByRole('tab', { name: '一句话规划' });
  const structuredTab = page.getByRole('tab', { name: '按条件规划' });
  const planner = page.locator('.new-trip-content > .planner-card');
  await naturalInput.fill('我想保留这句话');
  await structuredTab.click();
  const skip = page.getByRole('button', { name: '暂时不用默认值', exact: true });
  if (await skip.count()) await skip.click();
  const origin = page.getByRole('textbox', { name: '从哪里出发' });
  await expect(origin).toBeVisible();

  const structuredBox = await planner.boundingBox();
  await naturalTab.click();
  await expect(naturalInput).toHaveValue('我想保留这句话');
  const naturalBox = await planner.boundingBox();
  expect(structuredBox).not.toBeNull();
  expect(naturalBox).not.toBeNull();
  expect(Math.abs(structuredBox!.height - naturalBox!.height)).toBeLessThan(2);

  await structuredTab.click();
  await origin.fill('深');
  const budgetInput = page.getByLabel('总预算（可选）');
  await expect(budgetInput).toHaveAttribute('type', 'text');
  await expect(budgetInput).toHaveAttribute('inputmode', 'decimal');
  await expect(budgetInput).not.toHaveAttribute('min');
  await budgetInput.fill('4567');
  await page.getByRole('button', { name: '增加成人' }).click();
  await naturalTab.click();
  await structuredTab.click();
  await expect(origin).toHaveValue('深');
  await expect(page.getByLabel('总预算（可选）')).toHaveValue('4567');
  await expect(page.locator('.planner-party')).toContainText('3');
  await expect(page.getByRole('button', { name: '其他同行需求' })).toHaveCount(0);
  await expect(page.getByText('只用于花费参考', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '户外自然', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '亲子友好', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '更多偏好' }).click();
  await expect(page.getByRole('button', { name: '户外自然', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '亲子友好', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '更多偏好' }).click();

  await page.getByTestId('atlas-tab-island').click();
  await page.getByRole('button', { name: '用这个灵感填入规划：海口＋三亚 5 日', exact: true }).click();
  await expect(structuredTab).toHaveAttribute('aria-selected', 'true');
  await expect(origin).toHaveValue('广州');
  await expect(page.getByTestId('destination-token-0')).toContainText('海口');
  await expect(page.getByTestId('destination-token-1')).toContainText('三亚');
  await expect(page.getByLabel('总预算（可选）')).toHaveValue('8000');
  await expect(naturalInput).toHaveValue('想从广州去海口和三亚，5 天，2 位成人，想看海、吃海鲜，住得舒服一点，总预算约 8000 元。');
  await naturalTab.click();
  await expect(naturalInput).toBeVisible();
  await expect(naturalInput).toHaveValue(/海口和三亚/);
  expectCleanFixture(fixture);
});

test('移动端保持完整示例与输入回填', async ({ page }) => {
  const fixture = await openHome(page, { width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const atlasBox = await page.getByTestId('travel-atlas').boundingBox();
  expect(atlasBox).not.toBeNull();
  expect(atlasBox!.height).toBe(500);
  await page.getByTestId('atlas-tab-island').click();
  await expect(page.getByTestId('travel-atlas')).toHaveAttribute('data-scene', 'island');
  await expect(page.locator('.atlas-scene')).toHaveCount(1);
  await expect(page.locator('.atlas-theme-island')).toBeVisible();
  await page.getByRole('button', { name: '用这个灵感填入规划：海口＋三亚 5 日', exact: true }).click();
  await expect(page.getByTestId('natural-trip-input')).toBeFocused();
  await expect(page.getByTestId('natural-trip-input')).toHaveValue(/海口和三亚/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expectCleanFixture(fixture);
});

test('减少动态效果时停用环境动画与指针视差', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await openHome(page);
  await expect(page.getByTestId('atlas-motion-toggle')).toHaveCount(0);
  await expect(page.locator('.atlas-liquid-lens')).toHaveCSS('animation-name', 'none');
  await page.mouse.move(1100, 320);
  const nearX = await page.getByTestId('travel-atlas').evaluate((element) => element.style.getPropertyValue('--atlas-near-x'));
  expect(['', '0px']).toContain(nearX);
  await page.getByTestId('atlas-tab-jiangnan').click();
  await expect(page.getByTestId('travel-atlas')).toHaveAttribute('data-scene', 'jiangnan');
  await expect(page.locator('.atlas-scene')).toHaveCount(1);
  await page.getByTestId('natural-trip-input').fill('想从深圳去杭州，轻松玩几天。');
  const action = page.locator('.planner-action-area .planner-main-action');
  await action.hover();
  const motion = await action.evaluate((element) => {
    const style = getComputedStyle(element, '::before');
    return { name: style.animationName, duration: style.animationDuration };
  });
  expect(motion.name).toBe('none');
  expect(Number.parseFloat(motion.duration)).toBe(0);
  expectCleanFixture(fixture);
});

type PlannerRect = { x: number; y: number; width: number; height: number; bottom: number };
type PlannerGeometry = { card: PlannerRect; action: PlannerRect | null; activePanel: PlannerRect | null; activePanelBottom: number | null };

async function plannerGeometry(page: Page): Promise<PlannerGeometry> {
  return page.evaluate(() => {
    const card = document.querySelector('.new-trip-content > .planner-card');
    const action = Array.from(document.querySelectorAll<HTMLButtonElement>('.planner-main-action'))
      .find((element) => !element.closest('[aria-hidden="true"]') && getComputedStyle(element).visibility !== 'hidden');
    const activePanel = document.querySelector('.planner-panel.is-active');
    const rect = (element: Element) => {
      const box = element.getBoundingClientRect();
      return { x: box.x + scrollX, y: box.y + scrollY, width: box.width, height: box.height, bottom: box.bottom + scrollY };
    };
    if (!card) throw new Error('planner card missing');
    return {
      card: rect(card),
      action: action ? rect(action) : null,
      activePanel: activePanel ? rect(activePanel) : null,
      activePanelBottom: activePanel ? rect(activePanel).bottom : null,
    };
  });
}

function expectStablePlannerGeometry(natural: PlannerGeometry, structured: PlannerGeometry) {
  expect(natural.action).not.toBeNull();
  expect(structured.action).not.toBeNull();
  expect(Math.abs(natural.card.y - structured.card.y)).toBeLessThan(2);
  expect(Math.abs(natural.card.height - structured.card.height)).toBeLessThan(2);
  expect(Math.abs(natural.action!.x - structured.action!.x)).toBeLessThan(2);
  expect(Math.abs(natural.action!.y - structured.action!.y)).toBeLessThan(2);
  expect(Math.abs(natural.action!.width - structured.action!.width)).toBeLessThan(2);
  expect(Math.abs(natural.action!.height - structured.action!.height)).toBeLessThan(2);
}

test('双模式共享稳定主按钮、紧凑偏好行与宽窄屏几何', async ({ browser }) => {
  const geometry: Array<{ viewport: { width: number; height: number }; natural: PlannerGeometry; structured: PlannerGeometry; compactNaturalHeight: number }> = [];
  for (const viewport of [{ width: 2000, height: 880 }, { width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    const fixture = await openHome(page, viewport);
    const planner = page.locator('.new-trip-content > .planner-card');
    const action = page.locator('.planner-action-area .planner-main-action');
    const naturalInput = page.getByTestId('natural-trip-input');
    const naturalTab = page.getByRole('tab', { name: '一句话规划' });
    const structuredTab = page.getByRole('tab', { name: '按条件规划' });

    await expect(page.getByText('目的地还没定也没关系，先说说你想要怎样的旅行。', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '还没定目的地？从偏好开始', exact: true })).toHaveCount(0);
    await expect(page.getByText('这次想要', { exact: true })).toHaveCount(0);
    await expect(action).toHaveCount(1);
    await expect(action).toBeDisabled();

    await naturalInput.fill('想从深圳去杭州，轻松玩几天。');
    await expect(action).toBeEnabled();
    if (viewport.width === 2000) {
      await action.hover();
      const motion = await action.evaluate((element) => {
        const style = getComputedStyle(element, '::before');
        return { name: style.animationName, duration: style.animationDuration };
      });
      expect(motion.name).toBe('planner-main-sweep');
      expect(Number.parseFloat(motion.duration)).toBeGreaterThanOrEqual(2.8);
      await page.mouse.move(10, 10);
    }

    await structuredTab.click();
    await expect(page.getByRole('heading', { name: '选择你的常用出发地' })).toBeVisible();
    await expect(page.getByRole('button', { name: '保存并继续', exact: true })).toBeVisible();
    await page.getByRole('button', { name: '暂时不用默认值', exact: true }).click();
    await expect(page.getByRole('textbox', { name: '从哪里出发' })).toBeVisible();
    await expect(action).toBeVisible();
    await expect(page.locator('.planner-panel-natural')).toHaveAttribute('inert', '');
    await expect(page.locator('.planner-panel-natural')).toHaveAttribute('aria-hidden', 'true');

    const styleOptions = await page.locator('.planner-style-options').boundingBox();
    const budget = await page.locator('.planner-budget-input').boundingBox();
    if (viewport.width === 390) await planner.evaluate((element) => element.scrollIntoView({ block: 'nearest' }));
    const structured = await plannerGeometry(page);
    await page.screenshot({ path: `../output/polish/20261029-1207-home-action-layout/home-${viewport.width}-structured.png`, fullPage: true });
    await page.screenshot({ path: `../output/polish/20261029-1252-home-form-rhythm/home-${viewport.width}-structured.png`, fullPage: true });

    await naturalTab.click();
    await expect(naturalInput).toHaveValue('想从深圳去杭州，轻松玩几天。');
    await expect(page.locator('.planner-panel-structured')).toHaveAttribute('inert', '');
    if (viewport.width === 390) await planner.evaluate((element) => element.scrollIntoView({ block: 'nearest' }));
    const natural = await plannerGeometry(page);
    await page.screenshot({ path: `../output/polish/20261029-1207-home-action-layout/home-${viewport.width}-natural.png`, fullPage: true });
    await page.screenshot({ path: `../output/polish/20261029-1252-home-form-rhythm/home-${viewport.width}-natural.png`, fullPage: true });

    expectStablePlannerGeometry(natural, structured);
    expect(natural.card.bottom - natural.action!.bottom).toBeGreaterThan(10);
    expect(natural.card.bottom - natural.action!.bottom).toBeLessThan(28);
    expect(structured.card.bottom - structured.action!.bottom).toBeGreaterThan(10);
    expect(structured.card.bottom - structured.action!.bottom).toBeLessThan(28);
    expect(natural.activePanel!.bottom).toBeLessThanOrEqual(natural.action!.y + 1);
    expect(structured.activePanel!.bottom).toBeLessThanOrEqual(structured.action!.y + 1);

    expect(styleOptions).not.toBeNull();
    expect(budget).not.toBeNull();
    if (viewport.width >= 1440) {
      expect(budget!.y).toBeGreaterThanOrEqual(styleOptions!.y - 2);
      expect(budget!.y).toBeLessThanOrEqual(styleOptions!.y + styleOptions!.height - 2);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

    await structuredTab.click();
    await expect(action).toHaveCount(1);
    await action.click();
    await expect(page.getByText('请从地点候选中确认出发地和所有目的地。', { exact: true })).toBeVisible();
    await naturalTab.click();
    await expect(naturalInput).toHaveValue('想从深圳去杭州，轻松玩几天。');
    const backToNatural = await plannerGeometry(page);
    expectStablePlannerGeometry(natural, backToNatural);

    if (viewport.width === 2000) {
      await structuredTab.click();
      await page.getByRole('button', { name: '更多偏好' }).click();
      await expect(page.getByRole('button', { name: '户外自然', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: '摄影', exact: true })).toBeVisible();
      await page.screenshot({ path: '../output/polish/20261029-1207-home-action-layout/home-2000-more-preferences.png', fullPage: true });
      await page.screenshot({ path: '../output/polish/20261029-1252-home-form-rhythm/home-2000-more-preferences.png', fullPage: true });
    }

    expectCleanFixture(fixture);
    geometry.push({ viewport, natural, structured, compactNaturalHeight: natural.card.height });
    await context.close();
  }
  expect(geometry).toHaveLength(3);
  expect(geometry[0].natural.card.height).toBeLessThan(507.5);
  expect(geometry[1].natural.card.height).toBeLessThan(507.5);
  expect(geometry[2].natural.card.height).toBeLessThan(740);
});

test('目的地首站全宽常驻、紧凑小块换行与二维排序', async ({ page }) => {
  test.setTimeout(90_000);
  const fixture = await openHome(page, { width: 2000, height: 880 });
  await page.getByRole('tab', { name: '按条件规划' }).click();
  const skip = page.getByRole('button', { name: '暂时不用默认值', exact: true });
  if (await skip.count()) await skip.click();
  const field = page.getByTestId('destination-token-field');
  const add = page.getByTestId('add-destination');
  const tokens = page.locator('.destination-token');
  const candidates = page.getByTestId('destination-candidates');
  const search = () => page.locator('.destination-search input');

  await expect(field).toBeVisible();
  await expect(field).toHaveAttribute('data-state', 'base');
  await expect(tokens).toHaveCount(0);
  await expect(search()).toHaveCount(1);
  await expect(search()).toBeVisible();
  await expect(add).toHaveText('新增目的地');
  await expect(add).toHaveAttribute('aria-expanded', 'true');
  await expect(add).toHaveAttribute('aria-controls', await field.locator('.destination-base-search').getAttribute('id') ?? '');

  const initialField = (await field.boundingBox())!;
  const initialSearch = (await page.locator('.destination-search').boundingBox())!;
  const initialAdd = (await add.boundingBox())!;
  expect(initialAdd.x).toBeGreaterThan(initialSearch.x + initialSearch.width - 1);
  expect(initialAdd.x + initialAdd.width - initialSearch.x).toBeGreaterThanOrEqual(initialField.width - 2);
  expect(Math.abs((initialAdd.y + initialAdd.height / 2) - (initialSearch.y + initialSearch.height / 2))).toBeLessThan(8);
  await page.screenshot({ path: '../output/polish/20261029-1252-destination-tokens/destination-r9r10-2000-initial.png', fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(250);
  await page.screenshot({ path: '../output/polish/20261029-1252-destination-tokens/destination-r9r10-390-initial.png', fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.waitForTimeout(250);

  await add.click();
  await expect(search()).toBeFocused();
  await expect(field).toHaveAttribute('data-state', 'base');
  await expect(search()).toHaveCount(1);
  await add.click();
  await expect(search()).toBeFocused();
  await expect(search()).toHaveCount(1);

  const choose = async (name: string, expectFocused = true) => {
    const input = search();
    await expect(input).toHaveCount(1);
    if (expectFocused) await expect(input).toBeFocused();
    else await input.click();
    await input.fill(name);
    const candidate = candidates.getByRole('button').filter({ hasText: name }).first();
    await expect(candidate).toBeVisible();
    await candidate.click();
  };

  const dragToken = async (from: number, to: number) => {
    const handle = (await page.getByTestId(`destination-token-${from}`).locator('.destination-token-drag').boundingBox())!;
    const target = (await page.getByTestId(`destination-token-${to}`).boundingBox())!;
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
    await page.mouse.down();
    await page.mouse.move(target.x + target.width / 2, target.y + target.height / 2, { steps: 8 });
    await page.mouse.up();
    await expect(page.locator('.destination-token.is-dragging')).toHaveCount(0);
  };

  await choose('苏州', false);
  await expect(page.getByTestId('destination-token-0')).toContainText('苏州');
  await expect(tokens).toHaveCount(1);
  await expect(search()).toHaveCount(0);
  await expect(add).toHaveText('新增目的地');
  await expect(add).toHaveAttribute('aria-expanded', 'false');
  await expect(add).toBeFocused();
  const oneChip = (await page.getByTestId('destination-token-0').boundingBox())!;
  const flow = (await page.locator('.destination-token-flow').boundingBox())!;
  expect(oneChip.width).toBeLessThan(flow.width / 2);
  expect(initialAdd.x).toBeGreaterThan(oneChip.x + oneChip.width - 1);

  await add.click();
  await expect(search()).toBeFocused();
  await expect(add).toHaveText('关闭新增');
  await expect(add).toHaveAttribute('aria-expanded', 'true');
  const firstRow = (await page.getByTestId('destination-token-0').boundingBox())!;
  const firstSearch = (await search().boundingBox())!;
  expect(firstSearch.y).toBeGreaterThanOrEqual(firstRow.y + firstRow.height - 1);

  await choose('杭州');
  await expect(page.getByTestId('destination-token-1')).toContainText('杭州');
  await expect(search()).toBeFocused();
  const desktopTwoExpanded = await destinationGeometry(page);
  expect(desktopTwoExpanded.rows).toHaveLength(2);
  expect(Math.abs(desktopTwoExpanded.rows[0].top - desktopTwoExpanded.rows[1].top)).toBeLessThan(2);
  const desktopSearch = (await search().boundingBox())!;
  expect(desktopSearch.y).toBeGreaterThanOrEqual(desktopTwoExpanded.rows[0].bottom - 1);
  await page.screenshot({ path: '../output/polish/20261029-1252-destination-tokens/destination-r9r10-2000-two-expanded.png', fullPage: true });

  await add.click();
  await expect(search()).toHaveCount(0);
  await expect(tokens).toHaveCount(2);
  await expect(add).toHaveText('新增目的地');
  await expect(add).toBeFocused();
  await page.screenshot({ path: '../output/polish/20261029-1252-destination-tokens/destination-r9r10-2000-two-collapsed.png', fullPage: true });

  await dragToken(1, 0);
  await expect(page.getByTestId('destination-token-0')).toContainText('杭州');
  await expect(page.getByTestId('destination-token-1')).toContainText('苏州');
  const sameRowMouse = await page.locator('.destination-token-name').allTextContents();
  expect(sameRowMouse).toEqual(['杭州', '苏州']);

  await page.getByTestId('destination-token-1').focus();
  await page.getByTestId('destination-token-1').press('ArrowUp');
  await expect(page.getByTestId('destination-token-0')).toContainText('苏州');

  await add.click();
  await expect(search()).toBeFocused();
  await search().press('Backspace');
  await expect(tokens).toHaveCount(1);
  await expect(page.getByTestId('destination-token-0')).toContainText('苏州');
  await expect(search()).toBeFocused();

  await search().dispatchEvent('compositionstart');
  await search().press('Backspace');
  await expect(tokens).toHaveCount(1);
  await search().dispatchEvent('compositionend');

  await choose('杭州');
  await expect(tokens).toHaveCount(2);
  for (const name of ['南京', '宁波', '绍兴']) await choose(name);
  await expect(tokens).toHaveCount(5);
  await expect(search()).toHaveCount(0);
  await expect(add).toHaveText('目的地到达上限');
  await expect(add).toBeDisabled();
  await expect(add).toHaveAttribute('aria-expanded', 'false');
  const desktopFive = await destinationGeometry(page);
  expect(desktopFive.rows).toHaveLength(5);
  for (const row of desktopFive.rows) expect(row.width).toBeLessThan(desktopFive.listClientWidth! / 3);
  expect(desktopFive.search).toBeNull();
  expect(desktopFive.documentScrollWidth).toBeLessThanOrEqual(desktopFive.viewport.width);
  const fiveInitial = await page.locator('.destination-token-name').allTextContents();
  expect(fiveInitial).toEqual(['苏州', '杭州', '南京', '宁波', '绍兴']);
  await page.screenshot({ path: '../output/polish/20261029-1252-destination-tokens/destination-r9r10-2000-five-limit.png', fullPage: true });

  await dragToken(0, 1);
  const fullMouseOrder = await page.locator('.destination-token-name').allTextContents();
  expect(fullMouseOrder).toEqual(['杭州', '苏州', '南京', '宁波', '绍兴']);
  await page.getByTestId('destination-token-4').focus();
  await page.getByTestId('destination-token-4').press('ArrowUp');
  const fullKeyboardOrder = await page.locator('.destination-token-name').allTextContents();
  expect(fullKeyboardOrder).toEqual(['杭州', '苏州', '南京', '绍兴', '宁波']);
  await page.getByTestId('destination-token-3').press('ArrowDown');
  expect(await page.locator('.destination-token-name').allTextContents()).toEqual(fullMouseOrder);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(300);
  const mobileFive = await destinationGeometry(page);
  expect(mobileFive.rows).toHaveLength(5);
  const rowTops = new Set(mobileFive.rows.map((row) => Math.round(row.top)));
  expect(rowTops.size).toBeGreaterThanOrEqual(2);
  for (const row of mobileFive.rows) expect(row.width).toBeLessThan(mobileFive.viewport.width * 0.6);
  expect(mobileFive.documentScrollWidth).toBeLessThanOrEqual(mobileFive.viewport.width);
  await page.screenshot({ path: '../output/polish/20261029-1252-destination-tokens/destination-r9r10-390-five-limit.png', fullPage: true });

  const sourceRow = mobileFive.rows[0];
  const targetRow = mobileFive.rows[3];
  expect(targetRow.top).toBeGreaterThan(sourceRow.top + sourceRow.height / 2);
  await dragToken(0, 3);
  const crossRowMouse = await page.locator('.destination-token-name').allTextContents();
  expect(crossRowMouse).toEqual(['苏州', '南京', '宁波', '杭州', '绍兴']);
  await page.screenshot({ path: '../output/polish/20261029-1252-destination-tokens/destination-r9r10-390-mouse-cross-row.png', fullPage: true });

  for (let index = 0; index < 5; index += 1) {
    await tokens.last().focus();
    await tokens.last().press('Delete');
  }
  await expect(tokens).toHaveCount(0);
  await expect(search()).toHaveCount(1);
  await expect(search()).toBeVisible();
  await expect(field).toHaveAttribute('data-state', 'base');
  await expect(add).toHaveText('新增目的地');
  await expect(add).toHaveAttribute('aria-expanded', 'true');
  await expect(search()).toBeFocused();
  await page.screenshot({ path: '../output/polish/20261029-1252-destination-tokens/destination-r9r10-390-zero.png', fullPage: true });

  await choose('苏州', false);
  await add.click();
  await choose('杭州');
  await expect(tokens).toHaveCount(2);
  await expect(search()).toBeVisible();
  await page.screenshot({ path: '../output/polish/20261029-1252-destination-tokens/destination-r9r10-390-two-expanded.png', fullPage: true });
  await add.click();
  await expect(search()).toHaveCount(0);
  await page.screenshot({ path: '../output/polish/20261029-1252-destination-tokens/destination-r9r10-390-two-collapsed.png', fullPage: true });
  await tokens.first().locator('.destination-token-remove').click();
  await tokens.first().locator('.destination-token-remove').click();
  await expect(tokens).toHaveCount(0);
  await expect(search()).toHaveCount(1);
  await expect(field).toHaveAttribute('data-state', 'base');

  writeDestinationEvidence('destination-r9r10-geometry.json', {
    initial: { field: initialField, search: initialSearch, add: initialAdd },
    oneChip,
    desktopTwoExpanded,
    desktopFive,
    desktopFiveReorder: { before: fiveInitial, mouse: fullMouseOrder, keyboard: fullKeyboardOrder },
    mobileFive,
    mobileCrossRowMouse: { order: crossRowMouse, sourceRow, targetRow },
  });
  expectCleanFixture(fixture);
});

test('关闭新增后延迟候选不会重新展开', async ({ page }) => {
  const fixture = await openHome(page, { width: 1440, height: 900 });
  await page.getByRole('tab', { name: '按条件规划' }).click();
  const skip = page.getByRole('button', { name: '暂时不用默认值', exact: true });
  if (await skip.count()) await skip.click();
  const add = page.getByTestId('add-destination');
  const search = () => page.locator('.destination-search input');
  const candidates = page.getByTestId('destination-candidates');

  await search().fill('苏州');
  await candidates.getByRole('button').filter({ hasText: '苏州' }).first().click();
  await expect(page.getByTestId('destination-token-0')).toContainText('苏州');
  await expect(search()).toHaveCount(0);

  await add.click();
  let releaseDelay: (() => void) | null = null;
  const delay = new Promise<void>((resolve) => { releaseDelay = resolve; });
  let delayed = false;
  let delayedStarted = false;
  await page.route('**/api/places/search**', async (route) => {
    if (!delayed) return route.fallback();
    delayed = false;
    delayedStarted = true;
    const query = new URL(route.request().url()).searchParams.get('q') || '杭州';
    const name = query.replace(/[市\s]/g, '') || '杭州';
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
  });

  delayed = true;
  await search().fill('杭州');
  await expect.poll(() => delayedStarted).toBe(true);
  await add.click();
  await expect(search()).toHaveCount(0);
  releaseDelay?.();
  await page.waitForTimeout(600);
  await expect(candidates).toHaveCount(0);
  await expect(search()).toHaveCount(0);
  await expect(page.locator('.destination-token')).toHaveCount(1);

  await add.click();
  await search().fill('杭州');
  await candidates.getByRole('button').filter({ hasText: '杭州' }).first().click();
  await expect(page.getByTestId('destination-token-1')).toContainText('杭州');
  expectCleanFixture(fixture);
});

async function openPlannerCalendar(page: Page) {
  await page.getByRole('tab', { name: '按条件规划' }).click();
  const skip = page.getByRole('button', { name: '暂时不用默认值', exact: true });
  if (await skip.count()) await skip.click();
  await expect(page.getByRole('textbox', { name: '从哪里出发' })).toBeVisible();
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
  expect(await today.evaluate((element) => getComputedStyle(element).boxShadow)).not.toBe('none');
  expect(await today.evaluate((element) => getComputedStyle(element).boxShadow)).toContain('inset');
  await expect(past).toBeDisabled();
  await expect(past).toHaveCSS('opacity', '0.42');
  await expect(calendarDay(page, '2026-10-01')).toBeDisabled();

  await past.evaluate((element) => (element as HTMLButtonElement).click());
  await expect(trigger).toHaveAttribute('aria-label', '选择开始日期 → 选择结束日期');
  await page.screenshot({ path: '../output/polish/20261029-1207-calendar-date-limits/calendar-desktop-today.png' });

  await today.click();
  await expect(today).toHaveAttribute('aria-pressed', 'true');
  await expect(calendarDay(page, '2026-11-11')).toBeEnabled();
  await expect(calendarDay(page, '2026-11-12')).toBeDisabled();
  await expect(calendarDay(page, '2026-11-12')).toHaveCSS('opacity', '0.42');
  await calendarDay(page, '2026-11-12').evaluate((element) => (element as HTMLButtonElement).click());
  await expect(trigger).toHaveAttribute('aria-label', '2026-10-29 → 选择结束日期');
  await page.waitForTimeout(250);
  await page.screenshot({ path: '../output/polish/20261029-1207-calendar-date-limits/calendar-desktop-14-day-boundary.png' });

  await calendarDay(page, '2026-11-11').click();
  await expect(trigger).toHaveAttribute('aria-label', '2026-10-29 → 2026-11-11 · 14 天 13 晚');
  await expect(dialog.getByRole('button', { name: '确认日期 · 14 天 13 晚', exact: true })).toBeEnabled();

  await dialog.getByRole('button', { name: '清除日期', exact: true }).click();
  await expect(trigger).toHaveAttribute('aria-label', '选择开始日期 → 选择结束日期');
  await expect(calendarDay(page, '2026-10-28')).toBeDisabled();
  await today.click();
  await today.click();
  await expect(trigger).toHaveAttribute('aria-label', '2026-10-29 → 2026-10-29 · 1 天 0 晚');
  await expect(dialog.getByRole('button', { name: '确认日期 · 1 天 0 晚', exact: true })).toBeEnabled();

  await dialog.getByRole('button', { name: '下个月', exact: true }).click();
  await calendarDay(page, '2026-11-20').click();
  await expect(trigger).toHaveAttribute('aria-label', '2026-11-20 → 选择结束日期');
  await calendarDay(page, '2026-11-05').click();
  await expect(trigger).toHaveAttribute('aria-label', '2026-11-05 → 选择结束日期');
  await page.getByRole('button', { name: '关闭日期选择', exact: true }).click();
  await expect(dialog).toBeHidden();
  await trigger.click();
  await expect(page.getByRole('heading', { name: '2026 年 11 月', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '2027 年 1 月', exact: true })).toBeHidden();

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
  await expect(trigger).toHaveAttribute('aria-label', '2026-12-25 → 2027-01-07 · 14 天 13 晚');

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
    await expect(page.getByTestId('date-range-trigger')).toHaveAttribute('aria-label', '2027-03-10 → 2027-03-23 · 14 天 13 晚');
    expectCleanFixture(fixture);
  });
});

test('移动端单月显示今天与 14 天禁用边界', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-10-29T10:00:00+08:00'));
  const fixture = await openHome(page, { width: 390, height: 844 });
  const dialog = await openPlannerCalendar(page);
  const today = calendarDay(page, '2026-10-29');

  await expect(page.getByRole('heading', { name: '2026 年 10 月', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '2026 年 11 月', exact: true })).toBeHidden();
  await expect(today).toHaveAttribute('aria-current', 'date');
  await expect(calendarDay(page, '2026-10-28')).toBeDisabled();
  await page.screenshot({ path: '../output/polish/20261029-1207-calendar-date-limits/calendar-mobile-today.png' });

  await today.click();
  await dialog.getByRole('button', { name: '下个月', exact: true }).click();
  await expect(page.getByRole('heading', { name: '2026 年 11 月', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '2026 年 12 月', exact: true })).toBeHidden();
  await expect(calendarDay(page, '2026-11-11')).toBeEnabled();
  await expect(calendarDay(page, '2026-11-12')).toBeDisabled();
  await page.waitForTimeout(250);
  await page.screenshot({ path: '../output/polish/20261029-1207-calendar-date-limits/calendar-mobile-14-day-boundary.png' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expectCleanFixture(fixture);
});

test('390px 真实触摸可滚动页面并通过把手同排与跨行排序', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  const fixture = await openHome(page, { width: 390, height: 844 });
  await page.getByRole('tab', { name: '按条件规划' }).click();
  const skip = page.getByRole('button', { name: '暂时不用默认值', exact: true });
  if (await skip.count()) await skip.click();

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
  const firstAgain = (await page.getByTestId('destination-token-0').boundingBox())!;
  const secondAgain = (await page.getByTestId('destination-token-1').boundingBox())!;
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
  await touch('touchStart', firstAgain.x + 14, firstAgain.y + firstAgain.height / 2);
  await touch('touchMove', firstAgain.x + 14, firstAgain.y - 80);
  await touch('touchMove', firstAgain.x + 14, firstAgain.y - 150);
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
  const handle = (await page.getByTestId('destination-token-0').locator('.destination-token-drag').boundingBox())!;
  const secondAfterScroll = (await page.getByTestId('destination-token-1').boundingBox())!;
  await touch('touchStart', handle.x + handle.width / 2, handle.y + handle.height / 2);
  await expect(page.getByTestId('destination-token-0')).toHaveClass(/is-dragging/);
  const sameRowTarget = { x: secondAfterScroll.x + secondAfterScroll.width / 2, y: secondAfterScroll.y + secondAfterScroll.height / 2 };
  for (const ratio of [0.25, 0.5, 0.75, 1]) {
    await touch('touchMove', handle.x + handle.width / 2 + (sameRowTarget.x - handle.x - handle.width / 2) * ratio, sameRowTarget.y);
  }
  await expect(page.getByTestId('destination-token-1')).toHaveClass(/is-drop-target/);
  await page.waitForTimeout(60);
  await touch('touchEnd');
  await expect(page.getByTestId('destination-token-0')).toContainText('杭州');
  await expect(page.getByTestId('destination-token-1')).toContainText('苏州');
  const sameRowTouchOrder = await page.locator('.destination-token-name').allTextContents();
  expect(sameRowTouchOrder).toEqual(['杭州', '苏州']);
  await page.screenshot({ path: '../output/polish/20261029-1252-destination-tokens/destination-r9r10-390-touch-two-reorder.png', fullPage: true });

  for (const name of ['南京', '宁波', '绍兴']) await choose(name, false);
  await expect(page.locator('.destination-token')).toHaveCount(5);
  await expect(page.locator('.destination-search')).toHaveCount(0);
  await expect(page.getByTestId('add-destination')).toHaveText('目的地到达上限');
  await expect(page.getByTestId('add-destination')).toBeDisabled();
  expect(await page.locator('.destination-token-name').allTextContents()).toEqual(['杭州', '苏州', '南京', '宁波', '绍兴']);

  await page.getByTestId('destination-token-0').scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  const fullHandle = (await page.getByTestId('destination-token-0').locator('.destination-token-drag').boundingBox())!;
  const fullFirst = (await page.getByTestId('destination-token-0').boundingBox())!;
  const fullFourth = (await page.getByTestId('destination-token-3').boundingBox())!;
  expect(fullFourth.y).toBeGreaterThan(fullFirst.y + fullFirst.height / 2);
  await touch('touchStart', fullHandle.x + fullHandle.width / 2, fullHandle.y + fullHandle.height / 2);
  await expect(page.getByTestId('destination-token-0')).toHaveClass(/is-dragging/);
  const crossRowTarget = { x: fullHandle.x + fullHandle.width / 2, y: fullFourth.y + fullFourth.height / 2 };
  for (const ratio of [0.25, 0.5, 0.75, 1]) {
    await touch('touchMove', crossRowTarget.x, fullHandle.y + fullHandle.height / 2 + (crossRowTarget.y - fullHandle.y - fullHandle.height / 2) * ratio);
  }
  await expect(page.getByTestId('destination-token-3')).toHaveClass(/is-drop-target/);
  await page.waitForTimeout(60);
  await touch('touchEnd');
  const crossRowTouchOrder = await page.locator('.destination-token-name').allTextContents();
  expect(crossRowTouchOrder).toEqual(['苏州', '南京', '宁波', '杭州', '绍兴']);
  writeDestinationEvidence('destination-r9r10-touch-orders.json', {
    sameRow: sameRowTouchOrder,
    crossRow: crossRowTouchOrder,
    crossRowFrom: fullFirst,
    crossRowTarget: fullFourth,
  });
  await page.screenshot({ path: '../output/polish/20261029-1252-destination-tokens/destination-r9r10-390-touch-five-cross-row.png', fullPage: true });

  expectCleanFixture(fixture);
  await context.close();
});

test('目的地候选在 Escape、外部操作和切换模式后收起且旧搜索不重开', async ({ page }) => {
  const fixture = await openHome(page, { width: 1440, height: 900 });
  await page.getByRole('tab', { name: '按条件规划' }).click();
  const skip = page.getByRole('button', { name: '暂时不用默认值', exact: true });
  if (await skip.count()) await skip.click();
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

  await input.fill('');
  await input.fill('苏州');
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
