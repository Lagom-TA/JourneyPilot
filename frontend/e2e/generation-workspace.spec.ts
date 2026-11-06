import { expect, test, type Page } from '@playwright/test';
import type { GenerationWorkspaceScene } from './fixtures/generationWorkspace';

async function openWorkspace(page: Page, scene: GenerationWorkspaceScene = 'research') {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.startsWith('/api/')) return route.continue();
    const body = pathname === '/api/product/trip-planner'
      ? { primary_styles: [{ id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 14000, inspiration_prompts: [] }
      : pathname === '/api/user/default-origin' ? { place: null } : pathname.endsWith('/stats') ? { total: 0, sources: 0, source_details: [] } : pathname.endsWith('/profile') ? { preferences: {} } : [];
    await route.fulfill({ json: body });
  });
  await page.goto(`/e2e/fixtures/generation-workspace.html?scene=${scene}`);
  await expect(page.getByTestId('generation-journey-panel')).toBeVisible();
  return errors;
}
async function scene(page: Page, value: GenerationWorkspaceScene) { await page.evaluate(next => window.__generationWorkspace!.setScene(next), value); }

test('研究台面仅露出最新动态，整块任务可开合并保留查看位置', async ({ page }) => {
  const errors = await openWorkspace(page);
  const group = page.getByTestId('research-agent-transport');
  const opener = group.locator('button.research-agent-heading');
  await expect(group.getByTestId('research-agent-update')).toHaveText('会同时比较车站位置与到达后进入市区的交通。');
  await expect(opener).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByText('过程与来源', { exact: true })).toHaveCount(0);
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
