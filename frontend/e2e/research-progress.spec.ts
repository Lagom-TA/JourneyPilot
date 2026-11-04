import { test, expect, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

const EVIDENCE_DIR = '../test-results/e2e-evidence/process-disclosure';

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

// 尚无研究行动时过程区保持紧凑：不渲染角色卡片，也不出现旧版过程文案。
async function expectCompactProcessWithoutCards(page: Page) {
  await expect(page.locator('.research-agent')).toHaveCount(0);
  await expect(page.getByText(/理解偏好|旅行需求已整理|正在准备相关查询/)).toHaveCount(0);
  await expect(page.locator('.research-agent-description')).toHaveCount(0);
}

// 过程区默认收起，用户点开标题后才显示各阶段卡片。
async function expandProcessPanel(page: Page) {
  await page.locator('[data-testid="thinking-chain"] button.research-panel-heading').click();
}

for (const width of [320, 390, 1440]) {
  test(`研究面板：串行阶段、有效详情、停止状态 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/e2e/fixtures/research-progress.html');
    const panel = page.getByTestId('thinking-chain');
    await expect(panel).toContainText('查找旅行资料');
    const destination = page.getByTestId('research-agent-destination');
    await expect(destination).toBeVisible();
    // 串行研究：目的地进行中时，交通与住宿还没有开始。
    await expect(page.getByTestId('research-agent-transport')).toHaveCount(0);
    await expect(page.getByTestId('research-agent-stay')).toHaveCount(0);
    await expect(panel).not.toContainText('research_packet_id');
    await expect(destination.getByRole('button')).toHaveCount(1);
    await expect(destination.getByRole('button')).toHaveAttribute('aria-expanded', 'true');
    const query = destination.getByTestId('research-query');
    await expect(query).toContainText('找到 1 个结果');
    await expect(query.locator('.research-source')).not.toBeVisible();
    await query.locator('summary').click();
    await expect(query.locator('[data-detail-section="input"]')).toContainText('长春 历史博物馆');
    await expect(query).toContainText('长春市宽城区光复北路');
    await expect(query.getByRole('link', { name: '伪满皇宫博物院' })).toHaveAttribute('href', 'https://example.org/museum');
    await expect(destination.getByTestId('research-query')).toHaveCount(1);
    await page.getByRole('button', { name: '目的地完成', exact: true }).click();
    await expect(destination.locator('.research-agent-state')).toHaveText('已结束');
    await expect(destination.getByTestId('research-query')).toHaveCount(0);
    const transport = page.getByTestId('research-agent-transport');
    await expect(transport.locator('.research-agent-state')).toHaveText('进行中');
    await page.getByRole('button', { name: '交通完成', exact: true }).click();
    await expect(transport.locator('.research-agent-state')).toHaveText('已结束');
    const stay = page.getByTestId('research-agent-stay');
    await expect(stay.getByRole('button')).toHaveCount(1);
    const stayRows = stay.getByTestId('research-query');
    await expect(stayRows).toHaveCount(2);
    await expect(stayRows.first()).toContainText('找到 1 个结果');
    await expect(stayRows.first().locator('summary')).toHaveCount(0);
    await expect(stayRows.nth(1)).toContainText('暂不可查');
    await page.getByRole('button', { name: '停止', exact: true }).click();
    await expect(panel).toContainText('旅行规划已中断');
    await expect(stay.locator('.research-agent-state')).toHaveText('已停止');
    await destination.getByRole('button').click();
    await destination.getByTestId('research-query').locator('summary').click();
    await expect(destination.getByRole('link', { name: '伪满皇宫博物院' })).toBeVisible();
    await expect(destination.getByTestId('research-query')).toContainText('伪满皇宫博物院');
    await page.getByRole('button', { name: '住宿直接返回', exact: true }).click();
    await expect(stay.locator('.research-agent-state')).toHaveText('已结束');
    await expect(stay.getByTestId('research-query')).toHaveCount(0);
    await stay.getByRole('button').click();
    await expect(stay).toContainText('已整理 1 个住宿候选');
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
  // 串行推进到住宿阶段，三个角色卡片都已出现。
  await page.getByRole('button', { name: '目的地完成', exact: true }).click();
  await page.getByRole('button', { name: '交通完成', exact: true }).click();
  await expect(panel.locator('button.research-agent-heading[aria-expanded]')).toHaveCount(3);
  const transport = page.getByTestId('research-agent-transport');
  const stageHeight = await transport.locator('.research-agent-heading').evaluate(element => element.getBoundingClientRect().height);
  expect(stageHeight).toBeGreaterThanOrEqual(30);
  expect(stageHeight).toBeLessThanOrEqual(38);
  // 交通完成态会自动收起卡片，重新展开后再量查询行高。
  await transport.locator('button.research-agent-heading').click();
  const row = transport.getByTestId('research-query').locator('.research-query-summary').first();
  await expect(row).toBeVisible();
  const rowHeight = await row.evaluate(element => element.getBoundingClientRect().height);
  expect(rowHeight).toBeGreaterThanOrEqual(40);
  expect(rowHeight).toBeLessThanOrEqual(48);
  const geometry = await page.evaluate(() => {
    const research = document.querySelector<HTMLElement>('.research-panel-workspace')!;
    const rect = research.getBoundingClientRect();
    const style = getComputedStyle(research);
    return { width: Math.round(rect.width), left: Math.round(rect.left), border: style.borderTopWidth, shadow: style.boxShadow, overflow: document.documentElement.scrollWidth - innerWidth };
  });
  expect(geometry.width).toBeGreaterThanOrEqual(900);
  expect(geometry.width).toBeLessThanOrEqual(1044);
  expect(Number.parseFloat(geometry.border)).toBe(0);
  expect(geometry.shadow).toBe('none');
  expect(geometry.overflow).toBeLessThanOrEqual(1);

  await page.getByRole('button', { name: '内部工具', exact: true }).click();
  // search_tools 是内部能力选择，不再作为旅行行动出现在过程区。
  await expect(page.getByTestId('research-query').filter({ hasText: '已选择适合本次行程的地点与交通资料' })).toHaveCount(0);
  await expect(page.getByTestId('research-agent-planning')).toHaveCount(0);
  await expect(panel).not.toContainText('global_place_search');
  await page.screenshot({ path: `${EVIDENCE_DIR}/workspace-2000-compact-list.png` });

  await page.getByRole('button', { name: '长查询', exact: true }).click();
  // 目的地完成态自动收起，重新展开后再核对新追加的查询行。
  await page.getByTestId('research-agent-destination').locator('button.research-agent-heading').click();
  const longRow = page.getByTestId('research-query').filter({ hasText: '找到 1 个适合雨天散步的街区' });
  await expect(longRow).toContainText('找到 1 个适合雨天散步的街区');
  await longRow.locator('summary').focus();
  await page.keyboard.press('Enter');
  await expect(longRow.locator('[data-detail-section="input"]')).toContainText('杭州西湖周边适合雨天慢慢散步、喝咖啡并避开人群的路线与街区');
  await expect(longRow.getByRole('link', { name: '北山街雨天散步路线' })).toBeVisible();
  await expect(longRow.locator('.research-query-title')).toHaveCSS('white-space', 'normal');
  await page.screenshot({ path: `${EVIDENCE_DIR}/workspace-2000-expanded-query.png` });
  await longRow.locator('summary').click();

  await page.getByRole('button', { name: '路线阶段', exact: true }).click();
  await expect(panel.locator('.research-panel-title')).toHaveText('安排每天路线');
  await page.screenshot({ path: `${EVIDENCE_DIR}/workspace-2000-route-stage.png` });
  await page.getByRole('button', { name: '生成阶段', exact: true }).click();
  await expect(panel.locator('.research-panel-title')).toHaveText('生成完整计划');
  await page.screenshot({ path: `${EVIDENCE_DIR}/workspace-2000-delivery-stage.png` });

  await page.setViewportSize({ width: 390, height: 844 });
  const phoneRow = page.getByTestId('research-query').filter({ hasText: '找到 1 个适合雨天散步的街区' });
  await phoneRow.locator('summary').click();
  await expect(phoneRow.getByRole('link', { name: '北山街雨天散步路线' })).toBeVisible();
  await expect(phoneRow.locator('.research-tool-input-value')).toContainText('杭州西湖周边适合雨天慢慢散步');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${EVIDENCE_DIR}/workspace-390-expanded-query.png`, fullPage: true });
  mkdirSync(EVIDENCE_DIR, { recursive: true });
  writeFileSync(`${EVIDENCE_DIR}/desktop-measurements.json`, JSON.stringify({ stageHeight, rowHeight, workspace: geometry, phoneOverflow: await page.evaluate(() => document.documentElement.scrollWidth - innerWidth) }, null, 2));
});

test('workspace 激活摘要、真实计数、安全详情与后续事件保持展开', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/e2e/fixtures/research-progress.html');
  const panel = page.getByTestId('thinking-chain');

  await page.getByRole('button', { name: '激活摘要', exact: true }).click();
  await page.getByRole('button', { name: '边界详情', exact: true }).click();
  await page.getByRole('button', { name: '长查询', exact: true }).click();
  await page.screenshot({ path: `${EVIDENCE_DIR}/workspace-2000-running-activity.png` });
  // 内部能力激活不再进入过程区，也不再生成 planning 卡片。
  await expect(page.getByTestId('research-query').filter({ hasText: '已启用' })).toHaveCount(0);
  await expect(page.getByTestId('research-agent-planning')).toHaveCount(0);

  const fourResults = page.getByTestId('research-query').filter({ hasText: '找到 4 个结果：深圳湾公园、红树林、人才公园、海上世界' });
  await expect(fourResults.locator('summary')).toHaveCount(1);
  await fourResults.locator('summary').click();
  await expect(fourResults).not.toContainText('返回 4 条结果');
  await expect(fourResults).not.toContainText('返回 2 条结果');
  await expect(fourResults).toContainText('找到 4 个结果：深圳湾公园、红树林、人才公园、海上世界');
  await expect(fourResults.locator('.research-source')).toHaveCount(2);
  await fourResults.locator('.research-tool-detail').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${EVIDENCE_DIR}/workspace-2000-expanded-place.png` });

  const onlySummary = page.getByTestId('research-query').filter({ hasText: '已整理 3 条适合雨天的室内活动摘要' });
  await onlySummary.locator('summary').click();
  await expect(onlySummary.locator('[data-detail-section="input"]')).toContainText('当地雨天备选活动');
  await expect(onlySummary).toContainText('已整理 3 条适合雨天的室内活动摘要');
  await expect(onlySummary).not.toContainText('返回 ');
  await expect(onlySummary.locator('.research-source')).toHaveCount(0);

  const noInputResult = page.getByTestId('research-query').filter({ hasText: '已读取数据' });
  await expect(noInputResult.locator('summary')).toHaveCount(0);
  await expect(noInputResult.locator('[data-detail-section="input"]')).toHaveCount(0);
  await expect(noInputResult.locator('[data-detail-section="result"]')).toHaveCount(0);

  const jsonLeak = page.getByTestId('research-query').filter({ hasText: '已读取联网资料' });
  await jsonLeak.locator('summary').click();
  await expect(jsonLeak).toContainText('无结果');
  for (const leaked of ['success', 'secret', 'tavily_search']) {
    await expect(jsonLeak).not.toContainText(leaked);
  }

  const machineInput = page.getByTestId('research-query').filter({ hasText: '机器载荷输入已过滤' });
  await expect(machineInput.locator('summary')).toHaveCount(0);
  await expect(machineInput.locator('[data-detail-section="input"]')).toHaveCount(0);
  for (const leaked of ['success', 'provider', 'tavily_search', 'sanitized_result', 'contract_version']) {
    await expect(machineInput).not.toContainText(leaked);
  }

  const contractInput = page.getByTestId('research-query').filter({ hasText: '合同字段输入已过滤' });
  await expect(contractInput.locator('summary')).toHaveCount(0);
  await expect(contractInput.locator('[data-detail-section="input"]')).toHaveCount(0);
  for (const leaked of ['contract_version', 'research_packet_id', 'packet-1', 'tool_call_id']) {
    await expect(contractInput).not.toContainText(leaked);
  }

  const internalInput = page.getByTestId('research-query').filter({ hasText: '内部标识输入已转换' });
  await internalInput.locator('summary').click();
  await expect(internalInput.locator('.research-tool-input-value')).toHaveText('地点搜索 网页搜索 附近景点');
  for (const leaked of ['global_place_search', 'brave_web_search', 'tavily_search']) {
    await expect(internalInput).not.toContainText(leaked);
  }

  const errorInput = page.getByTestId('research-query').filter({ hasText: '异常文本输入已过滤' });
  await expect(errorInput.locator('summary')).toHaveCount(0);
  for (const leaked of ['Traceback', 'File', 'line 42', 'agent.py']) {
    await expect(errorInput).not.toContainText(leaked);
  }

  const longRow = page.getByTestId('research-query').filter({ hasText: '找到 1 个适合雨天散步的街区' });
  await longRow.locator('summary').focus();
  await page.keyboard.press('Enter');
  await expect(longRow.getByRole('link', { name: '北山街雨天散步路线' })).toBeVisible();
  await expect(longRow.locator('.research-tool-input-value')).toContainText('上午、午后和傍晚三个时间段的具体安排');

  // 阶段完成后自动收起；用户主动展开可继续查看正常结果，无关事件不会再次收起。
  await expect(fourResults.locator('.research-tool-detail')).toBeVisible();
  const scrollBefore = await page.evaluate(() => window.scrollY);
  await page.getByRole('button', { name: '目的地完成', exact: true }).click();
  const destination = page.getByTestId('research-agent-destination');
  await expect(destination.locator('.research-agent-state')).toHaveText('已结束');
  await expect(destination.locator('.research-agent-body')).toHaveCount(0);
  await destination.getByRole('button').click();
  const reopened = destination.getByTestId('research-query').filter({ hasText: '找到 4 个结果：深圳湾公园、红树林、人才公园、海上世界' });
  await reopened.locator('summary').click();
  await expect(reopened.locator('.research-tool-detail')).toBeVisible();
  await expect(reopened).not.toContainText('返回 4 条结果');
  await page.getByRole('button', { name: '无关事件', exact: true }).click();
  await expect(reopened.locator('.research-tool-detail')).toBeVisible();
  expect(await page.evaluate(() => window.scrollY)).toBe(scrollBefore);

  await page.getByRole('button', { name: '全部结束', exact: true }).click();
  await expect(destination.locator('.research-agent-body')).toHaveCount(0);
  await expect(panel.locator('.research-panel-title')).toHaveText('旅行规划已完成');
  await page.screenshot({ path: `${EVIDENCE_DIR}/workspace-2000-completed-activity.png` });

  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});

type GenerationFixtureWindow = Window & { __generationFixture?: { addResearch: () => void; compositionRedo: () => void; compositionContinue: () => void; longTitle: () => void; longPlaceName: () => void; specialParty: () => void; stop: () => void; finish: () => void; failAfterPlanning: () => void; cancelAfterPlanning: () => void; requestCancelAfterPlanning: () => void } };

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
    { type: 'thinking', message_id: 'assistant-generation-sse', agent_name: '制定计划', content: '制定调研计划：目的地调研 → 交通查询 → 住宿查询 → 行程规划', step_name: '制定规划安排', ts_ms: ts + 1 },
    { type: 'thinking', message_id: 'assistant-generation-sse', agent_name: '安排查询', content: '正在按顺序安排调研任务', step_name: '安排旅行查询', ts_ms: ts + 2 },
    { type: 'agent_progress', message_id: 'assistant-generation-sse', agent_name: '整理需求', content: '已整理旅行偏好与同行信息', step_name: '整理旅行需求', progress_status: 'completed', ts_ms: ts + 3 },
    { type: 'tool_start', message_id: 'assistant-generation-sse', agent_name: '目的地调研', tool_name: 'global_place_search', tool_call_id: 'sse-place', args_summary: '{"query":"青岛 海岸线"}', category: 'search', ts_ms: ts + 4 },
    { type: 'tool_result', message_id: 'assistant-generation-sse', agent_name: '目的地调研', tool_name: 'global_place_search', tool_call_id: 'sse-place', status: 'success', summary: '找到 1 个结果', result_preview: [{ title: '小麦岛公园', detail: '适合傍晚看海与散步', url: 'https://example.org/qingdao-coast' }], category: 'search', ts_ms: ts + 5 },
  ]);
  const planning = page.getByTestId('research-agent-planning');
  const destinationPanel = page.getByTestId('research-agent-destination');
  await expandProcessPanel(page);
  // 研究阶段视图里，已完成的目的地卡片保持收起，点开后工具结果可见。
  await expect(destinationPanel.locator('.research-agent-body')).toHaveCount(0);
  await destinationPanel.getByRole('button').click();
  await expect(destinationPanel).toContainText('找到 1 个结果');
  await fixture.push([{ type: 'run_failed', run_id: 'run-generation-sse', message: '离线合成：真实 thinking 事件形状后规划失败。', run_status: 'failed', ts_ms: ts + 6 }]);
  await expect(page.locator('.generation-progress > h2')).toHaveText('旅行规划未完成');
  // 右侧过程区标题跟随所属阶段；Run 终态由左侧进度标题表达。
  await expect(page.locator('.research-panel-title')).toHaveText('查找旅行资料');
  // 制定计划文本属于需求整理阶段：选择该阶段后再核对规划卡。
  await page.locator('.generation-progress li').first().getByRole('button').click();
  await expect(planning.locator('.research-agent-state')).toHaveText('已结束');
  await expect(planning.getByTestId('research-agent-update')).toHaveCount(0);
  await expect(planning).not.toContainText('正在按顺序安排调研任务');
  await expect(planning).not.toContainText('正在准备相关查询');
  await expect(planning.locator('.research-agent-body')).toHaveCount(0);
  await planning.getByRole('button').click();
  await expect(planning.locator('.research-agent-body')).toContainText('制定调研计划：目的地调研 → 交通查询 → 住宿查询 → 行程规划');
  await expect(planning.locator('.research-agent-body')).not.toContainText('正在按顺序安排调研任务');
  // 回到研究阶段核对目的地记录。
  await page.locator('.generation-progress li').nth(1).getByRole('button').click();
  await expect(destinationPanel.locator('.research-agent-body')).toHaveCount(0);
  await destinationPanel.getByRole('button').click();
  await expect(destinationPanel).toContainText('找到 1 个结果');
  await destinationPanel.getByTestId('research-query').locator('summary').click();
  await expect(destinationPanel.locator('[data-detail-section="input"]')).toContainText('青岛 海岸线');
  await expect(destinationPanel).not.toContainText('返回 1 条结果');
  await expect(destinationPanel.getByRole('link', { name: '小麦岛公园' })).toBeVisible();
  await page.screenshot({ path: `${EVIDENCE_DIR}/generation-2000-failed-expanded.png` });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.generation-activity').scrollIntoViewIfNeeded();
  await expect(planning).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${EVIDENCE_DIR}/generation-390-failed.png` });
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
    { type: 'thinking', message_id: 'assistant-generation-sse-cancel', agent_name: '制定计划', content: '制定调研计划：目的地调研 → 交通查询 → 住宿查询 → 行程规划', step_name: '制定规划安排', ts_ms: ts + 1 },
    { type: 'thinking', message_id: 'assistant-generation-sse-cancel', agent_name: '安排查询', content: '正在按顺序安排调研任务', step_name: '安排旅行查询', ts_ms: ts + 2 },
  ]);
  await fixture.push([{ type: 'run_cancelled', run_id: 'run-generation-sse-cancel', final_content: '离线合成：真实 thinking 事件形状后取消。', ts_ms: ts + 3 }]);
  await expect(page.locator('.generation-progress > h2')).toHaveText('旅行规划已取消');
  await expect(page.locator('.research-panel-title')).toHaveText('查找旅行资料');
  await expandProcessPanel(page);
  // 制定计划文本属于需求整理阶段：Run 已进入资料阶段后取消，
  // 已离开的需求阶段显示已结束，而不是继续保留“进行中/已停止”。
  await page.locator('.generation-progress li').first().getByRole('button').click();
  const planning = page.getByTestId('research-agent-planning');
  await expect(planning.locator('.research-agent-state')).toHaveText('已结束');
  await expect(planning).not.toContainText('正在按顺序安排调研任务');
  await expect(planning.locator('.research-agent-body')).toHaveCount(0);
  await planning.getByRole('button').click();
  await expect(planning.locator('.research-agent-body')).toContainText('制定调研计划：目的地调研 → 交通查询 → 住宿查询 → 行程规划');
  await expect(planning.locator('.research-agent-body')).not.toContainText('正在按顺序安排调研任务');
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
    await expectCompactProcessWithoutCards(page);
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
    expect(geometry.research / geometry.activity).toBeGreaterThan(0.55);
    expect(geometry.research).toBeGreaterThan(900);
    expect(geometry.research).toBeLessThanOrEqual(1044);
    const active = page.locator('.generation-progress li.is-active');
    await expect(active).toHaveCount(1);
    const motion = await active.evaluate((element) => {
      const style = getComputedStyle(element, '::before');
      return { name: style.animationName, duration: style.animationDuration };
    });
    expect(motion.name).toBe('generation-stage-sweep');
    expect(Number.parseFloat(motion.duration)).toBeGreaterThanOrEqual(3);
    await page.screenshot({ path: '../test-results/e2e-evidence/generation-layout/generation-2000-waiting.png' });
    await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.addResearch());
    await expandProcessPanel(page);
    // 规划卡记录属于需求整理阶段：先选该阶段核对，再回到研究阶段看角色卡片。
    await page.locator('.generation-progress li').first().getByRole('button').click();
    await expectPlanningCardWithoutDuplicateCopy(page, '已结束');
    await page.locator('.generation-progress li').nth(1).getByRole('button').click();
    const destination = page.getByTestId('research-agent-destination');
    const transport = page.getByTestId('research-agent-transport');
    await expect(destination.getByTestId('research-agent-update')).toHaveCount(0);
    await expect(transport.getByTestId('research-agent-update')).toHaveCount(0);
    await expect(transport).toContainText('上海虹桥 -> 杭州东');
    await expect(page.locator('.research-agent-description')).toHaveCount(0);
    await page.screenshot({ path: '../test-results/e2e-evidence/generation-layout/generation-2000-research-r3.png' });
    await transport.getByTestId('research-query').locator('summary').click();
    await expect(transport).toContainText('已整理上海到杭州的火车衔接');
    await expect(transport.getByRole('link', { name: '上海虹桥 → 杭州东' })).toBeVisible();
    await page.screenshot({ path: '../test-results/e2e-evidence/generation-layout/generation-2000-research-r3-details.png' });
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
    await page.screenshot({ path: '../test-results/e2e-evidence/generation-layout/generation-2000-long-title.png' });
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
    await page.screenshot({ path: '../test-results/e2e-evidence/compact-tool-activity/generation-1440-active.png' });
    await expect(page.locator('.generation-progress')).toHaveAttribute('data-active', 'true');
    await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.stop());
    await expect(page.locator('.generation-progress')).toHaveAttribute('data-active', 'false');
    await expect(page.locator('.generation-progress li.is-active')).toHaveCount(0);
    await expect(page.locator('.generation-progress > h2')).toHaveText('旅行规划已取消');
    await expect(page.locator('.research-panel-title')).toHaveText('整理旅行需求');
    await expectCompactProcessWithoutCards(page);
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
    await expandProcessPanel(page);
    await expect(page.getByTestId('research-agent-destination')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const order = await page.evaluate(() => {
      const card = document.querySelector('.generation-trip-card')!.getBoundingClientRect();
      const activity = document.querySelector('.generation-activity')!.getBoundingClientRect();
      return { cardBottom: card.bottom, activityTop: activity.top };
    });
    expect(order.activityTop).toBeGreaterThanOrEqual(order.cardBottom - 1);
    await page.screenshot({ path: '../test-results/e2e-evidence/generation-layout/generation-390-phone.png', fullPage: true });
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
    await expect(page.locator('.research-panel-title')).toHaveText('整理旅行需求');
    await expectCompactProcessWithoutCards(page);
    await page.screenshot({ path: '../test-results/e2e-evidence/generation-layout/generation-2000-failed-r3.png' });
    expect(errors).toEqual([]);
  });

  test('取消后阶段卡不承诺继续准备', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/e2e/fixtures/generation-progress.html');
    await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.cancelAfterPlanning());
    await expect(page.locator('.generation-progress > h2')).toHaveText('旅行规划已取消');
    await expect(page.locator('.research-panel-title')).toHaveText('整理旅行需求');
    await expect(page.getByText('这次规划已取消。', { exact: true })).toBeVisible();
    await expectCompactProcessWithoutCards(page);
    await expect(page.getByText(/正在规划你的旅行|正在准备相关查询/)).toHaveCount(0);
  });

  test('停止请求落定前也不显示仍在规划', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/e2e/fixtures/generation-progress.html');
    await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.requestCancelAfterPlanning());
    await expect(page.locator('.generation-progress > h2')).toHaveText('正在停止规划');
    await expect(page.locator('.research-panel-title')).toHaveText('整理旅行需求');
    await expect(page.getByText('正在停止这次规划。', { exact: true })).toBeVisible();
    await expectCompactProcessWithoutCards(page);
    await expect(page.getByText(/正在规划你的旅行|正在准备相关查询/)).toHaveCount(0);
  });

  test('390px 失败卡片仍只显示名称、状态与唯一说明', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/e2e/fixtures/generation-progress.html');
    await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.failAfterPlanning());
    await expectCompactProcessWithoutCards(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.locator('.generation-activity').scrollIntoViewIfNeeded();
    await expect(page.getByTestId('thinking-chain')).toBeInViewport();
    await page.screenshot({ path: '../test-results/e2e-evidence/generation-layout/generation-390-failed-r3.png' });
  });
});

test('内部失败、未匹配与激活失败不进入过程展示，成功空结果仍可查看', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/e2e/fixtures/research-progress.html');
  const panel = page.getByTestId('thinking-chain');
  await page.getByRole('button', { name: '内部失败', exact: true }).click();

  for (const leaked of ['失败调用不应展示', 'HTTP 500', '失败预览不应展示', 'secret-token', '未匹配到工具', '工具激活失败', '内部错误不应展示']) {
    await expect(panel).not.toContainText(leaked);
  }
  await expect(panel.locator('[title*="失败调用不应展示"]')).toHaveCount(0);
  const emptySuccess = page.getByTestId('research-query').filter({ hasText: '没有返回结果' });
  await expect(emptySuccess).toBeVisible();
  await expect(emptySuccess).toContainText('无结果');
  await expect(panel.getByTestId('research-query').filter({ hasText: '内部失败' })).toHaveCount(0);
  await page.screenshot({ path: `${EVIDENCE_DIR}/workspace-2000-internal-failures-hidden.png` });
  mkdirSync(EVIDENCE_DIR, { recursive: true });
  writeFileSync(`${EVIDENCE_DIR}/failure-visibility.json`, JSON.stringify({
    visibleText: await panel.innerText(),
    hiddenDomMatches: await panel.locator('text=失败调用不应展示').count(),
    failedPreviewDom: await panel.locator('[title*="失败预览不应展示"]').count(),
    successfulEmptyVisible: await emptySuccess.isVisible(),
  }, null, 2));
  expect(errors).toEqual([]);
});

test('阶段先有正常结果后失败仍按真实生命周期结束并自动折叠，失败正文不泄露', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/e2e/fixtures/research-progress.html');
  const panel = page.getByTestId('thinking-chain');
  await page.getByRole('button', { name: '结果后失败', exact: true }).click();
  const destination = page.getByTestId('research-agent-destination');
  await expect(destination.locator('.research-agent-state')).toHaveText('未完成');
  await expect(destination.locator('.research-agent-body')).toHaveCount(0);
  await expect(panel).not.toContainText('阶段失败正文不应展示');
  await destination.getByRole('button').click();
  await expect(destination.locator('.research-agent-body')).toContainText('伪满皇宫博物院');
  await expect(destination).not.toContainText('阶段失败正文不应展示');
  mkdirSync(EVIDENCE_DIR, { recursive: true });
  writeFileSync(`${EVIDENCE_DIR}/failed-after-result.json`, JSON.stringify({
    status: await destination.locator('.research-agent-state').innerText(),
    bodyVisibleAfterFailure: await destination.locator('.research-agent-body').count(),
    leakedFailureCopy: await panel.getByText('阶段失败正文不应展示').count(),
  }, null, 2));
  await page.screenshot({ path: `${EVIDENCE_DIR}/process-2000-failed-after-result.png`, fullPage: true });
});

test('同 Run 补充轮次重新展开阶段并隔离旧轮次工具详情', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/e2e/fixtures/research-progress.html');
  const destination = page.getByTestId('research-agent-destination');
  const oldRow = destination.getByTestId('research-query').filter({ hasText: '找到 1 个结果' });
  await oldRow.locator('summary').click();
  await expect(oldRow.getByRole('link', { name: '伪满皇宫博物院' })).toBeVisible();
  await page.getByRole('button', { name: '目的地完成', exact: true }).click();
  await expect(destination.locator('.research-agent-state')).toHaveText('已结束');
  await expect(destination.locator('.research-agent-body')).toHaveCount(0);

  await page.getByRole('button', { name: '补充轮次', exact: true }).click();
  await expect(destination.locator('.research-agent-state')).toHaveText('进行中');
  await expect(destination.locator('button.research-agent-heading')).toHaveAttribute('aria-expanded', 'true');
  await expect(destination.locator('.research-agent-body')).toContainText('吉林省博物院');
  await expect(oldRow.locator('.research-tool-detail')).not.toBeVisible();
  const newRow = destination.getByTestId('research-query').filter({ hasText: '找到 2 个结果' });
  await expect(newRow.getByRole('link', { name: '吉林省博物院' })).not.toBeVisible();
  await newRow.locator('summary').click();
  await expect(newRow.getByRole('link', { name: '吉林省博物院' })).toBeVisible();
  mkdirSync(EVIDENCE_DIR, { recursive: true });
  writeFileSync(`${EVIDENCE_DIR}/supplement-round-reset.json`, JSON.stringify({
    status: await destination.locator('.research-agent-state').innerText(),
    ariaExpanded: await destination.locator('button.research-agent-heading').getAttribute('aria-expanded'),
    oldRoundDetailVisible: await oldRow.locator('.research-tool-detail').isVisible(),
    newRoundDetailVisible: await newRow.locator('.research-tool-detail').isVisible(),
  }, null, 2));
  await page.screenshot({ path: `${EVIDENCE_DIR}/process-2000-supplement-round.png`, fullPage: true });
});

// 组合补查 → 反馈目的地返研 → 返研后继续组合：三个环节在同一过程区可见。
test('组合补查、反馈返研与返研后继续组合在同一工作台可见', async ({ page }) => {
  const redoEvidenceDir = '../test-results/e2e-evidence/generation-04-composition-feedback/e2e';
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/e2e/fixtures/research-progress.html');
  await page.getByRole('button', { name: '组合返研', exact: true }).click();
  const composition = page.getByTestId('research-agent-itinerary');
  const destination = page.getByTestId('research-agent-destination');
  // 组合卡：先补查路线，再以返研结论作为里程碑，返研后回到进行中。
  await expect(composition.locator('.research-agent-body')).toContainText('门到门 25 分钟');
  await expect(composition.locator('.research-agent-body')).toContainText('已要求按反馈重做');
  await expect(composition.locator('.research-agent-state')).toHaveText('进行中');
  // 目的地卡回到进行中，返研轮的查询行可展开。
  await expect(destination.locator('.research-agent-state')).toHaveText('进行中');
  await expect(destination.locator('.research-agent-body')).toContainText('长影旧址博物馆');
  const redoRow = destination.getByTestId('research-query').filter({ hasText: '找到 2 个结果' });
  await redoRow.locator('summary').click();
  await expect(redoRow.getByRole('link', { name: '长影旧址博物馆' })).toBeVisible();
  mkdirSync(redoEvidenceDir, { recursive: true });
  writeFileSync(`${redoEvidenceDir}/composition-redo-progress.json`, JSON.stringify({
    compositionState: await composition.locator('.research-agent-state').innerText(),
    destinationState: await destination.locator('.research-agent-state').innerText(),
    redoMilestoneVisible: await composition.getByText('已要求按反馈重做').count(),
    redoToolRowVisible: await destination.getByText('长影旧址博物馆').count(),
  }, null, 2));
  await page.screenshot({ path: `${redoEvidenceDir}/process-2000-composition-redo.png`, fullPage: true });
});

// 真实生成工作台面板上的返研：重做轮归并进同一张目的地卡，过程区焦点
// 在重做期间回到研究，继续组合后回到路线并展示组合卡。
test('生成工作台面板把返研重做过程留在当前活动区并归并轮次', async ({ page }) => {
  const redoEvidenceDir = '../test-results/e2e-evidence/generation-04-composition-feedback/e2e';
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/e2e/fixtures/generation-progress.html');
  await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.addResearch());
  await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.compositionRedo());
  await expandProcessPanel(page);
  // 重做轮归并进目的地卡，不是一张新卡；返研工具行可见。
  const destination = page.getByTestId('research-agent-destination');
  await expect(destination).toBeVisible();
  await expect(destination.locator('.research-agent-state')).toHaveText('进行中');
  await expect(destination.locator('.research-agent-body')).toContainText('长影旧址博物馆');
  await expect(page.getByTestId('research-agent-destination（第2轮补充）')).toHaveCount(0);
  // 重做期间过程区焦点回到研究：返研内容在当前活动区可见。
  await expect(page.locator('.generation-activity')).toContainText('长影旧址博物馆');
  // 继续组合后焦点回到路线，组合卡带着补查行与返研结论出现。
  await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.compositionContinue());
  const composition = page.getByTestId('research-agent-itinerary');
  await expect(composition).toBeVisible();
  if (await composition.locator('.research-agent-body').count() === 0) {
    await composition.locator('button.research-agent-heading').click();
  }
  await expect(composition.locator('.research-agent-body')).toContainText('门到门 25 分钟');
  await expect(composition.locator('.research-agent-body')).toContainText('已要求按反馈重做');
  await expect(composition.locator('.research-agent-state')).toHaveText('进行中');
  await expect(page.locator('.generation-activity')).not.toContainText('长影旧址博物馆');
  // 焦点回到路线：研究阶段的卡片退出当前活动区（可从左侧阶段切回查看）。
  await expect(page.getByTestId('research-agent-destination')).toHaveCount(0);
  mkdirSync(redoEvidenceDir, { recursive: true });
  await page.screenshot({ path: `${redoEvidenceDir}/generation-panel-composition-redo.png`, fullPage: true });
  expect(errors).toEqual([]);
});

test('新 Run 不继承旧 Run 的工具详情展开状态', async ({ page }) => {
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/e2e/fixtures/research-progress.html');
  await page.getByRole('button', { name: '长查询', exact: true }).click();
  const longRow = page.getByTestId('research-query').filter({ hasText: '找到 1 个适合雨天散步的街区' });
  await longRow.locator('summary').click();
  await expect(longRow.getByRole('link', { name: '北山街雨天散步路线' })).toBeVisible();
  await page.getByRole('button', { name: '新 Run', exact: true }).click();
  const newRunRow = page.getByTestId('research-query').filter({ hasText: '找到 1 个适合雨天散步的街区' });
  await expect(newRunRow.locator('.research-tool-detail')).not.toBeVisible();
  const newRunDetailVisibleBeforeClick = await newRunRow.locator('.research-tool-detail').isVisible();
  await newRunRow.locator('summary').click();
  await expect(newRunRow.getByRole('link', { name: '北山街雨天散步路线' })).toBeVisible();
  await page.screenshot({ path: `${EVIDENCE_DIR}/workspace-2000-new-run-reset.png` });
  writeFileSync(`${EVIDENCE_DIR}/new-run-reset.json`, JSON.stringify({
    oldRunExpanded: true,
    newRunDetailVisibleBeforeClick,
  }, null, 2));
});

test('侧栏多城站序、无重复信息与特殊同行 2000px/390px', async ({ page }) => {
  const evidence = '../test-results/e2e-evidence/planning-summary';
  expect(typeof evidence).toBe('string');
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/e2e/fixtures/generation-progress.html');
  const card = page.locator('.generation-trip-card');
  const title = card.locator('.generation-trip-card-header h1');
  await expect(title.locator('.generation-trip-title-place')).toHaveText(['北京', '上海', '长春']);
  await expect(title).toContainText('11 日');
  const facts = card.locator('.generation-trip-card-meta');
  await expect(facts).toContainText('深圳出发');
  await expect(facts).toContainText('2 位成人');
  await expect(card).not.toContainText('目的地');
  await expect(card).not.toContainText('行程');
  await expect(card.locator('.generation-trip-tags')).toContainText('经典均衡');
  await page.screenshot({ path: `${evidence}/generation-2000-three-cities.png`, fullPage: true });

  await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.specialParty());
  await expect(facts).toContainText('2 位成人 · 1 位儿童 · 有长辈同行 · 需要无障碍安排');
  await expect(card.locator('.generation-trip-tags')).toContainText('轻松慢游');
  await page.screenshot({ path: `${evidence}/generation-2000-special-party.png`, fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(facts).toContainText('1 位儿童');
  const order = await page.evaluate(() => {
    const trip = document.querySelector('.generation-trip-card')!.getBoundingClientRect();
    const activity = document.querySelector('.generation-activity')!.getBoundingClientRect();
    return { cardBottom: trip.bottom, activityTop: activity.top };
  });
  expect(order.activityTop).toBeGreaterThanOrEqual(order.cardBottom - 1);
  await page.screenshot({ path: `${evidence}/generation-390-special-party.png`, fullPage: true });

  await page.setViewportSize({ width: 2000, height: 880 });
  await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.longTitle());
  await expect(title.locator('.generation-trip-title-place')).toHaveCount(5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${evidence}/generation-2000-five-long-cities.png`, fullPage: true });
  mkdirSync(evidence, { recursive: true });
  writeFileSync(`${evidence}/sidebar-geometry.json`, JSON.stringify({
    stationOrder: await title.locator('.generation-trip-title-place').allTextContents(),
    factsText: await card.locator('.generation-trip-card-meta').innerText(),
    overflow: await page.evaluate(() => document.documentElement.scrollWidth - innerWidth),
  }, null, 2));
});

test('390px 合法超长城市名可在侧栏换行，不覆盖天数或操作', async ({ page }) => {
  const evidence = '../test-results/e2e-evidence/planning-summary';
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/e2e/fixtures/generation-progress.html');
  await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.longPlaceName());
  const card = page.locator('.generation-trip-card');
  const title = card.locator('.generation-trip-card-header h1');
  const placeName = title.locator('.generation-trip-title-place');
  await expect(placeName).toHaveText('克孜勒苏柯尔克孜自治州');
  await expect(title).toContainText('6 日');
  const geometry = await placeName.evaluate((element) => {
    const place = element.getBoundingClientRect();
    const segment = element.closest('.generation-trip-title-segment')!.getBoundingClientRect();
    const destinations = element.closest('.generation-trip-title-destinations')!.getBoundingClientRect();
    const duration = element.closest('h1')!.querySelector('.generation-trip-title-duration')!.getBoundingClientRect();
    return {
      place: { left: place.left, right: place.right, width: place.width, height: place.height },
      segment: { left: segment.left, right: segment.right, width: segment.width },
      destinations: { left: destinations.left, right: destinations.right, width: destinations.width },
      duration: { left: duration.left, right: duration.right, width: duration.width },
      whiteSpace: getComputedStyle(element.closest('.generation-trip-title-segment')!).whiteSpace,
      overflow: document.documentElement.scrollWidth - innerWidth,
    };
  });
  expect(geometry.whiteSpace).toBe('normal');
  expect(geometry.place.right).toBeLessThanOrEqual(geometry.destinations.right + 1);
  expect(geometry.place.right).toBeLessThanOrEqual(geometry.duration.left + 1);
  expect(geometry.place.height).toBeGreaterThan(20);
  expect(geometry.overflow).toBeLessThanOrEqual(1);
  mkdirSync(evidence, { recursive: true });
  mkdirSync('../test-results/e2e-evidence/feedback-workflow/review', { recursive: true });
  writeFileSync(`${evidence}/long-name-390.json`, JSON.stringify(geometry, null, 2));
  await page.screenshot({ path: `${evidence}/long-name-390.png`, fullPage: true });
  await page.screenshot({ path: '../test-results/e2e-evidence/feedback-workflow/review/long-name-390-fixed.png', fullPage: true });
});

test('过程披露实屏证据：仅规划去重、完成收起、展开来源与终端失败 2000px/390px', async ({ page }) => {
  test.setTimeout(60_000);
  const measurements: Record<string, unknown> = {};
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/e2e/fixtures/generation-progress.html');
  const panel = page.getByTestId('thinking-chain');
  await expect(panel.locator('.research-panel-title')).toHaveText('整理旅行需求');
  await expect(panel.getByText('整理旅行需求', { exact: true })).toHaveCount(1);
  measurements.planningOnly = await page.evaluate(() => {
    const panelElement = document.querySelector('.research-panel-workspace') as HTMLElement;
    const title = panelElement.querySelector('.research-panel-title') as HTMLElement;
    const heading = panelElement.querySelector('.research-agent-heading') as HTMLElement;
    const status = panelElement.querySelector('.research-agent-state') as HTMLElement;
    return {
      title: title?.textContent,
      headingText: heading?.textContent,
      lineHeight: heading ? getComputedStyle(heading).lineHeight : null,
      contentWidth: panelElement.getBoundingClientRect().width,
      statusVisible: Boolean(status?.textContent),
    };
  });
  await page.screenshot({ path: `${EVIDENCE_DIR}/process-2000-planning-only.png`, fullPage: true });

  await page.goto('/e2e/fixtures/research-progress.html');
  const destination = page.getByTestId('research-agent-destination');
  await page.getByRole('button', { name: '目的地完成', exact: true }).click();
  await expect(destination.locator('.research-agent-body')).toHaveCount(0);
  await expect(page.getByTestId('research-agent-transport')).toContainText('进行中');
  await page.screenshot({ path: `${EVIDENCE_DIR}/process-2000-destination-completed.png`, fullPage: true });
  await destination.getByRole('button').click();
  await destination.getByTestId('research-query').locator('summary').click();
  await expect(destination.getByRole('link', { name: '伪满皇宫博物院' })).toBeVisible();
  await page.screenshot({ path: `${EVIDENCE_DIR}/process-2000-expanded-source.png`, fullPage: true });
  const borderCheck = await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('.research-query'));
    const agents = Array.from(document.querySelectorAll('.research-agent'));
    return {
      rowBorders: rows.map((row) => getComputedStyle(row).borderTopWidth),
      agentBorders: agents.map((agent) => getComputedStyle(agent).borderTopWidth),
      rowHeights: rows.slice(0, 3).map((row) => (row.querySelector('.research-query-summary') as HTMLElement)?.getBoundingClientRect().height),
    };
  });
  await page.getByRole('button', { name: '全部结束', exact: true }).click();
  await expect(destination.locator('.research-agent-body')).toHaveCount(0);
  await page.screenshot({ path: `${EVIDENCE_DIR}/process-2000-terminal-collapsed.png`, fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await destination.getByRole('button').click();
  await destination.getByTestId('research-query').locator('summary').click();
  await expect(destination.getByRole('link', { name: '伪满皇宫博物院' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${EVIDENCE_DIR}/process-390-completed-expanded.png`, fullPage: true });

  await page.setViewportSize({ width: 2000, height: 880 });
  await page.goto('/e2e/fixtures/generation-progress.html');
  await page.evaluate(() => (window as GenerationFixtureWindow).__generationFixture?.failAfterPlanning());
  await expect(page.getByText('这次规划没有完成，你可以回到新旅行重新尝试。', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '返回新旅行', exact: true })).toBeVisible();
  await page.screenshot({ path: `${EVIDENCE_DIR}/process-2000-run-failed-actions.png`, fullPage: true });
  writeFileSync(`${EVIDENCE_DIR}/measurements.json`, JSON.stringify({ ...measurements, borderCheck }, null, 2));
});
