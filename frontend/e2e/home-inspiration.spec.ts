import { expect, test, type Page } from '@playwright/test';

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
  await page.getByLabel('总预算（可选）').fill('4567');
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
  await expect(page.getByRole('textbox', { name: '去哪里', exact: true })).toHaveValue('海口');
  await expect(page.getByRole('textbox', { name: '第 2 站', exact: true })).toHaveValue('三亚');
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
  expectCleanFixture(fixture);
});
