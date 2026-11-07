import { test, expect, type Page } from '@playwright/test';

// 正式组件与合成事件；经真实 SSE 解析和状态投影，不调用付费 API。
test.skip(process.env.JP_COMPONENT_E2E !== '1', 'Requires Vite dev component fixture');

async function openGroup(page: Page, id: string) {
  const group = page.getByTestId(`research-agent-${id}`);
  const button = group.locator('button.research-agent-heading');
  await expect(button).toHaveAttribute('aria-expanded', 'false');
  await button.click();
  await expect(button).toHaveAttribute('aria-expanded', 'true');
  return group;
}

test('研究任务按需展开，串行推进与停止保留手动查看', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/e2e/fixtures/research-progress.html');
    const panel = page.getByTestId('thinking-chain');
    await expect(panel.locator('.research-panel-heading')).not.toHaveAttribute('aria-expanded');
    await expect(page.getByTestId('research-agent-transport')).toHaveCount(0);
    await expect(page.getByTestId('research-agent-stay')).toHaveCount(0);
    await expect(panel).not.toContainText('research_packet_id');
    const destination = await openGroup(page, 'destination');
    const query = destination.getByTestId('research-query');
    await query.locator('summary').click();
    await expect(query.locator('[data-detail-section="input"]')).toContainText('长春 历史博物馆');
    await expect(query.getByRole('link', { name: '伪满皇宫博物院' })).toHaveAttribute('href', 'https://example.org/museum');
    await page.getByRole('button', { name: '目的地完成', exact: true }).click();
    await expect(destination.locator('.research-agent-state')).toHaveText('已结束');
    await expect(query.getByRole('link', { name: '伪满皇宫博物院' })).toBeVisible();
    const transport = page.getByTestId('research-agent-transport');
    await expect(transport.locator('.research-agent-state')).toHaveText('进行中');
    await expect(transport.locator('button')).toHaveAttribute('aria-expanded', 'false');
    await page.getByRole('button', { name: '交通完成', exact: true }).click();
    await expect(transport.locator('.research-agent-state')).toHaveText('已结束');
    const stay = await openGroup(page, 'stay');
    await expect(stay.getByTestId('research-query')).toHaveCount(2);
    await expect(stay.getByTestId('research-query').first().locator('summary')).toHaveCount(0);
    await expect(stay).toContainText('暂不可查');
    await page.getByRole('button', { name: '停止', exact: true }).click();
    await expect(panel).toContainText('旅行规划已中断');
    await expect(stay.locator('.research-agent-state')).toHaveText('已停止');
    await expect(query.getByRole('link', { name: '伪满皇宫博物院' })).toBeVisible();
    await page.getByRole('button', { name: '住宿直接返回', exact: true }).click();
    await expect(stay.locator('.research-agent-state')).toHaveText('已结束');
    await expect(stay.getByTestId('research-query')).toHaveCount(0);
    await expect(stay).toContainText('已整理 1 个住宿候选');
    expect(errors).toEqual([]);
  });

test('工具保留真实计数与安全详情，内部载荷和失败正文不进入界面', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/e2e/fixtures/research-progress.html');
  await page.getByRole('button', { name: '激活摘要', exact: true }).click();
  await page.getByRole('button', { name: '边界详情', exact: true }).click();
  await page.getByRole('button', { name: '长查询', exact: true }).click();
  const destination = await openGroup(page, 'destination');
  await expect(page.getByTestId('research-agent-planning')).toHaveCount(0);
  const fourResults = page.getByTestId('research-query').filter({ hasText: '找到 4 个结果：深圳湾公园、红树林、人才公园、海上世界' });
  await expect(fourResults.locator('summary')).toHaveCount(1);
  await fourResults.locator('summary').click();
  await expect(fourResults).toContainText('找到 4 个结果：深圳湾公园、红树林、人才公园、海上世界');
  await expect(fourResults.locator('.research-source')).toHaveCount(2);
  await fourResults.locator('.research-tool-detail').scrollIntoViewIfNeeded();

  const onlySummary = page.getByTestId('research-query').filter({ hasText: '已整理 3 条适合雨天的室内活动摘要' });
  await onlySummary.locator('summary').click();
  await expect(onlySummary.locator('[data-detail-section="input"]')).toContainText('当地雨天备选活动');
  await expect(onlySummary).toContainText('已整理 3 条适合雨天的室内活动摘要');
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

  const errorInput = page.locator('[data-tool-id="input-error"]');
  await expect(errorInput.locator('summary')).toHaveCount(0);
  for (const leaked of ['Traceback', 'File', 'line 42', 'agent.py']) {
    await expect(errorInput).not.toContainText(leaked);
  }

  const longRow = page.getByTestId('research-query').filter({ hasText: '找到 1 个适合雨天散步的街区' });
  await longRow.locator('summary').focus();
  await page.keyboard.press('Enter');
  await expect(longRow.getByRole('link', { name: '北山街雨天散步路线' })).toBeVisible();
  await expect(longRow.locator('.research-tool-input-value')).toContainText('上午、午后和傍晚三个时间段的具体安排');


  await page.getByRole('button', { name: '目的地完成', exact: true }).click();
  await page.getByRole('button', { name: '无关事件', exact: true }).click();
  await expect(fourResults.locator('.research-tool-detail')).toBeVisible();
  await page.getByRole('button', { name: '全部结束', exact: true }).click();
  await expect(destination.locator('.research-agent-body')).toBeVisible();
  await expect(fourResults.locator('.research-tool-detail')).toBeVisible();
});

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

for (const status of ['failed', 'cancelled'] as const) {
  test(`无 progress_status 的 thinking 经 SSE 到达 ${status} 后不保留运行占位`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const fixture = await openGenerationSse(page);
    const ts = Date.now();
    await fixture.push([
      { type: 'chat_start', session_id: 'generation-sse', run_id: 'run-generation-sse', message_id: 'assistant-sse', route_decision: { route: 'trip_planning', confidence: 1, alternatives: [], signals: ['explicit_ui_action'], requires_trip_draft: true, requires_confirmation: false }, ts_ms: ts },
      { type: 'thinking', message_id: 'assistant-sse', agent_name: '制定计划', content: '制定调研计划：目的地调研 → 交通查询 → 住宿查询 → 行程规划', step_name: '制定规划安排', ts_ms: ts + 1 },
      { type: 'thinking', message_id: 'assistant-sse', agent_name: '安排查询', content: '正在按顺序安排调研任务', step_name: '安排旅行查询', ts_ms: ts + 2 },
      { type: 'agent_progress', message_id: 'assistant-sse', agent_name: '整理需求', content: '已整理旅行偏好与同行信息', step_name: '整理旅行需求', progress_status: 'completed', ts_ms: ts + 3 },
      { type: 'tool_start', message_id: 'assistant-sse', agent_name: '目的地调研', tool_name: 'global_place_search', tool_call_id: 'sse-place', args_summary: '{"query":"青岛 海岸线"}', category: 'search', ts_ms: ts + 4 },
      { type: 'tool_result', message_id: 'assistant-sse', agent_name: '目的地调研', tool_name: 'global_place_search', tool_call_id: 'sse-place', status: 'success', summary: '找到 1 个结果', result_preview: [{ title: '小麦岛公园', detail: '适合傍晚看海与散步', url: 'https://example.org/qingdao-coast' }], category: 'search', ts_ms: ts + 5 },
    ]);
    await expect(page.getByTestId('generation-journey-panel')).toBeVisible();
    await fixture.push([{ type: status === 'failed' ? 'run_failed' : 'run_cancelled', run_id: 'run-generation-sse', message: '离线合成：规划失败。', final_content: '离线合成：规划取消。', run_status: status, ts_ms: ts + 6 }]);
    await expect(page.locator('.research-panel-title')).toHaveText(status === 'failed' ? '旅行规划未完成' : '旅行规划已取消');
    await page.getByRole('button', { name: '整理旅行需求', exact: true }).click();
    const planning = await openGroup(page, 'planning');
    await expect(planning.locator('.research-agent-state')).toHaveText('已结束');
    await expect(planning).toContainText('制定调研计划：目的地调研 → 交通查询 → 住宿查询 → 行程规划');
    await expect(planning).not.toContainText('正在按顺序安排调研任务');
    await page.getByRole('button', { name: '查找旅行资料', exact: true }).click();
    const destination = await openGroup(page, 'destination');
    await destination.getByTestId('research-query').locator('summary').click();
    await expect(destination.getByRole('link', { name: '小麦岛公园' })).toBeVisible();
    await expect(destination).not.toContainText('正在处理，结果返回后会显示在这里。');
    await expect(destination.locator('.research-agent-state')).not.toHaveText('进行中');
    await fixture.close();
    expect(fixture.pageErrors).toEqual([]);
  });
}

test('失败正文保持隐藏，成功空结果仍可查看，失败不改变手动展开状态', async ({ page }) => {
  await page.goto('/e2e/fixtures/research-progress.html');
  const destination = await openGroup(page, 'destination');
  await page.getByRole('button', { name: '内部失败', exact: true }).click();
  const panel = page.getByTestId('thinking-chain');
  for (const leaked of ['失败调用不应展示', 'HTTP 500', '失败预览不应展示', 'secret-token', '未匹配到工具', '工具激活失败', '内部错误不应展示']) {
    await expect(panel).not.toContainText(leaked);
  }
  await expect(destination.locator('[data-tool-id="empty-success"]')).toContainText('无结果');
  await page.getByRole('button', { name: '结果后失败', exact: true }).click();
  await expect(destination.locator('.research-agent-state')).toHaveText('未完成');
  await expect(destination.locator('.research-agent-body')).toBeVisible();
  await expect(destination).not.toContainText('阶段失败正文不应展示');
});

test('同 Run 补充轮次保留手动展开，新增工具详情由用户单独打开', async ({ page }) => {
  await page.goto('/e2e/fixtures/research-progress.html');
  const destination = await openGroup(page, 'destination');
  const oldRow = destination.locator('[data-tool-id="museum"]');
  await oldRow.locator('summary').click();
  await page.getByRole('button', { name: '目的地完成', exact: true }).click();
  await page.getByRole('button', { name: '补充轮次', exact: true }).click();
  await expect(destination.locator('.research-agent-state')).toHaveText('进行中');
  await expect(oldRow.getByRole('link', { name: '伪满皇宫博物院' })).toBeVisible();
  const newRow = destination.locator('[data-tool-id="destination-round-2-result"]');
  await expect(newRow.getByRole('link', { name: '吉林省博物院' })).not.toBeVisible();
  await newRow.locator('summary').click();
  await expect(newRow.getByRole('link', { name: '吉林省博物院' })).toBeVisible();
});

test('组合补查与反馈返研归入原任务，最新活动跟随当前阶段', async ({ page }) => {
  await page.goto('/e2e/fixtures/generation-progress.html');
  await page.evaluate(() => window.__generationFixture?.addResearch());
  await page.evaluate(() => window.__generationFixture?.compositionRedo());
  const destination = await openGroup(page, 'destination');
  await expect(page.getByTestId('research-agent-destination（第2轮补充）')).toHaveCount(0);
  await expect(destination).toContainText('找到 2 个结果');
  await destination.locator('[data-tool-id="destination-redo-query"]').locator('summary').click();
  await expect(destination.getByRole('link', { name: '长影旧址博物馆' })).toBeVisible();
  await page.evaluate(() => window.__generationFixture?.compositionContinue());
  await expect(page.locator('.research-panel-title')).toHaveText('安排每天路线');
  const composition = await openGroup(page, 'itinerary');
  await expect(composition).toContainText('门到门 25 分钟');
  await expect(composition).toContainText('已要求按反馈重做');
  await expect(destination).toHaveCount(0);
});

test('新 Run 清除任务与工具展开状态', async ({ page }) => {
  await page.goto('/e2e/fixtures/research-progress.html');
  const destination = await openGroup(page, 'destination');
  await destination.getByTestId('research-query').locator('summary').click();
  await expect(destination.getByRole('link', { name: '伪满皇宫博物院' })).toBeVisible();
  await page.getByRole('button', { name: '新 Run', exact: true }).click();
  await expect(destination.locator('button')).toHaveAttribute('aria-expanded', 'false');
  await destination.locator('button').click();
  await expect(destination.getByRole('link', { name: '伪满皇宫博物院' })).not.toBeVisible();
});


declare global {
  interface Window {
    __generationFixture?: { addResearch: () => void; compositionRedo: () => void; compositionContinue: () => void };
  }
}
