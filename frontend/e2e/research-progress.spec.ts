import { test, expect, type Page } from '@playwright/test';

// 在 Vite dev 下运行：JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npm run test:e2e -- research-progress
// 该 fixture 使用真实 UI 组件与合成事件，不调用付费 API。
test.skip(process.env.JP_COMPONENT_E2E !== '1', 'Requires Vite dev component fixture');

async function expectPlanningCardWithoutDuplicateCopy(page: Page, status: string) {
  const card = page.getByTestId('research-agent-planning');
  await expect(card.locator('.research-agent-state')).toContainText(status);
  await expect(card.locator('[data-testid="research-agent-update"]')).toHaveCount(0);
  await expect(card.locator('.research-agent-description')).toHaveCount(0);
  await expect(card).not.toContainText('理解偏好，准备相关查询');
  await expect(card).not.toContainText('旅行需求已整理');
  await expect(card).not.toContainText('正在准备相关查询');
  await expect(card.locator('button')).toHaveCount(0);
}

for (const width of [320, 390, 1440]) {
  test(`研究面板：并行归因、有效详情、停止状态 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/e2e/fixtures/research-progress.html');
    const panel = page.getByTestId('thinking-chain');
    await expect(panel).toContainText('查找旅行资料');
    await expect(panel.getByTestId('research-agent-destination')).toBeVisible();
    await expect(panel.getByTestId('research-agent-transport')).toBeVisible();
    await expect(panel.getByTestId('research-agent-stay')).toBeVisible();
    await expect(panel).not.toContainText('contract_version');
    const destination = page.getByTestId('research-agent-destination');
    await expect(destination.getByRole('button')).toHaveCount(0);
    const query = destination.getByTestId('research-query');
    await expect(query).toContainText('长春 历史博物馆');
    await expect(query.locator('.research-source')).not.toBeVisible();
    await query.locator('summary').click();
    await expect(query).toContainText('长春市宽城区光复北路');
    await expect(query.getByRole('link', { name: '伪满皇宫博物院' })).toHaveAttribute('href', 'https://example.org/museum');
    await expect(destination).toContainText('1 次查询');
    const stay = page.getByTestId('research-agent-stay');
    await expect(stay.getByRole('button')).toHaveCount(0);
    await expect(stay.getByTestId('research-query').first().locator('summary')).toHaveCount(0);
    await expect(stay).toContainText('参考资料');
    await expect(stay).toContainText('2 次查询 · 1 项资料需留意');
    await page.getByRole('button', { name: '住宿直接返回', exact: true }).click();
    await expect(stay).toContainText('已整理 1 个住宿候选');
    await expect(stay.getByTestId('research-query')).toHaveCount(0);
    await page.getByRole('button', { name: '目的地完成', exact: true }).click();
    await expect(destination.locator('.research-agent-state')).toHaveText('已结束');
    await expect(page.getByTestId('research-agent-transport').locator('.research-agent-state')).toHaveText('进行中');
    await page.getByRole('button', { name: '停止', exact: true }).click();
    await expect(panel).toContainText('旅行规划已中断');
    await expect(page.getByTestId('research-agent-transport').locator('.research-agent-state')).toHaveText('已停止');
    await expect(destination.getByRole('link', { name: '伪满皇宫博物院' })).toBeVisible();
    await expect(destination.getByTestId('research-query')).toContainText('伪满皇宫博物院');
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    expect(errors).toEqual([]);
  });
}

test('workspace 工具行密度、展开长查询与真实阶段标题', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/e2e/fixtures/research-progress.html');
  const panel = page.getByTestId('thinking-chain');
  await expect(panel.locator('.research-panel-title')).toHaveText('查找旅行资料');
  await expect(panel.locator('.research-agent-heading button')).toHaveCount(0);
  const transport = page.getByTestId('research-agent-transport');
  const stageHeight = await transport.locator('.research-agent-heading').evaluate(element => element.getBoundingClientRect().height);
  expect(stageHeight).toBeGreaterThanOrEqual(40);
  expect(stageHeight).toBeLessThanOrEqual(48);
  const row = transport.getByTestId('research-query').locator('.research-query-summary').first();
  const rowHeight = await row.evaluate(element => element.getBoundingClientRect().height);
  expect(rowHeight).toBeGreaterThanOrEqual(40);
  expect(rowHeight).toBeLessThanOrEqual(48);

  await page.getByRole('button', { name: '内部工具', exact: true }).click();
  const internalRow = page.getByTestId('research-query').filter({ hasText: '已选择适合本次行程的地点与交通资料' });
  await expect(internalRow).toBeVisible();
  await expect(internalRow).toContainText('整理规划');
  await expect(internalRow).not.toContainText('global_place_search');
  await page.screenshot({ path: '../output/polish/20261029-1817-compact-tool-activity/workspace-2000-compact-list.png' });

  await page.getByRole('button', { name: '长查询', exact: true }).click();
  const longRow = page.getByTestId('research-query').filter({ hasText: '杭州西湖周边适合雨天慢慢散步' });
  await expect(longRow).toContainText('杭州西湖周边适合雨天慢慢散步、喝咖啡并避开人群的路线与街区');
  await longRow.locator('summary').click();
  await expect(longRow.getByRole('link', { name: '北山街雨天散步路线' })).toBeVisible();
  await expect(longRow.locator('.research-query-title')).toHaveCSS('white-space', 'normal');
  await page.screenshot({ path: '../output/polish/20261029-1817-compact-tool-activity/workspace-2000-expanded-query.png' });
  await longRow.locator('summary').click();

  await page.getByRole('button', { name: '路线阶段', exact: true }).click();
  await expect(panel.locator('.research-panel-title')).toHaveText('安排每天路线');
  await page.screenshot({ path: '../output/polish/20261029-1817-compact-tool-activity/workspace-2000-route-stage.png' });
  await page.getByRole('button', { name: '生成阶段', exact: true }).click();
  await expect(panel.locator('.research-panel-title')).toHaveText('生成完整计划');
  await page.screenshot({ path: '../output/polish/20261029-1817-compact-tool-activity/workspace-2000-delivery-stage.png' });

  await page.setViewportSize({ width: 390, height: 844 });
  const phoneRow = page.getByTestId('research-query').filter({ hasText: '杭州西湖周边适合雨天慢慢散步' });
  await phoneRow.locator('summary').click();
  await expect(phoneRow.getByRole('link', { name: '北山街雨天散步路线' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: '../output/polish/20261029-1817-compact-tool-activity/workspace-390-expanded-query.png', fullPage: true });
});

type GenerationFixtureWindow = Window & { __generationFixture?: { addResearch: () => void; longTitle: () => void; stop: () => void; finish: () => void; failAfterPlanning: () => void; cancelAfterPlanning: () => void; requestCancelAfterPlanning: () => void } };

type GenerationSseStream = { push: (events: unknown[]) => void; close: () => void; requests: () => number };
type GenerationSseWindow = Window & { __generationSse?: { start: () => void }; __generationSseStream?: GenerationSseStream };

async function openGenerationSse(page: Page) {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.addInitScript(() => {
    const state: { controller: ReadableStreamDefaultController<Uint8Array> | null; requests: number } = { controller: null, requests: 0 };
    const win = window as unknown as { __generationSseStream?: GenerationSseStream };
    win.__generationSseStream = {
      push(events) {
        const encoder = new TextEncoder();
        for (const event of events) state.controller?.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      },
      close() {
        try { state.controller?.close(); } catch { /* stream already closed */ }
        state.controller = null;
      },
      requests: () => state.requests,
    };
    const originalFetch = window.fetch.bind(window);
    window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      if (!url.includes('/api/chat-stream')) return originalFetch(input, init);
      state.requests += 1;
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          state.controller = controller;
          init?.signal?.addEventListener('abort', () => {
            try { controller.error(new DOMException('aborted', 'AbortError')); } catch { /* already closed */ }
          });
        },
      });
      return Promise.resolve(new Response(stream, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
      }));
    }) as typeof window.fetch;
  });
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(path === '/api/user/sessions' ? [] : {}),
    });
  });
  await page.goto('/e2e/fixtures/generation-sse.html');
  await expect.poll(() => page.evaluate(() => Boolean((window as GenerationSseWindow).__generationSse))).toBe(true);
  await page.evaluate(() => (window as GenerationSseWindow).__generationSse?.start());
  await expect.poll(() => page.evaluate(() => (window as GenerationSseWindow).__generationSseStream?.requests() ?? 0)).toBe(1);
  return {
    pageErrors,
    push: (events: unknown[]) => page.evaluate((payload) => (window as GenerationSseWindow).__generationSseStream?.push(payload), events),
    close: () => page.evaluate(() => (window as GenerationSseWindow).__generationSseStream?.close()),
  };
}

test('真实 thinking 事件缺少 progress_status 时，终态展开记录不再显示运行中占位', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await openGenerationSse(page);
  const ts = 1761743000000;
  await fixture.push([{
    type: 'chat_start',
    session_id: 'generation-sse',
    run_id: 'run-generation-sse',
    message_id: 'assistant-generation-sse',
    route_decision: { route: 'trip_planning', confidence: 1, alternatives: [], signals: ['explicit_ui_action'], requires_trip_draft: true, requires_confirmation: false },
    ts_ms: ts,
  }]);
  await expect(page.getByTestId('generation-journey-panel')).toBeVisible();
  await fixture.push([
    { type: 'thinking', message_id: 'assistant-generation-sse', agent_name: '制定计划', content: '制定调研计划：目的地调研/交通查询/住宿查询', step_name: '制定规划安排', ts_ms: ts + 1 },
    { type: 'thinking', message_id: 'assistant-generation-sse', agent_name: '安排查询', content: '正在分派并行调研任务', step_name: '安排旅行查询', ts_ms: ts + 2 },
    { type: 'agent_progress', message_id: 'assistant-generation-sse', agent_name: '整理需求', content: '已整理旅行偏好与同行信息', step_name: '整理旅行需求', progress_status: 'completed', ts_ms: ts + 3 },
    { type: 'tool_start', message_id: 'assistant-generation-sse', agent_name: '目的地调研', tool_name: 'global_place_search', tool_call_id: 'sse-place', args_summary: '{"query":"青岛 海岸线"}', category: 'search', ts_ms: ts + 4 },
    { type: 'tool_result', message_id: 'assistant-generation-sse', agent_name: '目的地调研', tool_name: 'global_place_search', tool_call_id: 'sse-place', status: 'success', summary: '找到 1 个结果', result_preview: [{ title: '小麦岛公园', detail: '适合傍晚看海与散步', url: 'https://example.org/qingdao-coast' }], category: 'search', ts_ms: ts + 5 },
  ]);
  const planning = page.getByTestId('research-agent-planning');
  await expect(page.getByTestId('research-agent-destination')).toContainText('找到 1 个结果');
  await fixture.push([{ type: 'run_failed', run_id: 'run-generation-sse', message: '离线合成：真实 thinking 事件形状后规划失败。', run_status: 'failed', ts_ms: ts + 6 }]);
  await expect(page.locator('.generation-progress > h2')).toHaveText('旅行规划未完成');
  await expect(page.locator('.research-panel-title')).toHaveText('旅行规划未完成');
  await expect(planning.locator('.research-agent-state')).toHaveText('已结束');
  await expect(planning.getByTestId('research-agent-update')).toHaveText('已整理旅行偏好与同行信息');
  await expect(planning).not.toContainText('正在分派并行调研任务');
  await expect(planning).not.toContainText('正在准备相关查询');
  await expect(planning).not.toContainText('正在分派并行调研任务');
  await expect(planning.locator('.research-agent-body')).toContainText('制定调研计划：目的地调研/交通查询/住宿查询');
  await expect(planning.locator('.research-agent-body')).not.toContainText('正在分派并行调研任务');
  const destination = page.getByTestId('research-agent-destination');
  await expect(destination).toContainText('找到 1 个结果');
  await destination.getByTestId('research-query').locator('summary').click();
  await expect(destination.getByRole('link', { name: '小麦岛公园' })).toBeVisible();
  await page.screenshot({ path: '../output/polish/20261029-1817-compact-tool-activity/generation-2000-failed-expanded.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.generation-activity').scrollIntoViewIfNeeded();
  await expect(planning).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: '../output/polish/20261029-1817-compact-tool-activity/generation-390-failed.png' });
  await fixture.close();
  expect(fixture.pageErrors).toEqual([]);
});

test('真实 thinking 事件后取消也不在终态展开记录保留运行中占位', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const fixture = await openGenerationSse(page);
  const ts = 1761743100000;
  await fixture.push([{ type: 'chat_start', session_id: 'generation-sse-cancel', run_id: 'run-generation-sse-cancel', message_id: 'assistant-generation-sse-cancel', route_decision: { route: 'trip_planning', confidence: 1, alternatives: [], signals: ['explicit_ui_action'], requires_trip_draft: true, requires_confirmation: false }, ts_ms: ts }]);
  await fixture.push([
    { type: 'thinking', message_id: 'assistant-generation-sse-cancel', agent_name: '制定计划', content: '制定调研计划：目的地调研/交通查询/住宿查询', step_name: '制定规划安排', ts_ms: ts + 1 },
    { type: 'thinking', message_id: 'assistant-generation-sse-cancel', agent_name: '安排查询', content: '正在分派并行调研任务', step_name: '安排旅行查询', ts_ms: ts + 2 },
  ]);
  await fixture.push([{ type: 'run_cancelled', run_id: 'run-generation-sse-cancel', final_content: '离线合成：真实 thinking 事件形状后取消。', ts_ms: ts + 3 }]);
  await expect(page.locator('.generation-progress > h2')).toHaveText('旅行规划已取消');
  await expect(page.locator('.research-panel-title')).toHaveText('旅行规划已取消');
  const planning = page.getByTestId('research-agent-planning');
  await expect(planning.locator('.research-agent-state')).toHaveText('已结束');
  await expect(planning).not.toContainText('正在分派并行调研任务');
  await expect(planning.locator('.research-agent-body')).toContainText('制定调研计划：目的地调研/交通查询/住宿查询');
  await expect(planning.locator('.research-agent-body')).not.toContainText('正在分派并行调研任务');
  await fixture.close();
  expect(fixture.pageErrors).toEqual([]);
});

test.describe('生成工作区卡片、过程区与阶段扫光', () => {
  test('2000px 等待态与有研究内容时过程区占满右侧', async ({ page }) => {
    await page.setViewportSize({ width: 2000, height: 880 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/e2e/fixtures/generation-progress.html');
    const panel = page.getByTestId('generation-journey-panel');
    await expect(panel).toBeVisible();
    await expect(page.getByText('规划过程', { exact: true })).toHaveCount(0);
    await expect(page.getByText('每一步安排，都有据可查', { exact: true })).toHaveCount(0);
    await expect(page.getByText('查看不同阶段的思考摘要、查询内容和已找到的旅行资料。', { exact: true })).toHaveCount(0);
    await expect(page.getByText('规划进度', { exact: true })).toHaveCount(0);
    await expect(page.getByText('正在整理这趟旅行的基本信息。', { exact: true })).toHaveCount(0);
    await expectPlanningCardWithoutDuplicateCopy(page, '进行中');
    await expect(page.locator('.research-agent-description')).toHaveCount(0);
    const cardStyle = await page.locator('.generation-trip-card').evaluate((element) => {
      const style = getComputedStyle(element);
      return { border: style.borderTopWidth, radius: style.borderTopLeftRadius, background: style.backgroundColor };
    });
    expect(Number.parseFloat(cardStyle.border)).toBeGreaterThan(0);
    expect(Number.parseFloat(cardStyle.radius)).toBeGreaterThan(0);
    expect(cardStyle.background).not.toBe('rgba(0, 0, 0, 0)');
    const geometry = await page.evaluate(() => {
      const activity = document.querySelector('.generation-activity')!.getBoundingClientRect();
      const research = document.querySelector('.research-panel-workspace')!.getBoundingClientRect();
      return { activity: activity.width, research: research.width };
    });
    expect(geometry.research / geometry.activity).toBeGreaterThan(0.88);
    expect(geometry.research).toBeGreaterThan(1200);
    const active = page.locator('.generation-progress li.is-active');
    await expect(active).toHaveCount(1);
    const motion = await active.evaluate((element) => {
      const style = getComputedStyle(element, '::before');
      return { name: style.animationName, duration: style.animationDuration };
    });
    expect(motion.name).toBe('generation-stage-sweep');
    expect(Number.parseFloat(motion.duration)).toBeGreaterThanOrEqual(3);
    await page.screenshot({ path: '../output/polish/20261029-1252-generation-layout/generation-2000-waiting.png' });
    await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.addResearch());
    await expectPlanningCardWithoutDuplicateCopy(page, '已结束');
    const destination = page.getByTestId('research-agent-destination');
    const transport = page.getByTestId('research-agent-transport');
    await expect(destination.getByTestId('research-agent-update')).toHaveText('正在查找杭州与苏州的景点、美食和步行路线');
    await expect(transport.getByTestId('research-agent-update')).toHaveText('已整理上海到杭州的火车衔接');
    await expect(transport).toContainText('1 次查询');
    await expect(page.locator('.research-agent-description')).toHaveCount(0);
    await page.screenshot({ path: '../output/polish/20261029-1252-generation-layout/generation-2000-research-r3.png' });
    await transport.getByTestId('research-query').locator('summary').click();
    await expect(transport.getByRole('link', { name: '上海虹桥 → 杭州东' })).toBeVisible();
    await page.screenshot({ path: '../output/polish/20261029-1252-generation-layout/generation-2000-research-r3-details.png' });
    await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.longTitle());
    const title = page.locator('.generation-trip-card-header h1');
    await expect(title).toContainText('乌兰浩特');
    const titleGeometry = await title.evaluate((element) => {
      const duration = element.querySelector('.generation-trip-title-duration') as HTMLElement;
      const heading = element.getBoundingClientRect();
      const stop = (element.closest('.generation-trip-card-header')?.querySelector('.generation-stop-btn') as HTMLElement).getBoundingClientRect();
      const durationBox = duration.getBoundingClientRect();
      const places = Array.from(element.querySelectorAll('.generation-trip-title-place')).map((place) => place.getBoundingClientRect().height);
      return {
        durationHeight: durationBox.height,
        durationWidth: durationBox.width,
        lineHeight: Number.parseFloat(getComputedStyle(element).lineHeight),
        headingRight: heading.right,
        stopLeft: stop.left,
        placeHeights: places,
      };
    });
    expect(titleGeometry.durationHeight).toBeLessThan(titleGeometry.lineHeight * 1.35);
    expect(titleGeometry.durationWidth).toBeGreaterThan(20);
    expect(titleGeometry.placeHeights).toHaveLength(5);
    for (const height of titleGeometry.placeHeights) expect(height).toBeLessThan(titleGeometry.lineHeight * 1.35);
    expect(titleGeometry.headingRight).toBeLessThanOrEqual(titleGeometry.stopLeft + 1);
    await page.screenshot({ path: '../output/polish/20261029-1252-generation-layout/generation-2000-long-title.png' });
    expect(errors).toEqual([]);
  });

  test('1440px 活动阶段缓慢扫光，停止与减少动态时关闭', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.goto('/e2e/fixtures/generation-progress.html');
    const active = page.locator('.generation-progress li.is-active');
    await expect(active).toHaveCount(1);
    const researchWidth = await page.locator('.research-panel-workspace').evaluate((element) => element.getBoundingClientRect().width);
    expect(researchWidth).toBeGreaterThan(900);
    await page.screenshot({ path: '../output/polish/20261029-1817-compact-tool-activity/generation-1440-active.png' });
    await expect(page.locator('.generation-progress')).toHaveAttribute('data-active', 'true');
    await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.stop());
    await expect(page.locator('.generation-progress')).toHaveAttribute('data-active', 'false');
    await expect(page.locator('.generation-progress li.is-active')).toHaveCount(0);
    await expect(page.locator('.generation-progress > h2')).toHaveText('旅行规划已取消');
    await expect(page.locator('.research-panel-title')).toHaveText('旅行规划已取消');
    await expectPlanningCardWithoutDuplicateCopy(page, '已停止');
    expect(await page.locator('.generation-progress li').first().evaluate((element) => getComputedStyle(element, '::before').animationName)).toBe('none');

    await page.reload();
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await expect(page.locator('.generation-progress')).toHaveAttribute('data-active', 'true');
    expect(await page.locator('.generation-progress li.is-active').evaluate((element) => getComputedStyle(element, '::before').animationName)).toBe('none');
  });

  test('390px 手机按阅读顺序排列且无横向溢出', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/e2e/fixtures/generation-progress.html');
    await expect(page.getByTestId('generation-journey-panel')).toBeVisible();
    await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.addResearch());
    await expect(page.getByTestId('research-agent-destination')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const order = await page.evaluate(() => {
      const card = document.querySelector('.generation-trip-card')!.getBoundingClientRect();
      const activity = document.querySelector('.generation-activity')!.getBoundingClientRect();
      return { cardBottom: card.bottom, activityTop: activity.top };
    });
    expect(order.activityTop).toBeGreaterThanOrEqual(order.cardBottom - 1);
    await page.screenshot({ path: '../output/polish/20261029-1252-generation-layout/generation-390-phone.png', fullPage: true });
  });

  test('2000px 需求整理完成随后失败只显示真实阶段状态', async ({ page }) => {
    await page.setViewportSize({ width: 2000, height: 880 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/e2e/fixtures/generation-progress.html');
    await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.failAfterPlanning());
    await expect(page.locator('.generation-progress > h2')).toHaveText('旅行规划未完成');
    await expect(page.getByText('这次规划没有完成，你可以回到新旅行重新尝试。', { exact: true })).toBeVisible();
    await expect(page.getByText('旅行方案暂时无法生成，请稍后重试。', { exact: true })).toBeVisible();
    await expect(page.locator('.research-panel-title')).toHaveText('旅行规划未完成');
    await expectPlanningCardWithoutDuplicateCopy(page, '已结束');
    await expect(page.getByText(/理解偏好|旅行需求已整理|正在准备相关查询/)).toHaveCount(0);
    await expect(page.locator('.research-agent-description')).toHaveCount(0);
    await page.screenshot({ path: '../output/polish/20261029-1252-generation-layout/generation-2000-failed-r3.png' });
    expect(errors).toEqual([]);
  });

  test('取消后阶段卡不承诺继续准备', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/e2e/fixtures/generation-progress.html');
    await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.cancelAfterPlanning());
    await expect(page.locator('.generation-progress > h2')).toHaveText('旅行规划已取消');
    await expect(page.locator('.research-panel-title')).toHaveText('旅行规划已取消');
    await expect(page.getByText('这次规划已取消。', { exact: true })).toBeVisible();
    await expectPlanningCardWithoutDuplicateCopy(page, '已结束');
    await expect(page.getByText(/正在规划你的旅行|正在准备相关查询/)).toHaveCount(0);
  });

  test('停止请求落定前也不显示仍在规划', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/e2e/fixtures/generation-progress.html');
    await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.requestCancelAfterPlanning());
    await expect(page.locator('.generation-progress > h2')).toHaveText('正在停止规划');
    await expect(page.locator('.research-panel-title')).toHaveText('正在停止规划');
    await expect(page.getByText('正在停止这次规划。', { exact: true })).toBeVisible();
    await expectPlanningCardWithoutDuplicateCopy(page, '已结束');
    await expect(page.getByText(/正在规划你的旅行|正在准备相关查询/)).toHaveCount(0);
  });

  test('390px 失败卡片仍只显示名称、状态与唯一说明', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/e2e/fixtures/generation-progress.html');
    await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.failAfterPlanning());
    await expectPlanningCardWithoutDuplicateCopy(page, '已结束');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.locator('.generation-activity').scrollIntoViewIfNeeded();
    await expect(page.getByTestId('research-agent-planning')).toBeInViewport();
    await page.screenshot({ path: '../output/polish/20261029-1252-generation-layout/generation-390-failed-r3.png' });
  });
});
