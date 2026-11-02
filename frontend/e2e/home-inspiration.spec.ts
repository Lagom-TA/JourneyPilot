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
  const directory = '../test-results/e2e-evidence/destination-tokens';
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
  const budgetInput = page.getByLabel('预算（可选）');
  await expect(budgetInput).toHaveAttribute('type', 'text');
  await expect(budgetInput).toHaveAttribute('inputmode', 'decimal');
  await expect(budgetInput).not.toHaveAttribute('min');
  await budgetInput.fill('4567');
  await page.getByRole('button', { name: '增加成人' }).click();
  await naturalTab.click();
  await structuredTab.click();
  await expect(origin).toHaveValue('深');
  await expect(page.getByLabel('预算（可选）')).toHaveValue('4567');
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
  await expect(page.getByLabel('预算（可选）')).toHaveValue('8000');
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
    await page.screenshot({ path: `../test-results/e2e-evidence/home-action-layout/home-${viewport.width}-structured.png`, fullPage: true });
    await page.screenshot({ path: `../test-results/e2e-evidence/home-form-rhythm/home-${viewport.width}-structured.png`, fullPage: true });

    await naturalTab.click();
    await expect(naturalInput).toHaveValue('想从深圳去杭州，轻松玩几天。');
    await expect(page.locator('.planner-panel-structured')).toHaveAttribute('inert', '');
    if (viewport.width === 390) await planner.evaluate((element) => element.scrollIntoView({ block: 'nearest' }));
    const natural = await plannerGeometry(page);
    await page.screenshot({ path: `../test-results/e2e-evidence/home-action-layout/home-${viewport.width}-natural.png`, fullPage: true });
    await page.screenshot({ path: `../test-results/e2e-evidence/home-form-rhythm/home-${viewport.width}-natural.png`, fullPage: true });

    expectStablePlannerGeometry(natural, structured);
    expect(natural.card.bottom - natural.action!.bottom).toBeGreaterThan(10);
    expect(natural.card.bottom - natural.action!.bottom).toBeLessThan(28);
    expect(structured.card.bottom - structured.action!.bottom).toBeGreaterThan(10);
    expect(structured.card.bottom - structured.action!.bottom).toBeLessThan(28);
    expect(natural.activePanel!.bottom).toBeLessThanOrEqual(natural.action!.y + 1);
    expect(structured.activePanel!.bottom).toBeLessThanOrEqual(structured.action!.y + 1);

    expect(styleOptions).not.toBeNull();
    expect(budget).not.toBeNull();
    const dateTrigger = await page.getByTestId('date-range-trigger').boundingBox();
    const party = await page.locator('.planner-party').boundingBox();
    if (viewport.width >= 1024) {
      expect(dateTrigger).not.toBeNull();
      expect(party).not.toBeNull();
      expect(Math.abs(dateTrigger!.y - party!.y)).toBeLessThan(8);
      expect(Math.abs(dateTrigger!.y - budget!.y)).toBeLessThan(8);
      expect(Math.abs(budget!.y - dateTrigger!.y)).toBeLessThan(5);
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
      await page.screenshot({ path: '../test-results/e2e-evidence/home-action-layout/home-2000-more-preferences.png', fullPage: true });
      await page.screenshot({ path: '../test-results/e2e-evidence/home-form-rhythm/home-2000-more-preferences.png', fullPage: true });
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
  await page.screenshot({ path: '../test-results/e2e-evidence/destination-tokens/destination-r9r10-2000-initial.png', fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(250);
  await page.screenshot({ path: '../test-results/e2e-evidence/destination-tokens/destination-r9r10-390-initial.png', fullPage: true });
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
    const handle = (await page.getByTestId(`destination-token-${from}`).boundingBox())!;
    const target = (await page.getByTestId(`destination-token-${to}`).boundingBox())!;
    await page.mouse.move(handle.x + 10, handle.y + handle.height / 2);
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
  await page.screenshot({ path: '../test-results/e2e-evidence/destination-tokens/destination-r9r10-2000-two-expanded.png', fullPage: true });

  await add.click();
  await expect(search()).toHaveCount(0);
  await expect(tokens).toHaveCount(2);
  await expect(add).toHaveText('新增目的地');
  await expect(add).toBeFocused();
  await page.screenshot({ path: '../test-results/e2e-evidence/destination-tokens/destination-r9r10-2000-two-collapsed.png', fullPage: true });

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
  await page.screenshot({ path: '../test-results/e2e-evidence/destination-tokens/destination-r9r10-2000-five-limit.png', fullPage: true });

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
  await page.screenshot({ path: '../test-results/e2e-evidence/destination-tokens/destination-r9r10-390-five-limit.png', fullPage: true });

  const sourceRow = mobileFive.rows[0];
  const targetRow = mobileFive.rows[3];
  expect(targetRow.top).toBeGreaterThan(sourceRow.top + sourceRow.height / 2);
  await dragToken(0, 3);
  const crossRowMouse = await page.locator('.destination-token-name').allTextContents();
  expect(crossRowMouse).toEqual(['苏州', '南京', '宁波', '杭州', '绍兴']);
  await page.screenshot({ path: '../test-results/e2e-evidence/destination-tokens/destination-r9r10-390-mouse-cross-row.png', fullPage: true });

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
  await page.screenshot({ path: '../test-results/e2e-evidence/destination-tokens/destination-r9r10-390-zero.png', fullPage: true });

  await choose('苏州', false);
  await add.click();
  await choose('杭州');
  await expect(tokens).toHaveCount(2);
  await expect(search()).toBeVisible();
  await page.screenshot({ path: '../test-results/e2e-evidence/destination-tokens/destination-r9r10-390-two-expanded.png', fullPage: true });
  await add.click();
  await expect(search()).toHaveCount(0);
  await page.screenshot({ path: '../test-results/e2e-evidence/destination-tokens/destination-r9r10-390-two-collapsed.png', fullPage: true });
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
  await expect(trigger).toHaveAttribute('aria-label', '旅行日期：开始日期 → 结束日期');
  await page.screenshot({ path: '../test-results/e2e-evidence/calendar-date-limits/calendar-desktop-today.png' });

  await today.click();
  await expect(today).toHaveAttribute('aria-pressed', 'true');
  await expect(calendarDay(page, '2026-11-11')).toBeEnabled();
  await expect(calendarDay(page, '2026-11-12')).toBeDisabled();
  await expect(calendarDay(page, '2026-11-12')).toHaveCSS('opacity', '0.42');
  await calendarDay(page, '2026-11-12').evaluate((element) => (element as HTMLButtonElement).click());
  await expect(trigger).toHaveAttribute('aria-label', '旅行日期：2026-10-29 → 结束日期');
  await page.waitForTimeout(250);
  await page.screenshot({ path: '../test-results/e2e-evidence/calendar-date-limits/calendar-desktop-14-day-boundary.png' });

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

test('移动端单月显示今天与 14 天禁用边界', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-10-29T10:00:00+08:00'));
  const fixture = await openHome(page, { width: 390, height: 844 });
  const dialog = await openPlannerCalendar(page);
  const today = calendarDay(page, '2026-10-29');

  await expect(page.getByRole('heading', { name: '2026 年 10 月', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '2026 年 11 月', exact: true })).toBeHidden();
  await expect(today).toHaveAttribute('aria-current', 'date');
  await expect(calendarDay(page, '2026-10-28')).toBeDisabled();
  await page.screenshot({ path: '../test-results/e2e-evidence/calendar-date-limits/calendar-mobile-today.png' });

  await today.click();
  await dialog.getByRole('button', { name: '下个月', exact: true }).click();
  await expect(page.getByRole('heading', { name: '2026 年 11 月', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '2026 年 12 月', exact: true })).toBeHidden();
  await expect(calendarDay(page, '2026-11-11')).toBeEnabled();
  await expect(calendarDay(page, '2026-11-12')).toBeDisabled();
  await page.waitForTimeout(250);
  await page.screenshot({ path: '../test-results/e2e-evidence/calendar-date-limits/calendar-mobile-14-day-boundary.png' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expectCleanFixture(fixture);
});

test('390px 真实触摸可从非排序区滚动并按住目的地同排与跨行排序', async ({ browser }) => {
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
  await page.screenshot({ path: '../test-results/e2e-evidence/destination-tokens/destination-r9r10-390-touch-two-reorder.png', fullPage: true });

  for (const name of ['南京', '宁波', '绍兴']) await choose(name, false);
  await expect(page.locator('.destination-token')).toHaveCount(5);
  await expect(page.locator('.destination-search')).toHaveCount(0);
  await expect(page.getByTestId('add-destination')).toHaveText('目的地到达上限');
  await expect(page.getByTestId('add-destination')).toBeDisabled();
  expect(await page.locator('.destination-token-name').allTextContents()).toEqual(['杭州', '苏州', '南京', '宁波', '绍兴']);

  await page.getByTestId('destination-token-0').scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  const fullHandle = (await page.getByTestId('destination-token-0').boundingBox())!;
  const fullFirst = (await page.getByTestId('destination-token-0').boundingBox())!;
  const fullFourth = (await page.getByTestId('destination-token-3').boundingBox())!;
  expect(fullFourth.y).toBeGreaterThan(fullFirst.y + fullFirst.height / 2);
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
  expect(crossRowTouchOrder).toEqual(['苏州', '南京', '宁波', '杭州', '绍兴']);
  mkdirSync('../test-results/e2e-evidence/home-form-compact', { recursive: true });
  writeFileSync('../test-results/e2e-evidence/home-form-compact/touch-orders.json', JSON.stringify({ sameRow: sameRowTouchOrder, crossRow: crossRowTouchOrder }, null, 2));
  writeDestinationEvidence('destination-r9r10-touch-orders.json', {
    sameRow: sameRowTouchOrder,
    crossRow: crossRowTouchOrder,
    crossRowFrom: fullFirst,
    crossRowTarget: fullFourth,
  });
  await page.screenshot({ path: '../test-results/e2e-evidence/destination-tokens/destination-r9r10-390-touch-five-cross-row.png', fullPage: true });

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

test('首页紧凑条件表单、开关首排与控件同行 2000px/1440px/390px', async ({ browser }) => {
  const evidence = '../test-results/e2e-evidence/home-form-compact';
  mkdirSync(evidence, { recursive: true });
  const geometry: Record<string, unknown> = {};
  for (const viewport of [{ width: 2000, height: 880 }, { width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    const fixture = await openHome(page, viewport);
    await page.getByRole('tab', { name: '按条件规划' }).click();
    const skip = page.getByRole('button', { name: '暂时不用默认值', exact: true });
    if (await skip.count()) await skip.click();
    const add = page.getByTestId('add-destination');
    const search = () => page.locator('.destination-search input');
    const candidates = page.getByTestId('destination-candidates');
    const choose = async (name: string) => {
      if (await search().count() === 0) await add.click();
      await search().fill(name);
      await candidates.getByRole('button').filter({ hasText: name }).first().click();
    };

    await expect(page.getByText('精确日期', { exact: true })).toHaveCount(0);
    await expect(page.locator('.planner-panel-structured').getByText('同行', { exact: true })).toHaveCount(0);
    await expect(page.getByTestId('date-range-trigger')).toContainText('开始日期');
    await expect(page.getByTestId('date-range-trigger')).toContainText('结束日期');
    await expect(page.getByLabel('预算（可选）')).toHaveAttribute('placeholder', '预算（可选）');
    await expect(page.locator('.destination-token-drag')).toHaveCount(0);
    await expect(page.locator('.destination-token-sort-hint')).toHaveCount(0);
    for (const name of ['北京', '上海', '长春']) await choose(name);
    await expect(page.locator('.destination-token')).toHaveCount(3);
    await expect(add).toHaveText('关闭新增');
    const token0 = (await page.getByTestId('destination-token-0').boundingBox())!;
    const addBox = (await add.boundingBox())!;
    expect(addBox.y).toBeLessThanOrEqual(token0.y + 8);
    expect(addBox.y + addBox.height).toBeLessThanOrEqual(token0.y + token0.height + 8);
    const dateBox = (await page.getByTestId('date-range-trigger').boundingBox())!;
    const partyBox = (await page.locator('.planner-party').boundingBox())!;
    const budgetBox = (await page.locator('.planner-budget-input').boundingBox())!;
    if (viewport.width >= 1024) {
      expect(Math.abs(dateBox.y - partyBox.y)).toBeLessThan(8);
      expect(Math.abs(dateBox.y - budgetBox.y)).toBeLessThan(8);
      expect(dateBox.width).toBeLessThanOrEqual(340);
      expect(budgetBox.width).toBeLessThanOrEqual(150);
    } else {
      expect(dateBox.width).toBeLessThanOrEqual(viewport.width - 32);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `${evidence}/home-${viewport.width}-three-expanded.png`, fullPage: true });

    if (viewport.width === 390) {
      await page.getByRole('button', { name: '更多偏好' }).click();
      await page.screenshot({ path: `${evidence}/home-390-three-more-preferences.png`, fullPage: true });
    }
    await choose('南京');
    await choose('杭州');
    await expect(page.locator('.destination-token')).toHaveCount(5);
    await expect(add).toHaveText('目的地到达上限');
    const fiveToken0 = (await page.getByTestId('destination-token-0').boundingBox())!;
    const fiveAdd = (await add.boundingBox())!;
    expect(fiveAdd.y).toBeLessThanOrEqual(fiveToken0.y + 8);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `${evidence}/home-${viewport.width}-five-limit.png`, fullPage: true });

    for (let index = 0; index < 5; index += 1) {
      await page.locator('.destination-token').last().focus();
      await page.locator('.destination-token').last().press('Delete');
    }
    await expect(page.locator('.destination-token')).toHaveCount(0);
    await expect(search()).toBeVisible();
    await page.screenshot({ path: `${evidence}/home-${viewport.width}-zero.png`, fullPage: true });
    geometry[viewport.width] = {
      token0,
      add: addBox,
      fiveToken0,
      fiveAdd,
      date: dateBox,
      party: partyBox,
      budget: budgetBox,
      overflow: await page.evaluate(() => document.documentElement.scrollWidth - innerWidth),
    };
    expectCleanFixture(fixture);
    await context.close();
  }
  writeFileSync(`${evidence}/geometry.json`, JSON.stringify(geometry, null, 2));
});

// ---- 多目的地展开稳定性（20261031-1130-home-destination-stability） ----

const destinationStabilityEvidence = '../test-results/e2e-evidence/home-destination-stability';

type StabilityRect = { x: number; y: number; width: number; height: number; bottom: number; right: number };

type StabilityGeometry = {
  viewport: { width: number; height: number };
  card: StabilityRect;
  action: StabilityRect;
  date: StabilityRect | null;
  party: StabilityRect | null;
  budget: StabilityRect | null;
  route: StabilityRect;
  panel: StabilityRect;
  form: StabilityRect;
  prefs: StabilityRect;
  search: StabilityRect | null;
  tokenRows: StabilityRect[];
  fieldState: string | null;
  searchInputs: number;
  scroll: { window: number; hero: number; main: number };
  overflowX: number;
};

async function enterStructuredWithOrigin(page: Page) {
  await page.getByRole('tab', { name: '按条件规划' }).click();
  const skip = page.getByRole('button', { name: '暂时不用默认值', exact: true });
  const origin = page.getByRole('textbox', { name: '从哪里出发' });
  await expect(origin.or(skip).first()).toBeVisible();
  if (await skip.isVisible().catch(() => false)) await skip.click();
  await expect(origin).toBeVisible();
}

async function chooseDestinations(page: Page, names: readonly string[]) {
  const add = page.getByTestId('add-destination');
  for (const name of names) {
    if (await page.locator('.destination-search input').count() === 0) await add.click();
    const search = page.locator('.destination-search input');
    await expect(search).toHaveCount(1);
    await search.fill(name);
    await page.getByTestId('destination-candidates').getByRole('button').filter({ hasText: name }).first().click();
    await expect(page.locator('.destination-token-name').filter({ hasText: name })).toHaveCount(1);
  }
}

async function closeDestinationsAdd(page: Page) {
  const add = page.getByTestId('add-destination');
  if (await add.getAttribute('data-state') === 'open') await add.click();
  await expect(page.getByTestId('destination-token-field')).toHaveAttribute('data-state', 'closed');
  await page.waitForTimeout(320);
}

async function settlePlannerScroll(page: Page) {
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    window.scrollTo(0, 0);
    for (const selector of ['.new-trip-hero', '.new-trip-main']) {
      const node = document.querySelector<HTMLElement>(selector);
      if (node) node.scrollTop = 0;
    }
  });
  await page.waitForTimeout(120);
}

async function stabilityGeometry(page: Page): Promise<StabilityGeometry> {
  return page.evaluate(() => {
    const rect = (element: Element | null): StabilityRect | null => {
      if (!element) return null;
      const box = element.getBoundingClientRect();
      const round = (value: number) => Math.round(value * 100) / 100;
      return {
        x: round(box.x + scrollX),
        y: round(box.y + scrollY),
        width: round(box.width),
        height: round(box.height),
        bottom: round(box.bottom + scrollY),
        right: round(box.right + scrollX),
      };
    };
    const pick = (selector: string) => rect(document.querySelector(selector));
    const card = pick('.new-trip-content > .planner-card');
    const action = pick('.planner-action-area .planner-main-action');
    const route = pick('.planner-route-fields');
    const panel = pick('.planner-panel-structured');
    const form = pick('.planner-form-grid');
    const prefs = pick('.planner-preference-block');
    if (!card || !action || !route || !panel || !form || !prefs) throw new Error('planner geometry missing');
    return {
      viewport: { width: innerWidth, height: innerHeight },
      card,
      action,
      date: pick('[data-testid="date-range-trigger"]'),
      party: pick('.planner-party'),
      budget: pick('.planner-budget-input'),
      route,
      panel,
      form,
      prefs,
      search: pick('.destination-add-panel'),
      tokenRows: Array.from(document.querySelectorAll('.destination-token')).map((element) => rect(element)!),
      fieldState: document.querySelector('[data-testid="destination-token-field"]')?.getAttribute('data-state') ?? null,
      searchInputs: document.querySelectorAll('.destination-search input').length,
      scroll: {
        window: window.scrollY,
        hero: (document.querySelector('.new-trip-hero') as HTMLElement | null)?.scrollTop ?? 0,
        main: (document.querySelector('.new-trip-main') as HTMLElement | null)?.scrollTop ?? 0,
      },
      overflowX: document.documentElement.scrollWidth - innerWidth,
    };
  });
}

function expectSameRect(before: StabilityRect, after: StabilityRect, label: string) {
  for (const key of ['x', 'y', 'width', 'height', 'bottom', 'right'] as const) {
    expect(Math.abs(before[key] - after[key]), `${label}.${key}`).toBeLessThan(2);
  }
}

function expectStablePlannerFrame(before: StabilityGeometry, after: StabilityGeometry, label: string) {
  expectSameRect(before.card, after.card, `${label} card`);
  expectSameRect(before.action, after.action, `${label} action`);
  expect(after.scroll.window).toBe(0);
  expect(after.scroll.hero).toBe(0);
  expect(after.scroll.main).toBe(0);
  expect(after.overflowX).toBeLessThanOrEqual(0);
}

async function readTransitionDurations(page: Page) {
  return page.evaluate(() => {
    const duration = (selector: string) => {
      const element = document.querySelector(selector);
      return element ? getComputedStyle(element).transitionDuration : null;
    };
    return {
      search: duration('.destination-add-panel'),
      form: duration('.planner-form-grid'),
      panel: duration('.planner-panel-structured'),
    };
  });
}

async function recordTransitionFrames(page: Page, actionSelector: string) {
  return page.evaluate(async (selector) => {
    type Frame = {
      t: number;
      card: { top: number; height: number } | null;
      action: { top: number; height: number } | null;
      form: { top: number } | null;
      prefs: { top: number } | null;
      search: { top: number; height: number } | null;
    };
    const win = window as unknown as { __stabilityFrames?: Frame[]; __stabilityStop?: boolean };
    win.__stabilityFrames = [];
    win.__stabilityStop = false;
    const box = (query: string) => document.querySelector(query)?.getBoundingClientRect() ?? null;
    const started = performance.now();
    const sample = () => {
      if (win.__stabilityStop) return;
      const card = box('.new-trip-content > .planner-card');
      const action = box('.planner-action-area .planner-main-action');
      const form = box('.planner-form-grid');
      const prefs = box('.planner-preference-block');
      const search = box('.destination-add-panel');
      win.__stabilityFrames!.push({
        t: Math.round(performance.now() - started),
        card: card ? { top: card.top, height: card.height } : null,
        action: action ? { top: action.top, height: action.height } : null,
        form: form ? { top: form.top } : null,
        prefs: prefs ? { top: prefs.top } : null,
        search: search ? { top: search.top, height: search.height } : null,
      });
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
    (document.querySelector(selector) as HTMLElement | null)?.click();
    await new Promise((resolve) => setTimeout(resolve, 450));
    win.__stabilityStop = true;
    return win.__stabilityFrames!;
  }, actionSelector);
}

function summarizeFrames(frames: Array<{ card: { top: number; height: number } | null; action: { top: number; height: number } | null; form: { top: number } | null; prefs: { top: number } | null; search: { top: number; height: number } | null }>) {
  const values = (pick: (frame: (typeof frames)[number]) => number | undefined) => frames.map(pick).filter((value): value is number => typeof value === 'number');
  const range = (list: number[]) => [Math.min(...list), Math.max(...list)];
  const cardTops = values((frame) => frame.card?.top);
  const cardHeights = values((frame) => frame.card?.height);
  const actionTops = values((frame) => frame.action?.top);
  const actionHeights = values((frame) => frame.action?.height);
  const overlapSearchForm = frames.filter((frame) => frame.search && frame.form && frame.search.height > 1 && frame.form.top < frame.search.top + frame.search.height - 0.5).length;
  const prefsAboveForm = frames.filter((frame) => frame.prefs && frame.form && frame.prefs.top < frame.form.top - 0.5).length;
  const movingForms = values((frame) => frame.form?.top);
  return {
    frames: frames.length,
    cardTopRange: range(cardTops),
    cardHeightRange: range(cardHeights),
    actionTopRange: range(actionTops),
    actionHeightRange: range(actionHeights),
    formTopRange: range(movingForms),
    overlapSearchForm,
    prefsAboveForm,
  };
}

test('多目的地展开保持规划卡稳定', async ({ browser }) => {
  test.setTimeout(240_000);
  mkdirSync(destinationStabilityEvidence, { recursive: true });
  const report: Record<string, unknown> = {
    fixture: 'home-inspiration local /api fixture; no real API, place service or model calls',
    viewports: {} as Record<string, unknown>,
    wrap: {} as Record<string, unknown>,
    fiveAndZero: {} as Record<string, unknown>,
    contentGrowth: {} as Record<string, unknown>,
    animation: {} as Record<string, unknown>,
    reducedMotion: {} as Record<string, unknown>,
  };
  const viewports = [
    { width: 2000, height: 880 },
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ] as const;
  const counts = [1, 3, 4] as const;

  for (const viewport of viewports) {
    for (const count of counts) {
      const context = await browser.newContext({ viewport });
      const page = await context.newPage();
      const fixture = await openHome(page, viewport);
      await enterStructuredWithOrigin(page);
      const names = ['北京', '上海', '长春', '南京'].slice(0, count);
      await chooseDestinations(page, names);
      await closeDestinationsAdd(page);
      await settlePlannerScroll(page);
      const closed = await stabilityGeometry(page);
      expect(closed.fieldState).toBe('closed');
      expect(closed.searchInputs).toBe(0);

      if (count === 3 && (viewport.width === 2000 || viewport.width === 390)) {
        await page.screenshot({ path: `${destinationStabilityEvidence}/home-${viewport.width}-three-collapsed.png`, fullPage: true });
        await page.locator('.new-trip-content > .planner-card').screenshot({ path: `${destinationStabilityEvidence}/home-${viewport.width}-three-collapsed-card.png` });
      }

      const add = page.getByTestId('add-destination');
      await add.click();
      await expect(page.locator('.destination-search input')).toBeVisible();
      await page.waitForTimeout(320);
      await settlePlannerScroll(page);
      const open = await stabilityGeometry(page);
      expect(open.fieldState).toBe('open');
      expect(open.searchInputs).toBe(1);
      expectStablePlannerFrame(closed, open, `${viewport.width}x${viewport.height} ${count} station`);
      expect(open.form.y - closed.form.y).toBeGreaterThan(8);
      expect(open.prefs.y - closed.prefs.y).toBeGreaterThan(8);
      expect(Math.abs((open.form.y - closed.form.y) - (open.prefs.y - closed.prefs.y))).toBeLessThan(1);
      expect(open.search).not.toBeNull();
      expect(open.search!.height).toBeGreaterThan(40);
      expect(open.search!.y).toBeGreaterThanOrEqual(Math.max(...open.tokenRows.map((row) => row.bottom)) - 1);
      expect(open.form.y).toBeGreaterThanOrEqual(open.search!.bottom - 1);
      expect(open.prefs.y).toBeGreaterThanOrEqual(open.form.bottom - 1);
      expect(open.action.y).toBeGreaterThanOrEqual(open.prefs.bottom - 1);
      expect(closed.search?.height ?? 0).toBeLessThan(1);
      expect(closed.form.y).toBeGreaterThanOrEqual(closed.route.bottom);
      expect(closed.action.y - closed.prefs.bottom).toBeLessThanOrEqual(56);
      expect(closed.form.y - closed.route.bottom).toBeLessThanOrEqual(56);

      const rows = new Set(open.tokenRows.map((row) => Math.round(row.y)));
      if (viewport.width === 390 && count >= 3) {
        expect(rows.size).toBeGreaterThanOrEqual(2);
        (report.wrap as Record<string, unknown>)[`${viewport.width}x${viewport.height}-${count}`] = {
          rows: open.tokenRows,
          rowTops: Array.from(rows),
          tokenColumnWidth: open.route.width,
        };
      }
      if (count === 3 && (viewport.width === 2000 || viewport.width === 390)) {
        await page.screenshot({ path: `${destinationStabilityEvidence}/home-${viewport.width}-three-expanded.png`, fullPage: true });
        await page.locator('.new-trip-content > .planner-card').screenshot({ path: `${destinationStabilityEvidence}/home-${viewport.width}-three-expanded-card.png` });
      }

      await add.click();
      await expect(page.getByTestId('destination-token-field')).toHaveAttribute('data-state', 'closed');
      await page.waitForTimeout(320);
      await settlePlannerScroll(page);
      const closedAgain = await stabilityGeometry(page);
      expectStablePlannerFrame(closed, closedAgain, `${viewport.width}x${viewport.height} ${count} station close`);
      expect(closedAgain.searchInputs).toBe(0);

      const naturalInput = page.getByTestId('natural-trip-input');
      await page.getByRole('tab', { name: '一句话规划' }).click();
      await expect(naturalInput).toBeVisible();
      await naturalInput.fill('想从北京去上海，轻松玩五天。');
      await page.waitForTimeout(320);
      await settlePlannerScroll(page);
      const natural = await stabilityGeometry(page);
      expectStablePlannerFrame(closed, natural, `${viewport.width}x${viewport.height} ${count} station natural mode`);
      await page.getByRole('tab', { name: '按条件规划' }).click();
      await expect(naturalInput).toHaveValue('想从北京去上海，轻松玩五天。');
      await expect(page.locator('.destination-token')).toHaveCount(count);

      (report.viewports as Record<string, unknown>)[`${viewport.width}x${viewport.height}-${count}`] = {
        closed,
        open,
        closedAgain,
        natural,
        movements: {
          form: Math.round((open.form.y - closed.form.y) * 100) / 100,
          prefs: Math.round((open.prefs.y - closed.prefs.y) * 100) / 100,
          closedTopGap: Math.round((closed.form.y - closed.route.bottom) * 100) / 100,
          closedBottomGap: Math.round((closed.action.y - closed.prefs.bottom) * 100) / 100,
        },
      };
      expectCleanFixture(fixture);
      await context.close();
    }
  }

  {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const page = await context.newPage();
    const fixture = await openHome(page, { width: 390, height: 844 });
    await enterStructuredWithOrigin(page);
    const add = page.getByTestId('add-destination');
    await chooseDestinations(page, ['北京', '上海', '长春', '南京', '杭州']);
    await expect(page.locator('.destination-token')).toHaveCount(5);
    await expect(add).toHaveText('目的地到达上限');
    await expect(add).toBeDisabled();
    const five = await stabilityGeometry(page);
    await page.getByTestId('destination-token-0').focus();
    await page.getByTestId('destination-token-0').press('ArrowDown');
    await expect(page.getByTestId('destination-token-0')).toContainText('上海');
    const sortedNames = await page.locator('.destination-token-name').allTextContents();
    expect(sortedNames).toEqual(['上海', '北京', '长春', '南京', '杭州']);
    await page.getByTestId('destination-token-4').locator('.destination-token-remove').click();
    await expect(page.locator('.destination-token')).toHaveCount(4);
    await expect(page.getByTestId('destination-token-field')).toHaveAttribute('data-state', 'closed');
    await page.waitForTimeout(320);
    await settlePlannerScroll(page);
    const four = await stabilityGeometry(page);
    await add.click();
    await expect(page.locator('.destination-search input')).toBeVisible();
    await page.waitForTimeout(320);
    await settlePlannerScroll(page);
    const fourOpen = await stabilityGeometry(page);
    expectStablePlannerFrame(four, fourOpen, '390x844 five-to-four toggle');
    for (let index = 0; index < 4; index += 1) {
      await page.getByTestId('destination-token-0').locator('.destination-token-remove').click();
      await expect(page.locator('.destination-token')).toHaveCount(3 - index);
    }
    await expect(page.getByTestId('destination-token-field')).toHaveAttribute('data-state', 'base');
    await expect(page.locator('.destination-search input')).toBeVisible();
    await expect(add).toHaveText('新增目的地');
    await expect(add).toHaveAttribute('aria-expanded', 'true');
    const zero = await stabilityGeometry(page);
    await page.locator('.destination-search input').fill('苏州');
    await page.getByTestId('destination-candidates').getByRole('button').filter({ hasText: '苏州' }).first().click();
    await expect(page.locator('.destination-token')).toHaveCount(1);
    (report.fiveAndZero as Record<string, unknown>)['390x844'] = {
      five,
      sortedNames,
      four,
      fourOpen,
      zero,
      restoredToken: await page.locator('.destination-token-name').allTextContents(),
      addState: await add.getAttribute('data-state'),
    };
    expectCleanFixture(fixture);
    await context.close();
  }

  {
    const context = await browser.newContext({ viewport: { width: 2000, height: 880 } });
    const page = await context.newPage();
    const fixture = await openHome(page, { width: 2000, height: 880 });
    await enterStructuredWithOrigin(page);
    await chooseDestinations(page, ['北京', '上海', '长春']);
    await closeDestinationsAdd(page);
    await page.getByRole('button', { name: '更多偏好' }).click();
    await expect(page.getByRole('button', { name: '户外自然', exact: true })).toBeVisible();
    await settlePlannerScroll(page);
    const closedMore = await stabilityGeometry(page);
    const add = page.getByTestId('add-destination');
    await add.click();
    await page.waitForTimeout(320);
    await settlePlannerScroll(page);
    const openMore = await stabilityGeometry(page);
    expectStablePlannerFrame(closedMore, openMore, '2000x880 more preferences');
    await page.locator('.planner-action-area .planner-main-action').click();
    await expect(page.getByText('请从地点候选中确认出发地和所有目的地。', { exact: true })).toBeVisible();
    await settlePlannerScroll(page);
    const errorOpen = await stabilityGeometry(page);
    await add.click();
    await page.waitForTimeout(320);
    await settlePlannerScroll(page);
    const errorClosed = await stabilityGeometry(page);
    expectStablePlannerFrame(errorOpen, errorClosed, '2000x880 error toggle');
    expect(errorClosed.card.height).toBeGreaterThan(closedMore.card.height);
    await expect(page.getByText('请从地点候选中确认出发地和所有目的地。', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `${destinationStabilityEvidence}/home-2000-more-preferences-error.png`, fullPage: true });
    (report.contentGrowth as Record<string, unknown>)['more-preferences-error'] = {
      closedMore,
      openMore,
      errorOpen,
      errorClosed,
    };
    expectCleanFixture(fixture);
    await context.close();
  }

  {
    const context = await browser.newContext({ viewport: { width: 2000, height: 880 }, recordVideo: { dir: destinationStabilityEvidence } });
    const page = await context.newPage();
    const video = page.video();
    const fixture = await openHome(page, { width: 2000, height: 880 });
    await enterStructuredWithOrigin(page);
    await chooseDestinations(page, ['北京', '上海', '长春']);
    await closeDestinationsAdd(page);
    await settlePlannerScroll(page);
    const before = await stabilityGeometry(page);
    const openFrames = await recordTransitionFrames(page, '[data-testid="add-destination"]');
    await page.waitForTimeout(150);
    await settlePlannerScroll(page);
    const opened = await stabilityGeometry(page);
    await page.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur();
      window.scrollTo(0, 0);
      for (const selector of ['.new-trip-hero', '.new-trip-main']) {
        const node = document.querySelector<HTMLElement>(selector);
        if (node) node.scrollTop = 0;
      }
    });
    await page.waitForTimeout(120);
    const closeFrames = await recordTransitionFrames(page, '[data-testid="add-destination"]');
    await page.waitForTimeout(150);
    await settlePlannerScroll(page);
    const closed = await stabilityGeometry(page);
    const openSummary = summarizeFrames(openFrames);
    const closeSummary = summarizeFrames(closeFrames);
    for (const summary of [openSummary, closeSummary]) {
      expect(summary.cardTopRange[1] - summary.cardTopRange[0]).toBeLessThan(2);
      expect(summary.cardHeightRange[1] - summary.cardHeightRange[0]).toBeLessThan(2);
      expect(summary.actionTopRange[1] - summary.actionTopRange[0]).toBeLessThan(2);
      expect(summary.actionHeightRange[1] - summary.actionHeightRange[0]).toBeLessThan(2);
      expect(summary.overlapSearchForm).toBe(0);
      expect(summary.prefsAboveForm).toBe(0);
    }
    expect(openSummary.formTopRange[1] - openSummary.formTopRange[0]).toBeGreaterThan(8);
    expectStablePlannerFrame(before, opened, 'animation open final');
    expectStablePlannerFrame(before, closed, 'animation close final');
    await context.close();
    let videoPath: string | null = null;
    try {
      const recorded = await video?.path();
      if (recorded) {
        const target = `${destinationStabilityEvidence}/desktop-toggle.webm`;
        const { renameSync } = await import('node:fs');
        renameSync(recorded, target);
        videoPath = target;
      }
    } catch {
      videoPath = null;
    }
    (report.animation as Record<string, unknown>)['desktop'] = {
      before,
      opened,
      closed,
      openSummary,
      closeSummary,
      openFrames,
      closeFrames,
      videoPath,
    };
    expectCleanFixture(fixture);
  }

  {
    const context = await browser.newContext({ viewport: { width: 2000, height: 880 }, reducedMotion: 'reduce' });
    const page = await context.newPage();
    const fixture = await openHome(page, { width: 2000, height: 880 });
    await enterStructuredWithOrigin(page);
    await chooseDestinations(page, ['北京', '上海', '长春']);
    await closeDestinationsAdd(page);
    await settlePlannerScroll(page);
    const closed = await stabilityGeometry(page);
    const durations = await readTransitionDurations(page);
    for (const value of Object.values(durations)) {
      const seconds = Number.parseFloat(String(value).split(',')[0]);
      expect(seconds).toBeLessThan(0.01);
    }
    const add = page.getByTestId('add-destination');
    await add.click();
    await page.waitForTimeout(120);
    await settlePlannerScroll(page);
    const open = await stabilityGeometry(page);
    expectStablePlannerFrame(closed, open, 'reduced motion open');
    expect(open.form.y - closed.form.y).toBeGreaterThan(8);
    await add.click();
    await page.waitForTimeout(120);
    await settlePlannerScroll(page);
    const closedAgain = await stabilityGeometry(page);
    expectStablePlannerFrame(closed, closedAgain, 'reduced motion close');
    await page.screenshot({ path: `${destinationStabilityEvidence}/reduced-motion-closed.png`, fullPage: true });
    (report.reducedMotion as Record<string, unknown>)['2000x880'] = { durations, closed, open, closedAgain };
    expectCleanFixture(fixture);
    await context.close();
  }

  writeFileSync(`${destinationStabilityEvidence}/geometry.json`, JSON.stringify(report, null, 2));
});

test('多目的地展开保持规划卡稳定：卡内需求确认共用目的地控件', async ({ page }) => {
  test.setTimeout(90_000);
  mkdirSync(destinationStabilityEvidence, { recursive: true });
  const fixture = await openHome(page, { width: 2000, height: 880 });
  const intakePlace = (name: string) => ({
    place_id: `osm:relation:intake-${name}`,
    provider: 'osm',
    kind: 'city',
    name,
    display_name: `${name}，中国`,
    country_code: 'CN',
    latitude: 31.2,
    longitude: 121.4,
    admin_path: ['中国', name],
  });
  const intake = {
    raw_input: '想从北京出发去上海，轻松一点',
    route_decision: { route: 'trip_planning', confidence: 1, alternatives: [], signals: ['explicit_ui_action'], requires_trip_draft: true, requires_confirmation: false },
    controlled_identity: null,
    seed_destinations: [],
    missing_fields: ['dates', 'place_confirmation'],
    ready_to_create: false,
    recognized_requirements: ['轻松一点'],
    understanding_status: 'ready',
    draft: {
      origin_query: '',
      destination_queries: ['北京'],
      start_date: '2026-11-05',
      end_date: '2026-11-08',
      duration_days: 4,
      party: { adults: 1, children: 0, elderly_companions: false, accessibility_required: false },
      style: null,
      budget_text: '',
      destination_decided: false,
      destination_suggestions: [],
      confirmed_origin: null,
      confirmed_destinations: [intakePlace('北京')],
    },
    questions: [],
    answers: [],
    additional_requirements: '',
  };
  await page.route('**/api/chat-stream', async (route) => {
    const events = [
      { type: 'guided_intake', session_id: 'home-e2e', guided_intake: intake },
      { type: 'chat_complete' },
    ];
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
    });
  });
  await page.route('**/api/sessions/home-e2e/intake', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: route.request().postData() || '{}',
    });
  });
  await page.getByTestId('natural-trip-input').fill('想从北京出发去上海，轻松一点');
  await page.getByRole('button', { name: '开始规划', exact: true }).click();
  const inlineIntake = page.locator('.planner-inline-intake');
  await expect(inlineIntake).toBeVisible();
  await expect(inlineIntake.getByTestId('destination-token-0')).toContainText('北京');
  const field = inlineIntake.getByTestId('destination-token-field');
  const add = field.getByTestId('add-destination');
  await expect(field).toHaveAttribute('data-state', 'closed');
  await expect(field.locator('.destination-search')).toHaveCount(0);
  await add.click();
  const search = field.locator('.destination-search input');
  await expect(search).toBeFocused();
  await search.fill('上海');
  await page.getByTestId('destination-candidates').getByRole('button').filter({ hasText: '上海' }).first().click();
  await expect(field.getByTestId('destination-token-0')).toContainText('北京');
  await expect(field.getByTestId('destination-token-1')).toContainText('上海');
  await expect(field).toHaveAttribute('data-state', 'open');
  await expect(field.locator('.destination-search input')).toHaveCount(1);
  await add.click();
  await expect(field).toHaveAttribute('data-state', 'closed');
  await expect(field.locator('.destination-search')).toHaveCount(0);
  await field.getByTestId('destination-token-0').focus();
  await field.getByTestId('destination-token-0').press('ArrowDown');
  await expect(field.getByTestId('destination-token-0')).toContainText('上海');
  await expect(field.getByTestId('destination-token-1')).toContainText('北京');
  await page.screenshot({ path: `${destinationStabilityEvidence}/inline-intake-shared-destination.png`, fullPage: true });
  writeFileSync(`${destinationStabilityEvidence}/inline-intake-shared-destination.json`, JSON.stringify({
    fixture: 'home local API fixture with synthetic guided intake; no real API or model',
    fieldState: await field.getAttribute('data-state'),
    order: await field.locator('.destination-token-name').allTextContents(),
    searchInputs: await field.locator('.destination-search input').count(),
  }, null, 2));
  expectCleanFixture(fixture);
});
