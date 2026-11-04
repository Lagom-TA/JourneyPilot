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

async function expectTextInsidePaper(page: Page) {
  await page.locator('.travel-atlas img').evaluateAll((images) => Promise.all(images.map((image) => (image as HTMLImageElement).decode())));
  const geometry = await page.getByTestId('travel-atlas').evaluate((atlas) => {
    const primary = atlas.querySelector('.is-primary')!.getBoundingClientRect();
    const secondary = atlas.querySelector('.is-secondary')!.getBoundingClientRect();
    const toolbar = atlas.querySelector('.atlas-toolbar')!.getBoundingClientRect();
    return {
      paperGap: secondary.top - primary.bottom,
      controlGap: Math.min(primary.top, secondary.top) - toolbar.bottom,
      leftEdgeOffset: Math.abs(toolbar.left - primary.left),
      rightEdgeOffset: Math.abs(toolbar.right - primary.right),
      controlsRight: toolbar.right,
      viewportWidth: window.innerWidth,
      tabsOnOneLine: new Set(Array.from(atlas.querySelectorAll('[role="tab"]')).map((tab) => tab.getBoundingClientRect().top)).size === 1,
    };
  });
  expect(geometry.paperGap).toBeGreaterThanOrEqual(8);
  expect(geometry.controlGap).toBeGreaterThanOrEqual(8);
  expect(geometry.leftEdgeOffset).toBeLessThanOrEqual(4);
  expect(geometry.rightEdgeOffset).toBeLessThanOrEqual(4);
  expect(geometry.controlsRight).toBeLessThanOrEqual(geometry.viewportWidth);
  expect(geometry.tabsOnOneLine).toBe(true);
  const violations = await page.locator('.atlas-example-card').evaluateAll((cards) => cards.flatMap((card) => {
    const button = card as HTMLElement;
    const previous = button.style.getPropertyValue('transform');
    const priority = button.style.getPropertyPriority('transform');
    const transition = button.style.getPropertyValue('transition');
    const transitionPriority = button.style.getPropertyPriority('transition');
    button.style.setProperty('transition', 'none', 'important');
    button.style.setProperty('transform', 'none', 'important');
    const image = button.querySelector<HTMLImageElement>('.atlas-paper')!;
    const box = image.getBoundingClientRect();
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext('2d')!;
    context.drawImage(image, 0, 0);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const walker = document.createTreeWalker(button, NodeFilter.SHOW_TEXT);
    const errors: string[] = [];
    while (walker.nextNode()) {
      const text = walker.currentNode;
      if (!text.textContent?.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(text);
      for (const rect of Array.from(range.getClientRects())) {
        const points = [[rect.left, rect.top], [rect.right, rect.top], [rect.left, rect.bottom], [rect.right, rect.bottom]];
        for (const [left, top] of points) {
          const x = Math.floor((left - box.left) / box.width * canvas.width);
          const y = Math.floor((top - box.top) / box.height * canvas.height);
          if (x < 0 || x >= canvas.width || y < 0 || y >= canvas.height || pixels[(y * canvas.width + x) * 4 + 3] < 160) {
            errors.push(`${button.dataset.testid}: ${text.textContent.trim()}`);
            break;
          }
        }
      }
    }
    if (previous) button.style.setProperty('transform', previous, priority);
    else button.style.removeProperty('transform');
    button.getBoundingClientRect();
    if (transition) button.style.setProperty('transition', transition, transitionPriority);
    else button.style.removeProperty('transition');
    return errors;
  }));
  expect(violations).toEqual([]);
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
  await expect(page.getByRole('heading', { name: '我的偏好', exact: true })).toBeVisible();
});

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

test('首页只保留自由输入、四种场景与两件互补的旅行纸品', async ({ page }) => {
  const fixture = await openHome(page, { width: 1440, height: 900 });
  const input = page.getByTestId('natural-trip-input');
  await expect(page.getByRole('button', { name: '补充偏好' })).toHaveCount(0);
  await expect(page.getByText('补充偏好', { exact: true })).toHaveCount(0);
  await expect(page.locator('.planner-natural-starter')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '开始规划', exact: true })).toBeDisabled();
  await expect(input).toHaveCSS('resize', 'none');
  const initialInputHeight = (await input.boundingBox())!.height;
  await input.fill(Array.from({ length: 12 }, () => '沿海慢慢走，安排一些休息时间。').join('\n'));
  await expect.poll(async () => (await input.boundingBox())!.height).toBeGreaterThan(initialInputHeight + 100);
  expect(await input.evaluate((element) => element.scrollHeight - element.clientHeight)).toBeLessThanOrEqual(1);
  await input.fill('');
  await expect.poll(async () => (await input.boundingBox())!.height).toBe(initialInputHeight);
  const scenes = [
    { id: 'jiangnan', tab: '江南', title: '苏州＋杭州 4 日' },
    { id: 'northwest', tab: '西北', title: '敦煌＋张掖 6 日' },
    { id: 'southwest', tab: '巴蜀', title: '成都＋重庆 7 日' },
    { id: 'island', tab: '海岛', title: '海口＋三亚 5 日' },
  ];
  for (const scene of scenes) {
    await page.getByTestId(`atlas-tab-${scene.id}`).click();
    await expect(page.getByTestId('travel-atlas')).toHaveAttribute('data-scene', scene.id);
    const example = page.getByTestId('atlas-use-example');
    await expect(example).toHaveAccessibleName(`采用旅行提案：${scene.title}`);
    await expect(example.locator('.atlas-example-title')).toContainText(scene.title.split('＋')[0]);
    await expect(page.getByTestId('atlas-use-alternate')).toHaveAttribute('data-theme', scene.id);
    await expect(page.locator('.home-landscape')).toHaveAttribute('data-theme', scene.id);
    await expect(page.getByTestId('travel-atlas').getByText('填入', { exact: true })).toHaveCount(0);
    await expect(page.locator('.atlas-example-card')).toHaveCount(2);
    await expect(page.locator('.atlas-scene')).toHaveCount(1);
    await expectTextInsidePaper(page);
  }
  await page.getByTestId('atlas-use-example').click();
  await expect(input).toHaveValue(/海口和三亚/);
  await expect(input).toBeFocused();
  await expect(page.getByRole('button', { name: '开始规划', exact: true })).toBeEnabled();
  const proposal = await input.inputValue();
  await input.fill('另一个还未提交的想法');
  await page.getByTestId('atlas-use-alternate').click();
  await expect(input).toHaveValue(proposal);
  await expect(input).toBeFocused();
  for (const paper of ['atlas-use-example', 'atlas-use-alternate']) {
    await page.getByTestId(paper).hover();
    await page.waitForTimeout(350);
    await expectTextInsidePaper(page);
  }
  expectCleanFixture(fixture);
});

test('旅行提案自动轮换在悬停、填写、焦点和隐藏页面时暂停', async ({ page }) => {
  await page.clock.install();
  const fixture = await openHome(page);
  const atlas = page.getByTestId('travel-atlas');
  await page.mouse.move(0, 0);
  await expect(atlas).toHaveAttribute('data-autoplay', 'running');
  const readProgress = () => page.getByTestId('atlas-progress').evaluate((element) => {
    const right = getComputedStyle(element).clipPath.match(/inset\([^ ]+ ([\d.]+)%/);
    return 1 - Number(right?.[1] ?? 100) / 100;
  });
  await expect(page.getByTestId('atlas-rotation-control')).toHaveCount(0);
  await page.clock.fastForward(6000);
  await page.clock.runFor(40);
  const partial = await readProgress();
  expect(partial).toBeGreaterThan(0.35);
  expect(partial).toBeLessThan(0.65);
  await page.getByTestId('atlas-use-example').hover();
  await expect(atlas).toHaveAttribute('data-autoplay', 'paused');
  const frozen = await readProgress();
  await page.clock.fastForward(28_000);
  expect(await readProgress()).toBeCloseTo(frozen, 2);
  await expect(atlas).toHaveAttribute('data-scene', 'northwest');
  await page.mouse.move(0, 0);
  await expect(atlas).toHaveAttribute('data-autoplay', 'running');
  await page.clock.fastForward(8100);
  await expect(atlas).toHaveAttribute('data-scene', 'island');
  const input = page.getByTestId('natural-trip-input');
  await input.fill('保留我自己的旅行想法');
  await expect(atlas).toHaveAttribute('data-autoplay', 'paused');
  await page.clock.fastForward(28_000);
  await expect(atlas).toHaveAttribute('data-scene', 'island');
  await expect(input).toHaveValue('保留我自己的旅行想法');
  await page.getByTestId('atlas-tab-jiangnan').focus();
  await page.clock.fastForward(28_000);
  await expect(atlas).toHaveAttribute('data-scene', 'island');
  await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());
  await page.mouse.move(0, 0);
  await expect(atlas).toHaveAttribute('data-autoplay', 'running');
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(atlas).toHaveAttribute('data-autoplay', 'paused');
  await page.clock.fastForward(28_000);
  await expect(atlas).toHaveAttribute('data-scene', 'island');
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(atlas).toHaveAttribute('data-autoplay', 'running');
  await page.clock.fastForward(14_100);
  await expect(atlas).toHaveAttribute('data-scene', 'southwest');
  await expect(input).toHaveValue('保留我自己的旅行想法');
  expectCleanFixture(fixture);
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

test('配置失败不阻塞一句话输入，条件规划可以重试并保留草稿', async ({ page }) => {
  const fixture = await openHome(page, { width: 1440, height: 900 }, true);
  const input = page.getByTestId('natural-trip-input');
  await input.fill('带爸妈去杭州，步行少一点。');
  await page.getByTestId('planner-structured-tab').click();
  await expect(page.getByText('暂时读不到规划选项', { exact: true })).toBeVisible();
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
  await page.clock.install();
  await page.clock.fastForward(7000);
  await expect(page.getByTestId('travel-atlas')).toHaveAttribute('data-scene', 'northwest');
  await page.clock.resume();
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
  expect((await planner.boundingBox())!.height).toBeGreaterThan(naturalHeight + 60);
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

test('减少动态效果时场景立即切换且不保留装饰动效', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await openHome(page);
  await expect(page.locator('.atlas-liquid-lens')).toHaveCount(0);
  await page.getByTestId('atlas-tab-jiangnan').click();
  await expect(page.locator('.atlas-scene')).toHaveCount(1);
  await expect(page.getByTestId('travel-atlas')).toHaveAttribute('data-scene', 'jiangnan');
  const transition = await page.getByTestId('atlas-use-example').evaluate((el) => getComputedStyle(el).transitionDuration);
  expect(Number.parseFloat(transition)).toBeLessThan(0.01);
  expectCleanFixture(fixture);
});

test('人数用选项和自填确认，取消不改变草稿，提交保留成人儿童', async ({ browser }) => {
  const evidence = '../output/review/F2';
  mkdirSync(evidence, { recursive: true });
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport, deviceScaleFactor: 2 });
    const page = await context.newPage();
    const fixture = await openHome(page, viewport);
    const code = viewport.width === 390 ? 'M' : 'D';
    await page.getByTestId('planner-structured-tab').click();
    await expect(page.getByRole('button', { name: '增加成人' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '减少儿童' })).toHaveCount(0);
    await page.locator('.planner-card').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${evidence}/H2-${code}-form-r10.png` });
    const trigger = page.getByTestId('traveler-picker-trigger');
    await trigger.click();
    const dialog = page.getByTestId('traveler-picker-dialog');
    await expect(dialog).toHaveCSS('opacity', '1');
    await expect(page.getByRole('button', { name: '9 位成人', exact: true })).toBeVisible();
    await page.screenshot({ path: `${evidence}/H2-${code}-travelers-r10.png` });
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
    await page.screenshot({ path: `${evidence}/H2-${code}-travelers-custom-r10.png` });
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
  const evidence = '../output/review/F2';
  mkdirSync(evidence, { recursive: true });
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    const fixture = await openHome(page, viewport);
    const code = viewport.width === 390 ? 'M' : 'D';
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
    await page.screenshot({ path: `${evidence}/H1-${code}-pending-r10.png` });
    release();
    await expect(page.getByRole('button', { name: '再试一次', exact: true })).toBeVisible();
    await expect(page.getByText(text, { exact: true })).toBeVisible();
    await expect(page.getByText('Service unavailable: internal-provider-debug', { exact: true })).toHaveCount(0);
    await expect(page.getByTestId('error-inspect')).toHaveCount(0);
    await page.screenshot({ path: `${evidence}/H1-${code}-failed-r10.png` });
    expectCleanFixture(fixture);
    await context.close();
  }
});

test('目的地首站全宽常驻、紧凑小块换行与二维排序', async ({ page }) => {
  test.setTimeout(90_000);
  const fixture = await openHome(page, { width: 2000, height: 880 });
  await page.getByRole('tab', { name: '按条件规划' }).click();
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

test('首页在宽窄屏和断点保持主操作可见，条件表单自然展开', async ({ browser }) => {
  test.setTimeout(90_000);
  const evidence = '../output/review/F2';
  mkdirSync(evidence, { recursive: true });
  const results: Record<string, unknown> = {};
  const viewports = [
    ['M', 390, 844, 2], ['T', 768, 1024, 2], ['L', 1280, 720, 2],
    ['D', 1440, 900, 2], ['W', 1920, 1080, 1], ['U', 2560, 1440, 1],
    ['B639', 639, 900, 2], ['B640', 640, 900, 2],
    ['B1023', 1023, 900, 2], ['B1024', 1024, 900, 2], ['N320', 320, 844, 1],
  ] as const;
  for (const [code, width, height, deviceScaleFactor] of viewports) {
    const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor });
    const page = await context.newPage();
    const fixture = await openHome(page, { width, height });
    await page.locator('.atlas-artwork').evaluate((el) => (el as HTMLImageElement).decode());
    const planner = page.locator('.planner-card');
    const action = page.getByRole('button', { name: '开始规划', exact: true });
    const natural = (await planner.boundingBox())!;
    const headline = (await page.locator('.new-trip-copy').boundingBox())!;
    const content = (await page.locator('.new-trip-content').boundingBox())!;
    const actionBox = (await action.boundingBox())!;
    expect(natural.y - headline.y - headline.height).toBeGreaterThanOrEqual(40);
    expect(actionBox.y + actionBox.height).toBeLessThanOrEqual(height);
    expect(await page.locator('.new-trip-hero').evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    await expectTextInsidePaper(page);
    await page.screenshot({ path: `${evidence}/H1-${code}-default-r10.png` });
    await page.getByTestId('planner-structured-tab').click();
    await page.getByRole('button', { name: '更多偏好' }).click();
    await expect(page.getByRole('button', { name: '长辈同行', exact: true })).toBeVisible();
    await page.getByRole('textbox', { name: '出发地' }).fill('北京');
    await page.getByLabel('预算（可选）').fill('-1');
    await action.click();
    await expect(page.getByLabel('预算（可选）')).toHaveAttribute('aria-invalid', 'true');
    const structured = (await planner.boundingBox())!;
    expect(structured.height).toBeGreaterThan(natural.height);
    const overflow = await page.locator('.planner-card').evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${evidence}/H2-${code}-preferences-error-r10.png` });
    if (['M', 'D', 'B639', 'B640'].includes(code)) {
      await page.getByTestId('date-range-trigger').click();
      await expect(page.getByTestId('date-range-dialog')).toBeVisible();
      await expect(page.getByTestId('date-range-dialog')).toHaveCSS('opacity', '1');
      const calendar = (await page.getByTestId('date-range-dialog').boundingBox())!;
      expect(calendar.y).toBeGreaterThanOrEqual(0);
      expect(calendar.y + calendar.height).toBeLessThanOrEqual(height);
      await page.screenshot({ path: `${evidence}/H4-${code}-calendar-r10.png` });
      await page.keyboard.press('Escape');
    }
    results[code] = { width, height, deviceScaleFactor, headline, content, natural, structured, action: actionBox, overflow };
    expectCleanFixture(fixture);
    await context.close();
  }
  writeFileSync(`${evidence}/implementation-layout-r10.json`, JSON.stringify(results, null, 2));
});
