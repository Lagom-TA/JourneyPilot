import { expect, test } from '@playwright/test';
import { readFile, writeFile } from 'node:fs/promises';

test.describe.configure({ retries: 0 });

// 需要显式开启：这组用例调用真实付费模型并创建持久化行程。
// 本套件不得拦截请求或伪造 provider 响应。
test('真实跨城过夜旅行：表单 → 审批 → 调研 → 行程 → PDF → 刷新恢复', async ({ page, request }, testInfo) => {
  test.skip(process.env.JP_LIVE_E2E !== '1', 'Set JP_LIVE_E2E=1 to call real providers');
  test.setTimeout(900_000);
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
    await expect(page.getByRole('heading', { name: /选择你的常用出发地|规划一趟确定的旅行/ })).toBeVisible();
    if (await page.getByRole('button', { name: '跳过', exact: true }).isVisible()) {
      await page.getByRole('button', { name: '跳过', exact: true }).click();
    }
    const destination = process.env.JP_LIVE_DESTINATION || '苏州';
    for (const [label, query] of [['从哪里出发', '上海'], ['去哪里', destination]]) {
      const input = page.getByRole('textbox', { name: label, exact: true });
      await input.fill(query);
      await input.locator('xpath=../..').getByRole('button').filter({ hasText: `${query}市` }).first().click({ timeout: 40_000 });
      await expect(input).toHaveValue(`${query}市`);
    }
    const start = new Date();
    start.setDate(start.getDate() + 2);
    const end = new Date(start);
    end.setDate(end.getDate() + 1);
    const date = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
    await page.getByRole('button', { name: '选择开始日期 → 选择结束日期' }).click();
    await page.getByRole('button', { name: `选择 ${date(start)}`, exact: true }).click();
    await page.getByRole('button', { name: `选择 ${date(end)}`, exact: true }).click();
    await page.getByRole('button', { name: '确认日期 · 2 天 1 晚' }).click();
    await page.getByRole('button', { name: '轻松慢游', exact: true }).click();
    await page.getByRole('button', { name: '开始规划', exact: true }).click();

    const approve = page.getByRole('button', { name: '确认调研计划并继续', exact: true });
    await expect(approve).toBeVisible({ timeout: 150_000 });
    await Promise.all(captures);
    expect(runId, '审批阶段必须已持久化真实 Run').not.toBe('');
    console.log(`Live trip ${runId}: waiting for approval`);
    await page.screenshot({ path: testInfo.outputPath('plan-gate.png'), fullPage: true });
    restoringApproval = true;
    await page.reload();
    await expect(approve).toBeVisible({ timeout: 30_000 });
    restoringApproval = false;
    await approve.click();

    await expect.poll(async () => {
      const response = await request.get(`/api/trip-runs/${runId}`);
      expect(response.ok()).toBeTruthy();
      const detail = await response.json();
      await writeFile(testInfo.outputPath('run.json'), JSON.stringify(detail, null, 2));
      const status = detail.run.status;
      console.log(`Live trip ${runId}: ${status}`);
      return ['completed', 'failed', 'cancelled', 'interrupted'].includes(status);
    }, { timeout: 660_000, intervals: [15_000] }).toBe(true);
    const finalRun = await (await request.get(`/api/trip-runs/${runId}`)).json();
    expect(finalRun.run.status, JSON.stringify(finalRun.run)).toBe('completed');

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
    await page.screenshot({ path: testInfo.outputPath('itinerary.png'), fullPage: true });
    await page.getByRole('tab', { name: '完整报告' }).click();
    await expect(page.getByTestId('report-cover')).toBeVisible();
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: '导出当前 PDF' }).click();
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
    await page.getByRole('tab', { name: '完整报告' }).click();
    await expect(page.getByTestId('report-cover')).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath('mobile-report.png'), fullPage: true });
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
