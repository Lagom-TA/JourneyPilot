import { test, expect, type Page } from '@playwright/test';

test.skip(process.env.JP_COMPONENT_E2E !== '1', '需要启用组件夹具测试并启动本地开发服务');

test.beforeEach(async ({ page, baseURL }) => {
  const localOrigin = new URL(baseURL!).origin;
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin !== localOrigin || url.pathname.startsWith('/api/')) return route.abort();
    return route.continue();
  });
});

async function openGroup(page: Page, id: string, title: string) {
  const group = page.getByTestId(`research-agent-${id}`);
  const button = group.getByRole('button', { name: new RegExp(title) });
  await expect(button).toHaveAttribute('aria-expanded', 'false');
  await button.click();
  await expect(button).toHaveAttribute('aria-expanded', 'true');
  return group;
}

async function columns(page: Page) {
  return page.locator('.research-agent-heading').evaluateAll(headings => headings.map(heading => {
    const rect = (selector: string) => {
      const element = heading.querySelector<HTMLElement>(selector)!;
      const box = element.getBoundingClientRect();
      return { x: box.x, y: box.y, right: box.right, width: box.width, height: box.height, fontSize: Number.parseFloat(getComputedStyle(element).fontSize) };
    };
    return {
      id: heading.closest('[data-testid]')!.getAttribute('data-testid'),
      height: heading.getBoundingClientRect().height,
      title: rect('.research-agent-title'),
      summary: rect('.research-agent-update'),
      status: rect('.research-agent-state'),
    };
  }));
}

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`${viewport.width} 像素任务列、触控详情与键盘展开`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/e2e/fixtures/research-progress-layout.html');
    await page.evaluate(() => document.fonts.ready);
    const body = page.locator('.research-panel-body');
    await expect(body).toHaveCount(1);
    expect(await body.evaluate(element => getComputedStyle(element).containerName)).toBe('research-activity');
    const bodyWidth = (await body.boundingBox())!.width;
    if (viewport.width === 1440) expect(bodyWidth).toBeGreaterThanOrEqual(660);
    else expect(bodyWidth).toBeLessThan(660);

    const destination = await openGroup(page, 'destination', '目的地调研');
    await expect(destination.locator('.research-agent-state')).toHaveText('已结束');
    await expect(destination.getByTestId('research-work-note')).toContainText('先核对目的地资料');
    await expect(destination.getByTestId('research-query')).toHaveCount(2);
    await expect(page.getByTestId('research-agent-dispatch')).toHaveCount(0);
    for (const id of ['transport', 'stay']) {
      const group = page.getByTestId(`research-agent-${id}`);
      await expect(group.locator('.research-agent-state')).toHaveText('进行中');
      expect((await group.getByTestId('research-agent-update').innerText()).length).toBeGreaterThan(50);
    }
    expect(await body.locator('.research-agent').evaluateAll(groups => groups.map(group => ({
      borderStyle: getComputedStyle(group).borderStyle,
      borderWidths: [getComputedStyle(group).borderTopWidth, getComputedStyle(group).borderRightWidth, getComputedStyle(group).borderBottomWidth, getComputedStyle(group).borderLeftWidth],
      hasNode: Boolean(getComputedStyle(group, '::before').content && getComputedStyle(group, '::before').content !== 'none'),
    })))).toEqual([
      { borderStyle: 'none', borderWidths: ['0px', '0px', '0px', '0px'], hasNode: true },
      { borderStyle: 'none', borderWidths: ['0px', '0px', '0px', '0px'], hasNode: true },
      { borderStyle: 'none', borderWidths: ['0px', '0px', '0px', '0px'], hasNode: true },
    ]);
    await expect(body.locator('.research-agent-list')).toHaveCSS('padding-left', '18px');
    expect(await body.locator('.research-agent-heading').evaluateAll(headings => headings.map(heading => getComputedStyle(heading, '::after').content))).toEqual(['none', 'none', 'none']);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);

    const before = await columns(page);
    expect(before).toHaveLength(3);
    for (const row of before) {
      expect(row.height).toBeGreaterThanOrEqual(44);
      expect(row.title.fontSize).toBeGreaterThanOrEqual(16);
      expect(row.summary.fontSize).toBeGreaterThanOrEqual(15);
      expect(row.title.width).toBeGreaterThan(0);
      expect(row.summary.width).toBeGreaterThan(0);
      if (bodyWidth >= 660) {
        expect(Math.abs(row.title.x - before[0].title.x)).toBeLessThan(1);
        expect(Math.abs(row.summary.x - before[0].summary.x)).toBeLessThan(1);
        expect(Math.abs(row.status.right - before[0].status.right)).toBeLessThan(1);
        expect(row.summary.x).toBeGreaterThan(row.title.right);
        expect(row.status.x).toBeGreaterThan(row.summary.right);
        expect(Math.abs(row.summary.y - row.title.y)).toBeLessThan(8);
        expect(Math.abs(row.status.y - row.title.y)).toBeLessThan(8);
      } else {
        expect(row.status.x).toBeGreaterThan(row.title.right);
        expect(row.summary.y).toBeGreaterThanOrEqual(row.title.y + row.title.height);
      }
    }

    // 固定视口截图保留已打开的目的地任务及折叠的工具行。
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.mouse.move(0, 0);
    const screenshot = testInfo.outputPath(`research-progress-${viewport.width}x${viewport.height}.png`);
    await page.screenshot({ path: screenshot, fullPage: false, animations: 'disabled' });
    await testInfo.attach('调研进度视口截图', { path: screenshot, contentType: 'image/png' });

    const tool = destination.locator('[data-tool-id="destination-museum"]');
    await tool.locator('summary').focus();
    await page.keyboard.press('Enter');
    await expect(tool.locator('details')).toHaveAttribute('open', '');
    await expect(tool.locator('[data-detail-section="input"]')).toContainText('长春 历史博物馆');
    await expect(tool.locator('[data-detail-section="result"]')).toBeVisible();
    const source = tool.getByRole('link', { name: '伪满皇宫博物院' });
    await expect(source).toBeVisible();
    await expect(source).toHaveAttribute('href', 'https://example.org/museum');
    const linkBox = (await source.boundingBox())!;
    expect(linkBox.height).toBeGreaterThanOrEqual(44);
    expect(linkBox.width).toBeGreaterThanOrEqual(44);
    await expect(tool.locator('.research-source')).toContainText('example.org');
    const park = destination.locator('[data-tool-id="destination-park"]');
    await park.locator('summary').click();
    await expect(park.getByRole('link', { name: '南湖公园' })).toBeVisible();

    await page.getByRole('button', { name: '切换交通和住宿任务状态', exact: true }).click();
    await page.getByRole('button', { name: '追加交通和住宿长摘要', exact: true }).click();
    for (const id of ['transport', 'stay']) {
      const group = page.getByTestId(`research-agent-${id}`);
      await expect(group.locator('.research-agent-state')).toHaveText('已结束');
      await expect(group.getByTestId('research-agent-update')).toContainText('同时整理备选方案');
    }
    const after = await columns(page);
    if (bodyWidth >= 660) {
      for (const row of after) {
        const old = before.find(item => item.id === row.id)!;
        expect(Math.abs(row.title.x - old.title.x)).toBeLessThan(1);
        expect(Math.abs(row.summary.x - old.summary.x)).toBeLessThan(1);
        expect(Math.abs(row.status.right - old.status.right)).toBeLessThan(1);
      }
    }
    for (const row of after) expect(row.height).toBeGreaterThanOrEqual(44);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
    expect(errors).toEqual([]);
  });
}

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test.describe(`${viewport.width} 像素离线过程记录`, () => {
    test.use({ viewport, hasTouch: viewport.width === 390 });

    test('短记录不溢出，长记录可键盘滚动并保留全部类别', async ({ page }) => {
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await page.goto('/e2e/fixtures/research-progress-layout.html');
      await page.getByRole('button', { name: '注入六条简短说明' }).click();
      const itinerary = await openGroup(page, 'itinerary', '行程规划');
      const short = itinerary.locator('.research-queries');
      await expect(short.getByTestId('research-work-note')).toHaveCount(6);
      const six = await short.evaluate(element => ({ height: element.clientHeight, scrollHeight: element.scrollHeight }));
      expect(six.scrollHeight - six.height).toBeLessThanOrEqual(1);
      expect(six.height).toBeLessThanOrEqual(280);
      await page.getByRole('button', { name: '追加第七条说明' }).click();
      await expect(short.getByTestId('research-work-note')).toHaveCount(7);
      expect(await short.evaluate(element => element.scrollHeight - element.clientHeight)).toBeGreaterThan(0);

      await page.getByRole('button', { name: '注入各类长列表' }).click();
      for (const [id, title] of [['destination', '目的地调研'], ['transport', '交通查询'], ['stay', '住宿查询']]) {
        const group = await openGroup(page, id, title);
        const list = group.locator('.research-queries');
        await expect(list).toHaveAttribute('tabindex', '0');
        await expect(list.locator(`[data-tool-id^="long-${id}-"]`)).toHaveCount(14);
        const size = await list.evaluate(element => ({ height: element.clientHeight, scrollHeight: element.scrollHeight, overflow: getComputedStyle(element).overflowY }));
        expect(size.height).toBeLessThanOrEqual(280);
        expect(size.scrollHeight).toBeGreaterThan(size.height);
        expect(['auto', 'scroll']).toContain(size.overflow);
        await list.focus();
        await expect(list).toBeFocused();
        await page.keyboard.press('End');
        await expect.poll(() => list.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
        await expect(list.locator(`[data-tool-id="long-${id}-14"]`)).toBeInViewport();
        await page.keyboard.press('Home');
        await expect.poll(() => list.evaluate(element => element.scrollTop)).toBe(0);
        await expect(list.locator(`[data-tool-id="long-${id}-01"]`)).toBeInViewport();
      }
      await expect(page.getByTestId('research-agent-stay')).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    });

    test('相邻调用合并，详情和实时更新保留展开状态', async ({ page }) => {
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await page.goto('/e2e/fixtures/research-progress-layout.html');
      await page.getByRole('button', { name: '注入工具聚合' }).click();
      const destination = await openGroup(page, 'destination', '目的地调研');
      const list = destination.locator('.research-queries');
      const groups = destination.getByTestId('research-tool-group');
      await expect(groups).toHaveCount(2);
      const heading = groups.first().locator('button');
      await expect(heading).toContainText('地点搜索');
      await expect(heading).toContainText('3 次');
      await expect(heading).toContainText('已完成');
      if (viewport.width === 390) await heading.tap();
      else await heading.click();
      await expect(heading).toHaveAttribute('aria-expanded', 'true');
      await expect(groups.first().getByTestId('research-query')).toHaveCount(3);
      const first = groups.first().locator('[data-tool-id="aggregate-01"]');
      await first.locator('summary').click();
      await expect(first.locator('[data-detail-section="input"]')).toContainText('长春 长影旧址');
      await expect(first.getByRole('link', { name: '长影旧址' })).toHaveAttribute('href', 'https://example.org/studio');
      await expect(groups.first().locator('[data-tool-id="aggregate-03"]')).toContainText('进行中');
      const separator = list.getByTestId('research-work-note').filter({ hasText: '两组查询之间' });
      await expect(separator.locator('.research-work-note-text')).toHaveText('两组查询之间先比较资料，然后再继续确认相邻地点。');
      await expect(separator.locator('.research-work-note-text')).not.toContainText('工作说明');
      await groups.nth(1).locator('button').click();
      const repeated = groups.nth(1).locator('[data-tool-id="aggregate-04"]');
      await repeated.locator('summary').click();
      await expect(repeated.locator('[data-detail-section="input"]')).toContainText('长春 长影旧址');
      await expect(repeated.getByRole('link', { name: '长影旧址' })).toBeVisible();
      const agentHeading = destination.locator('button.research-agent-heading');
      await agentHeading.click();
      await agentHeading.click();
      await expect(groups.first().locator('button')).toHaveAttribute('aria-expanded', 'true');
      await expect(first.locator('details')).toHaveAttribute('open', '');
      await list.evaluate(element => { element.scrollTop = 80; });
      const before = await list.evaluate(element => element.scrollTop);
      await page.getByRole('button', { name: '追加实时记录' }).click();
      await expect(groups.first().locator('button')).toHaveAttribute('aria-expanded', 'true');
      await expect(first.locator('details')).toHaveAttribute('open', '');
      expect(Math.abs((await list.evaluate(element => element.scrollTop)) - before)).toBeLessThanOrEqual(1);
      await expect(list.getByTestId('research-work-note').filter({ hasText: '实时新增记录 1' })).toHaveCount(1);
    });

    test('两条独立工具转为聚合后保留已打开详情', async ({ page }) => {
      await page.goto('/e2e/fixtures/research-progress-layout.html');
      await page.getByRole('button', { name: '注入两条路线' }).click();
      const transport = await openGroup(page, 'transport', '交通查询');
      const first = transport.locator('[data-tool-id="pair-1"]');
      await expect(transport.getByTestId('research-tool-group')).toHaveCount(0);
      await first.locator('summary').click();
      await expect(first.locator('[data-detail-section="input"]')).toContainText('路线候选1');
      await page.getByRole('button', { name: '追加第三条路线' }).click();
      const aggregate = transport.getByTestId('research-tool-group');
      await expect(aggregate).toHaveCount(1);
      await expect(aggregate.locator('button')).toHaveAttribute('aria-expanded', 'true');
      await expect(first.locator('details')).toHaveAttribute('open', '');
      await expect(first.locator('[data-detail-section="input"]')).toContainText('路线候选1');
    });
  });
}
