import { expect, test, type Locator, type Page } from '@playwright/test';
import type { GenerationWorkspaceScene } from './fixtures/generationWorkspace';

type GateVariant = 'workspace' | 'card';
type PlanStep = { step: number; agents: string[]; tasks?: Record<string, string> };

async function openWorkspace(page: Page, scene: GenerationWorkspaceScene = 'research', variant: GateVariant = 'workspace') {
  const errors: string[] = [];
  const origin = new URL(test.info().project.use.baseURL!).origin;
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) {
      errors.push(`Unexpected external request: ${url.href}`);
      return route.abort();
    }
    const pathname = url.pathname;
    if (!pathname.startsWith('/api/')) return route.continue();
    const body = pathname === '/api/product/trip-planner'
      ? { primary_styles: [{ id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 14000, inspiration_prompts: [] }
      : pathname === '/api/user/default-origin' ? { place: null } : pathname.endsWith('/stats') ? { total: 0, sources: 0, source_details: [] } : pathname.endsWith('/profile') ? { preferences: {} } : [];
    await route.fulfill({ json: body });
  });
  await page.goto(`/e2e/fixtures/generation-workspace.html?scene=${scene}&variant=${variant}`);
  await expect(page.getByTestId(variant === 'card' ? 'trip-brief-plan-gate' : 'generation-journey-panel')).toBeVisible();
  return errors;
}
async function scene(page: Page, value: GenerationWorkspaceScene) { await page.evaluate(next => window.__generationWorkspace!.setScene(next), value); }

async function setPlan(page: Page, planText: string, steps: PlanStep[]) {
  await page.evaluate(({ planText, steps }) => {
    const dispatch = window.__generationWorkspace!.dispatch as (action: unknown) => void;
    dispatch({ type: 'SET_PLAN_APPROVAL_GATE', payload: {
      gate: 'plan', runId: 'run-generation-workspace', status: 'pending', source: 'restored',
      approvalToken: 'offline-generation-plan', revision: 0, decisionOptions: ['approve', 'supplement', 'cancel'], planText, steps,
    } });
  }, { planText, steps });
}

async function expectPlanList(plan: Locator, tag: 'ul' | 'ol', marker: 'disc' | 'decimal') {
  const list = plan.locator(tag);
  const items = list.locator('li');
  await expect(list).toHaveCount(1);
  await expect(items).toHaveCount(3);
  for (const item of await items.all()) await expect(item).toBeVisible();
  await expect(list).toHaveCSS('list-style-type', marker);
  await expect(items.first()).toHaveCSS('display', 'list-item');
  await expect(items.first()).toHaveCSS('list-style-type', marker);
  await expect(items.first()).toHaveCSS('list-style-position', 'outside');
  const layout = await list.evaluate(element => {
    const item = element.querySelector('li')!;
    return {
      padding: Number.parseFloat(getComputedStyle(element).paddingLeft),
      listLeft: element.getBoundingClientRect().left,
      itemLeft: item.getBoundingClientRect().left,
    };
  });
  expect(layout.padding).toBeGreaterThan(0);
  expect(layout.itemLeft).toBeGreaterThan(layout.listLeft);
  expect(await plan.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
}

const unorderedPlan = [
  '逛逛成都和重庆的街区，尝尝当地美食。',
  '比较两城间的交通和方便出行的住宿。',
  '每天安排相近区域，留出休息时间。',
];
const orderedPlan = [
  '先看看适合散步和品尝美食的街区。',
  '再比较两城间的交通和住宿位置。',
  '最后按相近区域安排路线，留出休息时间。',
];

for (const variant of ['workspace', 'card'] as const) {
  for (const viewport of [{ name: '桌面', width: 1440, height: 900 }, { name: '窄屏', width: 320, height: 800 }]) {
    test(`${viewport.name}${variant === 'workspace' ? '工作台' : '普通卡'}显示研究方案列表标记`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.emulateMedia({ reducedMotion: 'reduce' });
      const errors = await openWorkspace(page, 'plan', variant);
      const gate = page.getByTestId('trip-brief-plan-gate');
      const plan = gate.locator('.plan-gate-plan-text');
      await expectPlanList(plan, 'ul', 'disc');
      await expect(plan.locator('ul > li')).toHaveText(unorderedPlan);

      await setPlan(page, orderedPlan.map((item, index) => `${index + 1}. ${item}`).join('\n'), [{ step: 1, agents: ['destination_researcher'] }]);
      await expectPlanList(plan, 'ol', 'decimal');
      await expect(plan.locator('ol > li')).toHaveText(orderedPlan);
      const layout = await gate.evaluate(element => ({
        width: element.clientWidth,
        scrollWidth: element.scrollWidth,
        left: element.getBoundingClientRect().left,
        right: element.getBoundingClientRect().right,
      }));
      expect(layout.scrollWidth).toBeLessThanOrEqual(layout.width + 1);
      expect(layout.left).toBeGreaterThanOrEqual(0);
      expect(layout.right).toBeLessThanOrEqual(viewport.width);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      expect(errors).toEqual([]);
    });
  }
}

test('研究方案保留纯文本与任务回退，并可补充要求后确认', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = await openWorkspace(page, 'plan');
  const gate = page.getByTestId('trip-brief-plan-gate');
  const plan = gate.locator('.plan-gate-plan-text');
  const approve = gate.getByRole('button', { name: '确认并开始生成' });

  await setPlan(page, '先比较交通和住宿，再安排每天的路线。', [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '这段任务不应覆盖正文' } }]);
  await expect(plan.locator('p')).toHaveText('先比较交通和住宿，再安排每天的路线。');
  await expect(plan).not.toContainText('这段任务不应覆盖正文');
  await expect(approve).toBeEnabled();

  await setPlan(page, '  ', [
    { step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '核对街区与美食', transport_researcher: '比较城际交通' } },
    { step: 2, agents: ['transport_researcher'], tasks: { transport_researcher: '比较城际交通' } },
  ]);
  await expect(plan.locator('p')).toHaveText(['核对街区与美食', '比较城际交通']);
  await expect(approve).toBeEnabled();
  await gate.getByRole('button', { name: '补充或调整旅行要求' }).click();
  const guide = gate.getByLabel('想改哪里？');
  await guide.fill('每天晚一点出门');
  await expect(approve).toBeDisabled();
  await expect(gate.getByTestId('plan-gate-supplement')).toBeEnabled();
  await guide.clear();
  await expect(gate.getByTestId('plan-gate-supplement')).toBeDisabled();
  await expect(approve).toBeEnabled();

  let decision: unknown;
  await page.route('**/api/chat-stream', async route => {
    decision = route.request().postDataJSON().gate_decision;
    await route.fulfill({ status: 400, json: { detail: '离线测试，不发送请求' } });
  });
  await approve.click();
  await expect.poll(() => decision).toEqual({ action: 'approve', content: '', approval_token: 'offline-generation-plan' });
  await expect(gate.getByRole('alert')).toBeVisible();
  expect(errors).toEqual([]);
});

test('研究台面仅露出最新动态，整块任务可开合并保留查看位置', async ({ page }) => {
  const errors = await openWorkspace(page);
  const progress = page.locator('.generation-progress');
  const progressVisuals = await progress.evaluate(element => {
    const active = element.querySelector<HTMLElement>('li.is-active');
    const activeAfter = active ? getComputedStyle(active, '::after') : null;
    const railAfter = getComputedStyle(element, '::after');
    return {
      railAfter: railAfter.content,
      activeAfter: activeAfter?.content || 'none',
      activeWidth: active?.getBoundingClientRect().width || 0,
      railWidth: element.getBoundingClientRect().width,
    };
  });
  expect(progressVisuals.railAfter).toBe('none');
  expect(progressVisuals.activeAfter).not.toBe('none');
  expect(progressVisuals.activeWidth).toBeLessThan(progressVisuals.railWidth);
  const group = page.getByTestId('research-agent-transport');
  const opener = group.locator('button.research-agent-heading');
  await expect(group.getByTestId('research-agent-update')).toHaveText('会同时比较车站位置与到达后进入市区的交通。');
  await expect(opener).toHaveAttribute('aria-expanded', 'false');
  await group.getByTestId('research-agent-update').click();
  await expect(opener).toHaveAttribute('aria-expanded', 'true');
  await group.getByTestId('research-query').locator('summary').click();
  await expect(group.getByRole('link', { name: '成都东 → 重庆北' })).toBeVisible();
  await page.evaluate(() => window.__generationWorkspace!.dispatch({ type: 'ADD_THINKING_STEP', payload: { id: 'transport-end', agentName: '交通查询', content: '交通资料已整理。', progressStatus: 'completed', stepName: '交通查询', timestamp: new Date() } }));
  await expect(opener).toHaveAttribute('aria-expanded', 'true');
  await expect(group.getByRole('link', { name: '成都东 → 重庆北' })).toBeVisible();
  await opener.click();
  await expect(opener).toHaveAttribute('aria-expanded', 'false');
  await opener.focus();
  await page.keyboard.press('Enter');
  await expect(opener).toHaveAttribute('aria-expanded', 'true');
  expect(errors).toEqual([]);
});

test('阶段可固定查看，再次点击回到当前进展', async ({ page }) => {
  await openWorkspace(page);
  const requirements = page.getByRole('button', { name: '整理旅行需求', exact: true });
  await requirements.click();
  await expect(requirements).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('research-agent-transport')).toHaveCount(0);
  await scene(page, 'route');
  await expect(requirements).toHaveAttribute('aria-pressed', 'true');
  await requirements.click();
  await expect(page.getByTestId('research-agent-itinerary')).toBeVisible();
});

test('确认方案后点回需求阶段仍可查看原研究方案', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = await openWorkspace(page, 'plan');
  await expect(page.getByTestId('trip-brief-plan-gate').locator('.plan-gate-plan-text')).toContainText('逛逛成都和重庆的街区');
  await scene(page, 'research');
  const requirements = page.getByRole('button', { name: '整理旅行需求', exact: true });
  await requirements.click();
  await expect(requirements).toHaveAttribute('aria-pressed', 'true');
  const stagePlan = page.locator('[data-testid="trip-brief-plan-gate"][data-readonly="true"]');
  await expect(stagePlan).toBeVisible();
  await expect(stagePlan.locator('.plan-gate-plan-text')).toContainText('逛逛成都和重庆的街区');
  await expect(stagePlan.getByRole('button', { name: '确认并开始生成' })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('刷新后从运行事件恢复需求阶段的研究方案', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = await openWorkspace(page);
  await page.route('**/api/trip-runs/**/events**', async route => {
    await route.fulfill({
      json: {
        run_id: 'run-generation-workspace',
        requested_after_sequence: 0,
        replay_floor_sequence: 1,
        latest_sequence: 1,
        next_after_sequence: 1,
        window_expired: false,
        run_status: 'running',
        current_bundle_id: null,
        events: [{
          event_id: 1,
          run_id: 'run-generation-workspace',
          sequence: 1,
          event_type: 'run.gate_raised',
          payload: {
            status: 'awaiting_input',
            gate: 'plan',
            payload: {
              revision: 0,
              plan_text: '确认过的方案仍从这里查看。',
              plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: {} }] },
              decision_options: ['approve', 'supplement', 'cancel'],
            },
          },
          created_at: '2026-12-01T00:00:00Z',
        }],
      },
    });
  });
  await page.getByRole('button', { name: '整理旅行需求', exact: true }).click();
  const stagePlan = page.locator('[data-testid="trip-brief-plan-gate"][data-readonly="true"]');
  await expect(stagePlan.locator('.plan-gate-plan-text')).toContainText('确认过的方案仍从这里查看。');
  expect(errors).toEqual([]);
});

test('追问按类型作答，多轮替换清除旧选择和草稿', async ({ page }) => {
  await openWorkspace(page, 'questions');
  const form = page.getByTestId('understanding-questions-card');
  await form.getByRole('button', { name: '慢慢逛，留出休息时间', exact: true }).click();
  await form.getByRole('button', { name: '当地美食', exact: true }).click();
  await form.getByRole('button', { name: '街区与文化', exact: true }).click();
  await expect(form.getByRole('button', { name: '当地美食', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await form.getByRole('button', { name: '补充回答：这趟旅行更想慢慢逛，还是多看几个地方？' }).click();
  await form.getByRole('textbox', { name: '自由回答：这趟旅行更想慢慢逛，还是多看几个地方？' }).fill('第二天晚一点出门');
  await expect(form.getByTestId('date-range-trigger')).toBeVisible();
  await form.getByRole('textbox', { name: '自由回答：还有什么希望照顾到的地方？' }).fill('不安排爬山');
  await scene(page, 'question-next');
  await expect(form).toHaveAttribute('data-revision', '1');
  await expect(form.getByRole('button', { name: '慢慢逛，留出休息时间', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await expect(form.getByRole('textbox')).toHaveCount(0);
  await expect(page.getByTestId('generation-followup-composer')).toHaveCount(0);
});

test('终态只提供实际可用动作，过期追问与只读记录不能提交', async ({ page }) => {
  const errors = await openWorkspace(page, 'interrupted');
  await expect(page.getByRole('button', { name: '继续生成', exact: true })).toBeVisible();
  await scene(page, 'unrecoverable');
  await expect(page.getByRole('button', { name: '继续生成', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '返回新旅行', exact: true })).toBeVisible();
  await scene(page, 'cancelled');
  await page.evaluate(() => window.__generationWorkspace!.dispatch({ type: 'SET_UNDERSTANDING_QUESTIONS', payload: { runId: 'run-generation-workspace', revision: 3, approvalToken: 'obsolete', questions: [], retryLocation: true, retryResearch: true } }));
  await expect(page.getByTestId('understanding-questions-card')).toHaveCount(0);
  await scene(page, 'stopping');
  await expect(page.getByTestId('boarding-pass-stop')).toBeDisabled();
  await expect(page.getByTestId('boarding-pass-stop')).toHaveText('正在停止');
  await scene(page, 'readonly');
  await expect(page.getByText('历史生成记录 · 只读', { exact: true })).toBeVisible();
  await expect(page.getByTestId('boarding-pass-resume')).toHaveCount(0);
  await expect(page.getByTestId('generation-followup-composer')).toHaveCount(0);
  expect(errors).toEqual([]);
});
