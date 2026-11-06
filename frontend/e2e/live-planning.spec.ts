import { expect, test } from '@playwright/test';
import { readFile, writeFile } from 'node:fs/promises';

test.describe.configure({ retries: 0 });

// 需要显式开启：这组用例调用真实付费模型并创建持久化行程。
// 本套件不得拦截请求或伪造 provider 响应。
test('真实跨城过夜旅行：需求 → 审批 → 调研 → 行程 → PDF → 刷新恢复', async ({ page, request }, testInfo) => {
  test.skip(process.env.JP_LIVE_E2E !== '1', 'Set JP_LIVE_E2E=1 to call real providers');
  test.setTimeout(2_100_000);
  const errors: string[] = [];
  const httpErrors: string[] = [];
  const captures: Promise<void>[] = [];
  const deliveryIds: string[] = [];
  const terminalEvents: string[] = [];
  let restoringApproval = false;
  let runId = '';
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    // 恢复未审批的行程时会查询当前 bundle；该端点在首次交付前按公开合同返回 404。
    // 不要放行后续的其他 404。
    const pendingBundle = restoringApproval && response.status() === 404
      && new URL(response.url()).pathname === `/api/trip-runs/${runId}/bundle/current`;
    if (response.url().includes('/api/') && response.status() >= 400 && !pendingBundle) {
      httpErrors.push(`${response.status()} ${new URL(response.url()).pathname}`);
    }
    if (response.url().endsWith('/api/chat-stream')) {
      const index = captures.length;
      captures.push((async () => {
        const body = await response.text();
        await writeFile(testInfo.outputPath(`chat-${index}.sse`), body);
        for (const line of body.split('\n')) {
          if (!line.startsWith('data:')) continue;
          const event = JSON.parse(line.slice(5));
          if (event.run_id) runId = event.run_id;
          if (event.type === 'delivery_ready') deliveryIds.push(event.bundle_id);
          if (['chat_complete', 'run_terminal', 'run_failed', 'run_cancelled'].includes(event.type)) terminalEvents.push(event.type);
        }
      })());
    }
  });

  try {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /想去哪里，\s*告诉我。/ })).toBeVisible();
    const destination = process.env.JP_LIVE_DESTINATION || '苏州';
    const start = new Date();
    start.setDate(start.getDate() + 4);
    const end = new Date(start);
    end.setDate(end.getDate() + 1);
    const date = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
    await page.getByRole('textbox', { name: '一句话描述旅行' }).fill(
      `两位成年人从上海出发到${destination}旅行，${date(start)}至${date(end)}，共两天一晚，预算总计3000元。喜欢人文和当地美食，希望节奏轻松；往返优先高铁，住干净舒适的中档酒店，没有饮食禁忌。请规划具体日程、住宿和交通。`,
    );
    await page.getByRole('button', { name: '开始规划', exact: true }).click();

    const approve = page.getByRole('button', { name: '确认并开始生成', exact: true });
    const questions = page.getByTestId('understanding-questions-card');
    for (let round = 0; round < 6; round += 1) {
      await expect(approve.or(questions)).toBeVisible({ timeout: 300_000 });
      if (await approve.isVisible()) break;
      for (const question of await questions.getByTestId('understanding-question').all()) {
        const options = question.getByRole('group').getByRole('button');
        expect(await options.count()).toBeGreaterThan(0);
        await options.first().click();
      }
      await questions.getByTestId('understanding-questions-submit').click();
      await expect(questions).toBeHidden({ timeout: 30_000 });
    }
    await expect(approve).toBeVisible({ timeout: 300_000 });
    await Promise.all(captures);
    expect(runId, '审批阶段必须已持久化真实 Run').not.toBe('');
    console.log(`Live trip ${runId}: waiting for approval`);
    restoringApproval = true;
    await page.reload();
    await expect(approve).toBeVisible({ timeout: 30_000 });
    restoringApproval = false;
    await approve.click();

    // 审批后运行开始，若又停在 awaiting_input，就是研究门（如某类调研未完成）等待用户决定；
    // 本用例不替用户决定，直接以真实状态失败，不空等到超时。审批刚点下时状态可能还没离开
    // awaiting_input，所以只在已观察到 running 之后才把它视为终止。
    let sawRunning = false;
    await expect.poll(async () => {
      const response = await request.get(`/api/trip-runs/${runId}`);
      expect(response.ok()).toBeTruthy();
      const detail = await response.json();
      await writeFile(testInfo.outputPath('run.json'), JSON.stringify(detail, null, 2));
      const status = detail.run.status;
      console.log(`Live trip ${runId}: ${status}`);
      if (status === 'running') sawRunning = true;
      return ['completed', 'failed', 'cancelled', 'interrupted'].includes(status) || (sawRunning && status === 'awaiting_input');
    }, { timeout: 1_800_000, intervals: [15_000] }).toBe(true);
    const finalRun = await (await request.get(`/api/trip-runs/${runId}`)).json();
    expect(finalRun.run.status, JSON.stringify({ run: finalRun.run, pending: finalRun.state?.pending_user_choice })).toBe('completed');

    await expect(page.getByTestId('interactive-itinerary')).toBeVisible({ timeout: 30_000 });
    const bundleResponse = await request.get(`/api/trip-runs/${runId}/bundle/current`);
    expect(bundleResponse.ok()).toBeTruthy();
    const bundle = await bundleResponse.json();
    await writeFile(testInfo.outputPath('bundle.json'), JSON.stringify(bundle, null, 2));
    expect(bundle.manifest.run_id).toBe(runId);
    expect(bundle.workspace.itinerary.day_plans).toHaveLength(2);
    expect(bundle.workspace.itinerary.visit_stops.length).toBeGreaterThan(0);
    expect(bundle.workspace.itinerary.lodging_stays.length, '跨夜行程必须交付住宿').toBeGreaterThan(0);
    expect(bundle.workspace.itinerary.transport_legs.length, '跨城行程必须交付交通').toBeGreaterThan(0);
    await page.getByRole('button', { name: '阅读版', exact: true }).click();
    await expect(page.getByTestId('report-cover')).toBeVisible();
    const downloadPromise = page.waitForEvent('download');
    // 阅读版面板内唯一一个导出按钮；不做全局 testid 查询，避免命中导航栏的入口。
    await page.getByRole('region', { name: '旅行阅读版' }).getByTestId('download-current-pdf').click();
    const download = await downloadPromise;
    const pdfPath = testInfo.outputPath('trip.pdf');
    await download.saveAs(pdfPath);
    const pdf = await readFile(pdfPath);
    expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
    expect(pdf.length).toBeGreaterThan(10_000);
    await page.reload();
    await expect(page.getByTestId('interactive-itinerary')).toBeVisible({ timeout: 30_000 });
    const restored = await request.get(`/api/trip-runs/${runId}/bundle/current`);
    expect((await restored.json()).manifest.bundle_id).toBe(bundle.manifest.bundle_id);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByTestId('canvas-pill').click();
    await expect(page.getByTestId('canvas-sheet').getByTestId('interactive-itinerary')).toBeVisible();
    await page.getByRole('button', { name: '阅读版', exact: true }).click();
    await expect(page.getByTestId('report-cover')).toBeVisible();
    await Promise.all(captures);
    expect(deliveryIds).toContain(bundle.manifest.bundle_id);
    expect(terminalEvents).toContain('chat_complete');
    expect(terminalEvents).toContain('run_terminal');
    expect(errors, '浏览器未捕获异常').toEqual([]);
    expect(httpErrors, '真实 API 错误').toEqual([]);
  } finally {
    await Promise.allSettled(captures);
    await writeFile(testInfo.outputPath('browser-diagnostics.json'), JSON.stringify({ runId, errors, httpErrors }, null, 2));
    await writeFile(testInfo.outputPath('page.txt'), await page.locator('body').innerText());
  }
});
