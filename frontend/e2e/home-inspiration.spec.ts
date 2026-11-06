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
  await expect(page.getByRole('heading', { name: '我的偏好', exact: true })).toBeVisible();
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

test('人数用选项和自填确认，取消不改变草稿，提交保留成人儿童', async ({ browser }) => {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport, deviceScaleFactor: 2 });
    const page = await context.newPage();
    const fixture = await openHome(page, viewport);
    await page.getByTestId('planner-structured-tab').click();
    await expect(page.getByRole('button', { name: '增加成人' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '减少儿童' })).toHaveCount(0);
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
    await expect(page.getByTestId('error-inspect')).toHaveCount(0);
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

  for (const name of ['南京', '宁波', '绍兴']) await choose(name, false);
  await expect(page.locator('.destination-token')).toHaveCount(5);
  await expect(page.locator('.destination-search')).toHaveCount(0);
  await expect(page.getByTestId('add-destination')).toHaveText('目的地到达上限');
  await expect(page.getByTestId('add-destination')).toBeDisabled();
  expect(await page.locator('.destination-token-name').allTextContents()).toEqual(['杭州', '苏州', '南京', '宁波', '绍兴']);

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
  expect(crossRowTouchOrder).toEqual(['苏州', '南京', '宁波', '杭州', '绍兴']);

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
