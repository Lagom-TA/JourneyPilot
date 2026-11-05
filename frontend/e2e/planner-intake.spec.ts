import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';

/**
 * 点击开始规划立即进入工作台；理解问题、回答与方案在同一工作台连续发生。
 * 全部 API 在浏览器内拦截，离线演示，不访问外部服务。
 */

const SCREEN_DIR = '../test-results/e2e-evidence/generation-02-workspace-understanding/screens';

const routeDecision = { route: 'trip_planning', confidence: 1, alternatives: [], signals: ['model_intent'], requires_trip_draft: true, requires_confirmation: false };
const fastDecision = { route: 'fast_answer', confidence: 1, alternatives: [], signals: ['model_intent'], requires_trip_draft: false, requires_confirmation: false };
const place = (name: string, id: string) => ({ place_id: id, provider: 'osm', kind: 'city', name, display_name: `${name}，中国`, country_code: 'CN', latitude: 31.2, longitude: 121.4, admin_path: ['中国', name] });

const paceQuestion = {
  id: 'pace',
  question: '这次更想慢慢逛，还是把行程排满？',
  kind: 'single',
  options: [
    { id: 'slow', label: '慢慢逛，留出休息时间' },
    { id: 'full', label: '排满一些，多看几个地方' },
  ],
};
const understandingPayload = (revision: number, token: string) => ({
  gate: 'understanding',
  revision,
  questions: [paceQuestion],
  decision_options: ['answer', 'cancel'],
  approval_token: token,
});
const planGatePayload = {
  gate: 'plan',
  revision: 0,
  decision_options: ['approve', 'supplement', 'cancel'],
  plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '调查青岛适合独游的海边与城区路线' } }] },
  plan_text: '从上海出发去青岛，2026-11-05 至 2026-11-07，独自旅行；节奏：慢慢逛，留出休息时间。',
};

function sse(events: unknown[]) {
  return { status: 200, contentType: 'text/event-stream', body: events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('') };
}

interface Harness {
  requests: Record<string, any>[];
  chatRequests: Record<string, any>[];
  errors: string[];
}

async function interceptWorkspaceApi(page: Page, overrides: {
  session: string;
  runId: string;
  firstChat: (body: Record<string, any>) => unknown[];
  answerChat?: (body: Record<string, any>) => unknown[];
  runDetail?: () => Record<string, unknown>;
  sessionDetail?: () => Record<string, unknown>;
}): Promise<Harness> {
  const harness: Harness = { requests: [], chatRequests: [], errors: [] };
  page.on('pageerror', error => harness.errors.push(error.message));
  let releaseChat: (() => void) | null = null;
  const chatGate = new Promise<void>(resolve => { releaseChat = resolve; });
  (page as any)._releaseChat = () => releaseChat?.();
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!['localhost', '127.0.0.1'].includes(url.hostname)) return route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.slice(4);
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/chat-stream') {
      const body = route.request().postDataJSON();
      harness.chatRequests.push(body);
      if (!body.run_id) {
        await chatGate;
        return route.fulfill(sse(overrides.firstChat(body)));
      }
      if (body.gate_decision?.action === 'answer') {
        return route.fulfill(sse((overrides.answerChat ?? (() => [
          { type: 'chat_start', session_id: overrides.session, run_id: overrides.runId, message_id: 'assistant-2', route_decision: routeDecision },
          { type: 'approval_gate_raised', run_id: overrides.runId, gate: 'plan', run_status: 'awaiting_input', payload: planGatePayload },
          { type: 'chat_complete', run_id: overrides.runId, run_status: 'awaiting_input' },
        ]))(body)));
      }
      return route.fulfill(sse([
        { type: 'chat_start', session_id: overrides.session, run_id: overrides.runId, message_id: 'assistant-replay', route_decision: routeDecision },
        { type: 'chat_complete', run_id: overrides.runId, run_status: 'awaiting_input' },
      ]));
    }
    const summary = { session_id: overrides.session, title: '海边独旅', status: 'active', mode: 'deep', last_message_preview: '', created_at: '2026-11-01', updated_at: '2026-11-01' };
    if (path === '/user/sessions') return json([summary]);
    if (path === `/user/sessions/${overrides.session}` && overrides.sessionDetail) return json(overrides.sessionDetail());
    if (path === '/trip-runs') {
      if (url.searchParams.get('session_id') === overrides.session && overrides.runDetail) {
        const run = (overrides.runDetail() as any).run;
        return json({ runs: [run], total: 1 });
      }
      return json({ runs: [], total: 0 });
    }
    if (path === `/trip-runs/${overrides.runId}/events`) return json({ run_id: overrides.runId, requested_after_sequence: 0, replay_floor_sequence: 0, latest_sequence: 0, next_after_sequence: 0, window_expired: false, current_bundle_id: null, run_status: 'awaiting_input', events: [] });
    if (path === `/trip-runs/${overrides.runId}` && overrides.runDetail) return json(overrides.runDetail());
    if (path === '/product/trip-planner') return json({ primary_styles: [{ id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 5000, inspiration_prompts: ['想去海边放松几天', '第一次独自旅行', '轻松一点'] });
    if (path === '/user/default-origin') return json({ place: null });
    if (path === '/places/search') {
      const query = new URL(route.request().url()).searchParams.get('q') ?? '';
      const name = ['上海', '青岛'].find(item => query.includes(item)) ?? '青岛';
      return json({ candidates: [{ place: place(name, `offline:${name}`), confidence: 1, requires_confirmation: true }] });
    }
    if (path === '/presets' || path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: [] });
    return json({});
  });
  return harness;
}

for (const mobile of [false, true]) {
  test(`提交后立即进入工作台，理解问题在工作台内回答${mobile ? '（手机）' : ''}`, async ({ page }) => {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 });
    const harness = await interceptWorkspaceApi(page, {
      session: 'understanding-e2e',
      runId: 'trip-understanding',
      firstChat: () => [
        { type: 'chat_start', session_id: 'understanding-e2e', run_id: 'trip-understanding', message_id: 'assistant-1', route_decision: routeDecision },
        { type: 'tool_start', run_id: 'trip-understanding', message_id: 'assistant-1', agent_name: '理解旅行需求', tool_name: 'free_web_search', tool_call_id: 'tool-1', args_summary: '青岛 11 月 海边', category: 'web', ts_ms: 1 },
        { type: 'tool_result', run_id: 'trip-understanding', message_id: 'assistant-1', agent_name: '理解旅行需求', tool_name: 'free_web_search', tool_call_id: 'tool-1', summary: '青岛 11 月适合海边散步', status: 'success', result_preview: [], duration_ms: 800, ts_ms: 2 },
        { type: 'understanding_questions', run_id: 'trip-understanding', gate: 'understanding', run_status: 'awaiting_input', payload: understandingPayload(1, 'understanding_gate.approval:e2e-1') },
        { type: 'chat_complete', run_id: 'trip-understanding', run_status: 'awaiting_input' },
      ],
    });
    await page.emulateMedia({ reducedMotion: mobile ? 'reduce' : 'no-preference' });
    await page.goto('/');
    await expect(page.getByTestId('new-trip-hero')).toBeVisible();
    await page.getByRole('textbox', { name: '一句话描述旅行', exact: true }).fill('想去青岛海边放松几天，第一次独自旅行');
    await page.getByRole('button', { name: '开始规划', exact: true }).click();
    // 点击开始规划立即显示工作台；首页不再等待问答。
    await expect(page.getByTestId('journey-workspace')).toBeVisible();
    await expect(page.getByTestId('new-trip-hero')).toHaveCount(0);
    await page.screenshot({ path: `${SCREEN_DIR}/${mobile ? '390' : '1440'}-submitted-waiting.png`, fullPage: true });
    (page as any)._releaseChat();
    await expect(page.getByTestId('understanding-questions-card')).toBeVisible();
    await expect(page.getByTestId('understanding-question')).toContainText('慢慢逛');
    await expect(page.getByTestId('journey-workspace')).toBeVisible();
    await expect(page.getByTestId('new-trip-hero')).toHaveCount(0);
    await page.screenshot({ path: `${SCREEN_DIR}/${mobile ? '390' : '1440'}-understanding-questions.png`, fullPage: true });
    // 选项与自由补充合并成完整回答文字。
    await page.getByRole('button', { name: '慢慢逛，留出休息时间' }).click();
    await page.getByRole('button', { name: '补充回答：这次更想慢慢逛，还是把行程排满？' }).click();
    await page.getByRole('textbox', { name: '自由回答：这次更想慢慢逛，还是把行程排满？' }).fill('第二天想睡到自然醒');
    await page.getByTestId('understanding-questions-submit').click();
    await expect.poll(() => harness.chatRequests.at(-1)?.gate_decision?.action).toBe('answer');
    const decision = harness.chatRequests.at(-1)!.gate_decision;
    expect(decision.answers[0].text).toContain('慢慢逛，留出休息时间');
    expect(decision.answers[0].text).toContain('第二天想睡到自然醒');
    expect(decision.approval_token).toBe('understanding_gate.approval:e2e-1');
    // 回答后方案在同一工作台出现，理解卡退场，没有首页闪回。
    await expect(page.getByTestId('trip-brief-plan-gate')).toBeVisible();
    await expect(page.getByTestId('trip-brief-plan-gate')).toContainText('慢慢逛，留出休息时间');
    await expect(page.getByTestId('trip-brief-plan-gate').getByRole('heading', { name: '研究与安排设想' })).toHaveCount(1);
    await expect(page.getByTestId('trip-brief-plan-gate')).not.toContainText('调查青岛适合独游的海边与城区路线');
    await expect(page.getByTestId('understanding-questions-card')).toHaveCount(0);
    await expect(page.getByTestId('new-trip-hero')).toHaveCount(0);
    await page.waitForTimeout(mobile ? 150 : 450);
    await page.screenshot({ path: `${SCREEN_DIR}/${mobile ? '390' : '1440'}-plan-gate.png`, fullPage: true });
    expect(harness.errors).toEqual([]);
  });
}

test('刷新后工作台恢复待答问题，回答继续同一运行', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let asked = false;
  const harness = await interceptWorkspaceApi(page, {
    session: 'understanding-e2e',
    runId: 'trip-understanding',
    firstChat: () => {
      asked = true;
      return [
        { type: 'chat_start', session_id: 'understanding-e2e', run_id: 'trip-understanding', message_id: 'assistant-1', route_decision: routeDecision },
        { type: 'understanding_questions', run_id: 'trip-understanding', gate: 'understanding', run_status: 'awaiting_input', payload: understandingPayload(1, 'understanding_gate.approval:e2e-1') },
        { type: 'chat_complete', run_id: 'trip-understanding', run_status: 'awaiting_input' },
      ];
    },
    sessionDetail: () => ({
      session_id: 'understanding-e2e', title: '海边独旅', status: 'active', mode: 'deep',
      last_message_preview: '', created_at: '2026-11-01', updated_at: '2026-11-01',
      messages: [], next_before: null, has_more: false,
    }),
    runDetail: () => ({
      run: {
        run_id: 'trip-understanding', session_id: 'understanding-e2e', mode: 'deep', status: 'awaiting_input',
        title: null, request_message_id: 'm1', assistant_message_id: 'assistant-1', parent_run_id: null,
        current_node: 'understanding_gate', resume_policy: 'checkpoint', controlled_trip_identity: null,
      },
      state: {
        run_id: 'trip-understanding', status: 'awaiting_input', current_node: 'understanding_gate',
        completed_nodes: [], latest_state_summary: {}, pending_user_choice: {
          type: 'understanding_questions', gate: 'understanding',
          payload: understandingPayload(1, 'understanding_gate.approval:e2e-1'),
        }, trace_event_count: 0, pending_monitor_trigger_count: 0, last_error: null, updated_at: '2026-11-01',
      },
      events: [],
    }),
  });
  await page.goto('/');
  await page.getByRole('textbox', { name: '一句话描述旅行', exact: true }).fill('想去青岛海边放松几天');
  await page.getByRole('button', { name: '开始规划', exact: true }).click();
  (page as any)._releaseChat();
  await expect(page.getByTestId('understanding-questions-card')).toBeVisible();
  await page.reload();
  // 刷新后仍在工作台，问题从持久化状态恢复，没有回到首页重新出题。
  await expect(page.getByTestId('journey-workspace')).toBeVisible();
  await expect(page.getByTestId('new-trip-hero')).toHaveCount(0);
  await expect(page.getByTestId('understanding-questions-card')).toBeVisible();
  await expect(page.getByTestId('understanding-question')).toContainText('慢慢逛');
  await page.getByRole('button', { name: '慢慢逛，留出休息时间' }).click();
  await page.getByTestId('understanding-questions-submit').click();
  await expect.poll(() => harness.chatRequests.length).toBe(2);
  expect(harness.chatRequests[1].run_id).toBe('trip-understanding');
  expect(harness.chatRequests[1].gate_decision.action).toBe('answer');
  expect(asked).toBe(true);
  expect(harness.errors).toEqual([]);
});

test('表单完整身份直接进入方案确认', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const harness = await interceptWorkspaceApi(page, {
    session: 'form-e2e',
    runId: 'trip-form',
    firstChat: () => [
      { type: 'chat_start', session_id: 'form-e2e', run_id: 'trip-form', message_id: 'assistant-1', route_decision: routeDecision },
      { type: 'approval_gate_raised', run_id: 'trip-form', gate: 'plan', run_status: 'awaiting_input', payload: planGatePayload },
      { type: 'chat_complete', run_id: 'trip-form', run_status: 'awaiting_input' },
    ],
  });
  await page.clock.setFixedTime(new Date('2026-11-01T10:00:00+08:00'));
  await page.goto('/');
  await page.getByTestId('planner-structured-tab').click();
  await page.getByRole('textbox', { name: '出发地', exact: true }).fill('上海');
  await page.getByRole('button', { name: '上海 上海，中国', exact: true }).click();
  await page.getByRole('textbox', { name: '目的地，搜索城市或区域' }).fill('青岛');
  await page.getByRole('button', { name: '青岛 青岛，中国', exact: true }).click();
  await page.getByTestId('date-range-trigger').click();
  const dialog = page.getByTestId('date-range-dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: /^选择 2026-11-05/ }).click();
  await dialog.getByRole('button', { name: /^选择 2026-11-07/ }).click();
  await dialog.getByRole('button', { name: /确认日期/ }).click();
  await page.getByRole('button', { name: '开始规划', exact: true }).click();
  await expect(page.getByTestId('journey-workspace')).toBeVisible();
  (page as any)._releaseChat();
  await expect(page.getByTestId('trip-brief-plan-gate')).toBeVisible();
  await expect(page.getByTestId('understanding-questions-card')).toHaveCount(0);
  const body = harness.chatRequests[0];
  expect(body.route).toBe('trip_planning');
  expect(body.controlled_trip_identity.destinations[0].name).toBe('青岛');
  expect(harness.errors).toEqual([]);
});

test('普通问题得到轻量回答，不进入规划门', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const harness = await interceptWorkspaceApi(page, {
    session: 'qa-e2e',
    runId: 'trip-qa',
    firstChat: () => [
      { type: 'chat_start', session_id: 'qa-e2e', run_id: 'trip-qa', message_id: 'assistant-qa', route_decision: fastDecision },
      { type: 'tool_start', run_id: 'trip-qa', message_id: 'assistant-qa', agent_name: '旅行顾问', tool_name: 'free_web_search', tool_call_id: 'tool-1', args_summary: '青岛 11 月 天气', category: 'web', ts_ms: 1 },
      { type: 'tool_result', run_id: 'trip-qa', message_id: 'assistant-qa', agent_name: '旅行顾问', tool_name: 'free_web_search', tool_call_id: 'tool-1', summary: '青岛 11 月平均 15 度', status: 'success', result_preview: [], duration_ms: 500, ts_ms: 2 },
      { type: 'chat_chunk', message_id: 'assistant-qa', content: '青岛 11 月平均气温 15 度左右，海边风大，建议带一件防风外套。', show_content: '青岛 11 月平均气温 15 度左右，海边风大，建议带一件防风外套。' },
      { type: 'chat_complete', run_id: 'trip-qa', run_status: 'completed' },
    ],
  });
  await page.goto('/');
  await page.getByRole('textbox', { name: '一句话描述旅行', exact: true }).fill('青岛 11 月需要穿什么衣服？');
  await page.getByRole('button', { name: '开始规划', exact: true }).click();
  await expect(page.getByTestId('journey-workspace')).toBeVisible();
  (page as any)._releaseChat();
  await expect(page.getByText('青岛 11 月平均气温 15 度左右')).toBeVisible();
  await expect(page.getByTestId('understanding-questions-card')).toHaveCount(0);
  await expect(page.getByTestId('trip-brief-plan-gate')).toHaveCount(0);
  // 自然语言请求不指定路径，由模型判断普通提问还是正式规划。
  expect(harness.chatRequests[0].route).toBeNull();
  expect(harness.errors).toEqual([]);
});
