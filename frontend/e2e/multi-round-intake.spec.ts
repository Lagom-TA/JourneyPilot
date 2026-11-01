import { expect, test, type Page } from '@playwright/test';

/**
 * 多轮理解：回答进入后续理解，问题逐轮更新且凭据随版本变化；
 * 已答问题不重复出现。全部 API 在浏览器内拦截，离线演示。
 */

const routeDecision = { route: 'trip_planning', confidence: 1, alternatives: [], signals: ['model_intent'], requires_trip_draft: true, requires_confirmation: false };
const firstQuestion = {
  id: 'pace',
  question: '这次更想慢慢逛，还是把行程排满？',
  kind: 'single',
  options: [
    { id: 'slow', label: '慢慢逛，留出休息时间' },
    { id: 'full', label: '排满一些' },
  ],
};
const secondQuestion = {
  id: 'budget',
  question: '大约多少预算比较合适？',
  kind: 'single',
  options: [
    { id: 'low', label: '5000 元以内' },
    { id: 'high', label: '8000 元左右' },
  ],
};
const planGatePayload = {
  gate: 'plan',
  revision: 0,
  decision_options: ['approve', 'supplement', 'cancel'],
  plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '调查青岛慢节奏海边路线' } }] },
  plan_text: '**研究和安排设想**\n从上海去青岛，节奏：慢慢逛；预算：5000 元以内。\n\n- **目的地调研**：调查青岛慢节奏海边路线',
};

function sse(events: unknown[]) {
  return { status: 200, contentType: 'text/event-stream', body: events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('') };
}

test('逐轮回答新问题，方案消费全部问答', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const chatRequests: Record<string, any>[] = [];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  let round = 0;
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!['localhost', '127.0.0.1'].includes(url.hostname)) return route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.slice(4);
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/chat-stream') {
      const body = route.request().postDataJSON();
      chatRequests.push(body);
      if (round === 0) {
        round = 1;
        return route.fulfill(sse([
          { type: 'chat_start', session_id: 'multi-understanding', run_id: 'trip-multi', message_id: 'assistant-1', route_decision: routeDecision },
          { type: 'understanding_questions', run_id: 'trip-multi', gate: 'understanding', run_status: 'awaiting_input', payload: { gate: 'understanding', revision: 1, questions: [firstQuestion], decision_options: ['answer', 'cancel'], approval_token: 'token-round-1' } },
          { type: 'chat_complete', run_id: 'trip-multi', run_status: 'awaiting_input' },
        ]));
      }
      if (round === 1) {
        round = 2;
        return route.fulfill(sse([
          { type: 'chat_start', session_id: 'multi-understanding', run_id: 'trip-multi', message_id: 'assistant-2', route_decision: routeDecision },
          { type: 'tool_start', run_id: 'trip-multi', message_id: 'assistant-2', agent_name: '理解旅行需求', tool_name: 'free_web_search', tool_call_id: 'tool-2', args_summary: '青岛 慢节奏 预算', category: 'web', ts_ms: 3 },
          { type: 'tool_result', run_id: 'trip-multi', message_id: 'assistant-2', agent_name: '理解旅行需求', tool_name: 'free_web_search', tool_call_id: 'tool-2', summary: '青岛消费适中', status: 'success', result_preview: [], duration_ms: 400, ts_ms: 4 },
          { type: 'understanding_questions', run_id: 'trip-multi', gate: 'understanding', run_status: 'awaiting_input', payload: { gate: 'understanding', revision: 2, questions: [secondQuestion], decision_options: ['answer', 'cancel'], approval_token: 'token-round-2' } },
          { type: 'chat_complete', run_id: 'trip-multi', run_status: 'awaiting_input' },
        ]));
      }
      return route.fulfill(sse([
        { type: 'chat_start', session_id: 'multi-understanding', run_id: 'trip-multi', message_id: 'assistant-3', route_decision: routeDecision },
        { type: 'approval_gate_raised', run_id: 'trip-multi', gate: 'plan', run_status: 'awaiting_input', payload: planGatePayload },
        { type: 'chat_complete', run_id: 'trip-multi', run_status: 'awaiting_input' },
      ]));
    }
    const summary = { session_id: 'multi-understanding', title: '海边独旅', status: 'active', mode: 'deep', last_message_preview: '', created_at: '2026-11-01', updated_at: '2026-11-01' };
    if (path === '/user/sessions') return json([summary]);
    if (path === '/trip-runs') return json({ runs: [], total: 0 });
    if (path === '/trip-runs/trip-multi/events') return json({ run_id: 'trip-multi', requested_after_sequence: 0, replay_floor_sequence: 0, latest_sequence: 0, next_after_sequence: 0, window_expired: false, current_bundle_id: null, run_status: 'awaiting_input', events: [] });
    if (path === '/product/trip-planner') return json({ primary_styles: [{ id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 5000, inspiration_prompts: ['想去海边', '第一次独自旅行', '轻松一点'] });
    if (path === '/user/default-origin') return json({ place: null });
    if (path === '/presets' || path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: [] });
    return json({});
  });
  await page.goto('/');
  await page.getByRole('textbox', { name: '一句话描述旅行', exact: true }).fill('想去青岛海边放松几天');
  await page.getByRole('button', { name: '开始规划', exact: true }).click();
  await expect(page.getByTestId('journey-workspace')).toBeVisible();

  // 第一轮：只问节奏。
  await expect(page.getByTestId('understanding-questions-card')).toBeVisible();
  await expect(page.getByTestId('understanding-question')).toContainText('慢慢逛');
  await page.getByRole('button', { name: '慢慢逛，留出休息时间' }).click();
  await page.getByTestId('understanding-questions-submit').click();
  await expect.poll(() => chatRequests.at(-1)?.gate_decision?.approval_token).toBe('token-round-1');

  // 第二轮：先查再问预算；已答的节奏问题不再出现。
  await expect(page.getByTestId('understanding-questions-card')).toBeVisible();
  await expect(page.getByTestId('understanding-question')).toContainText('预算');
  await expect(page.getByTestId('understanding-question')).not.toContainText('慢慢逛');
  await page.getByRole('button', { name: '5000 元以内' }).click();
  await page.getByTestId('understanding-questions-submit').click();
  await expect.poll(() => chatRequests.at(-1)?.gate_decision?.approval_token).toBe('token-round-2');

  // 方案消费两轮问答，同一工作台内确认。
  await expect(page.getByTestId('trip-brief-plan-gate')).toBeVisible();
  await expect(page.getByTestId('trip-brief-plan-gate')).toContainText('慢慢逛');
  await expect(page.getByTestId('trip-brief-plan-gate')).toContainText('5000 元以内');
  await expect(page.getByTestId('new-trip-hero')).toHaveCount(0);
  expect(errors).toEqual([]);
});
