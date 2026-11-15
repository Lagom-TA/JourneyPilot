import { expect, test, type Page } from '@playwright/test';

type JourneyRoute = 'trip_planning' | 'destination_discovery' | 'fast_answer' | 'trip_refinement';
interface RouteDecision {
  route: JourneyRoute;
  confidence: number;
  alternatives: Array<{ route: JourneyRoute; confidence: number }>;
  signals: string[];
  requires_trip_draft: boolean;
  requires_confirmation: boolean;
}
interface ChatRequest {
  messages: Array<{ role: string; content: string; message_id?: string }>;
  session_id: string | null;
  run_id: string | null;
  route: JourneyRoute | null;
  route_decision: RouteDecision | null;
  gate_decision?: {
    action: string;
    approval_token?: string;
    answers?: Array<{ question_id: string; text: string }>;
  };
}

test.use({ serviceWorkers: 'block' });

const sessionId = 'pending-e2e-session';
const runId = 'pending-e2e-run';
const originalText = '想从上海去青岛海边放松几天，第一次独自旅行。';
const privateDetail = 'upstream-private-trace-9f72 /srv/internal/provider.py';
const question = {
  id: 'pace',
  question: '这次更想慢慢逛，还是把行程排满？',
  kind: 'single',
  options: [
    { id: 'slow', label: '慢慢逛，留出休息时间' },
    { id: 'full', label: '排满一些，多看几个地方' },
  ],
};

function decision(route: JourneyRoute): RouteDecision {
  return {
    route,
    confidence: 1,
    alternatives: [],
    signals: ['model_intent'],
    requires_trip_draft: route === 'trip_planning',
    requires_confirmation: false,
  };
}

interface MockReply {
  status: number;
  contentType: string;
  body: string;
}

function sse(events: Array<{ type: string; [key: string]: unknown }>): MockReply {
  return {
    status: 200,
    contentType: 'text/event-stream',
    body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
  };
}

function planningQuestions(): MockReply {
  return sse([
    { type: 'chat_start', session_id: sessionId, run_id: runId, message_id: 'assistant-1', route_decision: decision('trip_planning') },
    {
      type: 'understanding_questions', run_id: runId, gate: 'understanding', run_status: 'awaiting_input',
      payload: { gate: 'understanding', revision: 1, questions: [question], decision_options: ['answer', 'cancel'], approval_token: 'pending-e2e-approval' },
    },
    { type: 'chat_complete', run_id: runId, run_status: 'awaiting_input' },
  ]);
}

function planningGate(): MockReply {
  return sse([
    { type: 'chat_start', session_id: sessionId, run_id: runId, message_id: 'assistant-2', route_decision: decision('trip_planning') },
    {
      type: 'approval_gate_raised', run_id: runId, gate: 'plan', run_status: 'awaiting_input',
      payload: {
        gate: 'plan', revision: 0, decision_options: ['approve', 'supplement', 'cancel'],
        plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '调查青岛海边路线' } }] },
        plan_text: '青岛海边独旅，慢慢逛，留出休息时间。',
      },
    },
    { type: 'chat_complete', run_id: runId, run_status: 'awaiting_input' },
  ]);
}

function answer(route: 'fast_answer' | 'destination_discovery', content: string, index: number): MockReply {
  const messageId = `assistant-answer-${index}`;
  const answerRunId = `answer-run-${index}`;
  return sse([
    { type: 'chat_start', session_id: sessionId, run_id: answerRunId, message_id: messageId, route_decision: decision(route) },
    { type: 'chat_chunk', message_id: messageId, content, show_content: content },
    { type: 'chat_complete', run_id: answerRunId, run_status: 'completed' },
  ]);
}

interface Harness {
  chatRequests: ChatRequest[];
  apiRequests: Array<{ method: string; path: string }>;
  unmocked: string[];
  pageErrors: string[];
  firstResponseSettled: Promise<void>;
  release: (allowAborted?: boolean) => void;
}

// 所有 API 都在浏览器内应答；未匹配的 API 返回错误，外部资源一律阻断。
async function interceptOffline(
  page: Page,
  reply: (body: ChatRequest, index: number) => MockReply,
  reducedMotion: 'reduce' | 'no-preference' = 'reduce',
): Promise<Harness> {
  const appUrl = new URL(process.env.JOURNEYPILOT_APP_URL || 'http://127.0.0.1:8080');
  if (!['localhost', '127.0.0.1', '[::1]'].includes(appUrl.hostname)) {
    throw new Error('Offline tests require a local frontend URL');
  }
  let releaseFirst = () => {};
  let settleFirst = () => {};
  let allowAborted = false;
  const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve; });
  const firstResponseSettled = new Promise<void>((resolve) => { settleFirst = resolve; });
  const harness: Harness = {
    chatRequests: [], apiRequests: [], unmocked: [], pageErrors: [], firstResponseSettled,
    release: (aborted = false) => {
      allowAborted ||= aborted;
      releaseFirst();
    },
  };
  let latestChoice: { gate: string; payload: Record<string, unknown> } | null = null;
  releases.set(page, harness.release);
  page.on('pageerror', (error) => harness.pageErrors.push(error.message));
  await page.emulateMedia({ reducedMotion });
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === '/__e2e-release-first-response') {
      harness.release();
      return route.fulfill({ status: 204, body: '' });
    }
    if (!url.pathname.startsWith('/api/')) {
      return url.origin === appUrl.origin ? route.continue() : route.abort();
    }
    const path = url.pathname.slice(4);
    harness.apiRequests.push({ method: request.method(), path });
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/chat-stream') {
      const body = request.postDataJSON() as ChatRequest;
      const index = harness.chatRequests.push(body) - 1;
      if (index === 0) await firstGate;
      try {
        const response = reply(body, index);
        if (response.contentType === 'text/event-stream') {
          const events = response.body.split('\n\n').filter(Boolean).map((frame) => JSON.parse(frame.slice('data: '.length)) as {
            type: string;
            gate?: string;
            payload?: Record<string, unknown>;
          });
          const pending = events.find((event) => (event.type === 'understanding_questions' || event.type === 'approval_gate_raised') && event.gate && event.payload);
          if (pending?.gate && pending.payload) latestChoice = { gate: pending.gate, payload: pending.payload };
        }
        return await route.fulfill(response);
      } catch (error) {
        // 用户取消后，浏览器可能已关闭仍被拦截的请求。
        if (index !== 0 || !allowAborted) throw error;
      } finally {
        if (index === 0) settleFirst();
      }
    }
    if (path === '/user/sessions') return json([]);
    if (path === '/trip-runs') return json({ runs: [], total: 0 });
    if (path === `/trip-runs/${runId}/events`) {
      return json({ run_id: runId, requested_after_sequence: 0, replay_floor_sequence: 0, latest_sequence: 0, next_after_sequence: 0, window_expired: false, current_bundle_id: null, run_status: 'awaiting_input', events: [] });
    }
    if (path === `/trip-runs/${runId}`) {
      return json({
        run: { run_id: runId, session_id: sessionId, mode: 'deep', status: 'awaiting_input', title: null, request_message_id: 'request-1', assistant_message_id: 'assistant-1', parent_run_id: null, current_node: latestChoice?.gate ?? 'understanding', resume_policy: 'checkpoint' },
        controlled_trip_identity: null,
        state: { run_id: runId, status: 'awaiting_input', current_node: latestChoice?.gate ?? 'understanding', completed_nodes: [], latest_state_summary: {}, pending_user_choice: latestChoice, trace_event_count: 0, pending_monitor_trigger_count: 0, last_error: null, updated_at: '2026-11-01' },
        execution: null, available_actions: [], events: [],
      });
    }
    if (path === '/product/trip-planner') {
      return json({ primary_styles: [{ id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 5000, inspiration_prompts: ['想去海边放松几天', '第一次独自旅行', '轻松一点'] });
    }
    if (path === '/user/default-origin') return json({ place: null });
    if (path === '/places/search') {
      const name = url.searchParams.get('q')?.trim() || '甲地';
      return json({ candidates: [{ place: { place_id: `offline:${name}`, provider: 'osm', kind: 'city', name, display_name: `${name}，中国`, country_code: 'CN', latitude: 31.2, longitude: 121.4, admin_path: ['中国', name] }, confidence: 1, requires_confirmation: true }] });
    }
    if (path === '/presets' || path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: [] });
    if (path === '/knowledge/collections/travel_knowledge/stats') return json({ total: 0, sources: 0, source_details: [] });
    harness.unmocked.push(`${request.method()} ${path}`);
    return json({ detail: 'Unmocked API request' }, 501);
  });
  await page.goto('/');
  await expect(page.getByTestId('new-trip-hero')).toBeVisible();
  return harness;
}

const releases = new WeakMap<Page, (allowAborted?: boolean) => void>();
test.afterEach(async ({ page }) => {
  releases.get(page)?.(true);
});

async function submitHome(page: Page, text: string) {
  await page.getByRole('textbox', { name: '一句话描述旅行', exact: true }).fill(text);
  await page.getByRole('button', { name: '开始规划', exact: true }).click();
}

async function expectPending(page: Page, harness: Harness, text: string) {
  await expect.poll(() => harness.chatRequests.length).toBe(1);
  expect(harness.chatRequests[0].messages[0].content).toBe(text);
  expect(harness.chatRequests[0].run_id).toBeNull();
  expect(harness.chatRequests[0].route).toBeNull();
  await expect(page.getByTestId('journey-workspace')).toBeVisible();
  const panel = page.getByTestId('generation-journey-panel');
  await expect(panel).toHaveCount(1);
  await expect(panel).toBeVisible();
  await expect(panel.getByText(text, { exact: true })).toBeVisible();
  await expect(panel.getByTestId('boarding-pass-stop')).toBeVisible();
  await expect(panel.getByTestId('boarding-pass-stop')).toBeEnabled();
  await expect(page.locator('.generation-workspace-conversation')).toHaveCount(0);
  await expect(page.getByTestId('new-trip-hero')).toHaveCount(0);
  expect(harness.apiRequests.filter(({ path }) => path.endsWith('/control'))).toEqual([]);
  return panel;
}

type HandoffObservation = {
  homeOpacity: number | null;
  workspaceOpacity: number | null;
  workspaceOffsetY: number | null;
  stopHit: boolean;
  homeInert: boolean;
  homeAriaHidden: string | null;
  stopFocused: boolean;
  workspaceFocused: boolean;
};

async function observeHandoff(page: Page, action?: 'release' | 'focus' | 'stop') {
  await page.evaluate((handoffAction) => {
    const samples: HandoffObservation[] = [];
    (window as Window & { handoffSamples?: HandoffObservation[] }).handoffSamples = samples;
    const started = performance.now();
    let acted = false;
    const sample = () => {
      const home = document.querySelector<HTMLElement>('[data-testid="workspace-conversation"]');
      const workspace = document.querySelector<HTMLElement>('[data-testid="journey-workspace"]');
      const stop = workspace?.querySelector<HTMLButtonElement>('[data-testid="boarding-pass-stop"]');
      if (home?.hasAttribute('inert') && workspace && !acted) {
        if (handoffAction === 'release') {
          acted = true;
          void fetch('/__e2e-release-first-response');
        } else if ((handoffAction === 'focus' || handoffAction === 'stop') && stop) {
          acted = true;
          stop.focus();
          if (handoffAction === 'stop') stop.click();
        }
      }
      samples.push({
        homeOpacity: home ? Number(getComputedStyle(home).opacity) : null,
        workspaceOpacity: workspace ? Number(getComputedStyle(workspace).opacity) : null,
        workspaceOffsetY: workspace ? workspace.getBoundingClientRect().top - workspace.parentElement!.getBoundingClientRect().top : null,
        stopHit: Boolean(stop && (() => {
          const rect = stop.getBoundingClientRect();
          return stop.contains(document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2));
        })()),
        homeInert: home?.hasAttribute('inert') ?? false,
        homeAriaHidden: home?.getAttribute('aria-hidden') ?? null,
        stopFocused: Boolean(stop && document.activeElement === stop),
        workspaceFocused: Boolean(workspace && document.activeElement === workspace.querySelector('[data-workspace-handoff-focus]')),
      });
      if (performance.now() - started < 1500) requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  }, action);
}

async function handoffSamples(page: Page) {
  return page.evaluate(() => (window as Window & { handoffSamples?: HandoffObservation[] }).handoffSamples ?? []);
}

function expectClean(harness: Harness) {
  expect(harness.pageErrors).toEqual([]);
  expect(harness.unmocked).toEqual([]);
}

for (const viewport of [
  { name: '桌面端', width: 1440, height: 900 },
  { name: '移动端', width: 390, height: 844 },
]) {
  test(`${viewport.name}首页退场与工作台入场保持连续`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const harness = await interceptOffline(page, () => planningQuestions(), 'no-preference');
    await page.getByRole('textbox', { name: '一句话描述旅行', exact: true }).fill(originalText);
    await observeHandoff(page);
    await page.getByRole('button', { name: '开始规划', exact: true }).click();
    const panel = await expectPending(page, harness, originalText);
    await expect(page.getByTestId('workspace-conversation')).toHaveCount(0);
    const samples = await handoffSamples(page);
    const overlap = samples.filter((sample) => sample.homeOpacity !== null && sample.workspaceOpacity !== null);
    expect(overlap.length).toBeGreaterThan(0);
    expect(overlap.every((sample) => sample.homeInert && sample.homeAriaHidden === 'true')).toBe(true);
    expect(overlap.some((sample) => sample.homeOpacity! > 0 && sample.workspaceOpacity === 1 && sample.stopHit)).toBe(true);
    expect(samples.some((sample) => sample.workspaceOffsetY !== null && sample.workspaceOffsetY > 0.5)).toBe(true);
    await expect(panel.getByText('正在确认处理方式')).toBeVisible();
    await expect(panel.locator('[data-workspace-handoff-focus]')).toBeFocused();
    expect((await handoffSamples(page)).some((sample) => sample.homeInert && sample.workspaceFocused)).toBe(false);
    harness.release();
    await expect(page.getByTestId('understanding-questions-card')).toBeVisible();
    expectClean(harness);
  });
}

test('快速响应和手动焦点不受交接动画影响', async ({ page }) => {
  const harness = await interceptOffline(page, () => answer('fast_answer', '海边风大，记得带外套。', 0), 'no-preference');
  await page.getByRole('textbox', { name: '一句话描述旅行', exact: true }).fill(originalText);
  await observeHandoff(page, 'release');
  await page.getByRole('button', { name: '开始规划', exact: true }).click();
  await expect.poll(() => harness.chatRequests.length).toBe(1);
  await expect(page.getByText('海边风大，记得带外套。')).toBeVisible();
  const input = page.getByTestId('brief-input');
  await input.focus();
  await expect(page.getByTestId('workspace-conversation')).toHaveCount(0);
  await expect(input).toBeFocused();
  expect((await handoffSamples(page)).some((sample) => sample.homeInert && sample.workspaceOpacity !== null)).toBe(true);
  expectClean(harness);
});

test('交接中快速出现的路径确认获得焦点', async ({ page }) => {
  const ambiguousDecision: RouteDecision = {
    ...decision('trip_planning'), confidence: 0.5,
    alternatives: [{ route: 'fast_answer', confidence: 0.45 }], requires_confirmation: true,
  };
  const harness = await interceptOffline(page, () => sse([
    { type: 'route_confirmation', session_id: sessionId, message_id: 'assistant-route', route_decision: ambiguousDecision },
    { type: 'chat_complete', message_id: 'assistant-route' },
  ]), 'no-preference');
  await page.getByRole('textbox', { name: '一句话描述旅行', exact: true }).fill(originalText);
  await observeHandoff(page, 'release');
  await page.getByRole('button', { name: '开始规划', exact: true }).click();
  const confirmation = page.getByRole('heading', { name: '你希望我先做哪件事？' });
  await expect(confirmation).toBeVisible();
  await expect(confirmation).toBeFocused();
  expectClean(harness);
});

test('交接完成时保留用户主动选择的停止按钮焦点', async ({ page }) => {
  const harness = await interceptOffline(page, () => planningQuestions(), 'no-preference');
  await page.getByRole('textbox', { name: '一句话描述旅行', exact: true }).fill(originalText);
  await observeHandoff(page, 'focus');
  await page.getByRole('button', { name: '开始规划', exact: true }).click();
  await expect(page.getByTestId('workspace-conversation')).toHaveCount(0);
  const stop = page.getByTestId('boarding-pass-stop');
  await expect(stop).toBeFocused();
  expect((await handoffSamples(page)).some((sample) => sample.homeInert && sample.stopFocused)).toBe(true);
  expectClean(harness);
});

test('交接中停止等待不会被动画或迟到响应覆盖', async ({ page }) => {
  const harness = await interceptOffline(page, () => planningQuestions(), 'no-preference');
  await page.getByRole('textbox', { name: '一句话描述旅行', exact: true }).fill(originalText);
  await observeHandoff(page, 'stop');
  await page.getByRole('button', { name: '开始规划', exact: true }).click();
  await expect(page.getByText('已停止等待。你可以补充需求或重新开始。')).toBeVisible();
  await expect(page.getByTestId('brief-input')).toBeFocused();
  expect((await handoffSamples(page)).some((sample) => sample.homeInert && sample.stopFocused)).toBe(true);
  expect(harness.apiRequests.filter(({ path }) => path.endsWith('/control'))).toEqual([]);
  harness.release(true);
  await harness.firstResponseSettled;
  await expect(page.getByTestId('understanding-questions-card')).toHaveCount(0);
  expectClean(harness);
});

test('打开首页后切换减少动态效果，提交时直接交接', async ({ page }) => {
  const harness = await interceptOffline(page, () => planningQuestions(), 'no-preference');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await page.getByRole('textbox', { name: '一句话描述旅行', exact: true }).fill(originalText);
  await observeHandoff(page);
  await page.getByRole('button', { name: '开始规划', exact: true }).click();
  const panel = await expectPending(page, harness, originalText);
  await expect(panel.locator('[data-workspace-handoff-focus]')).toBeFocused();
  const samples = await handoffSamples(page);
  expect(samples.some((sample) => sample.workspaceOffsetY !== null && Math.abs(sample.workspaceOffsetY) > 0.5)).toBe(false);
  expectClean(harness);
});

test('减少动态效果时直接交接并可立即停止', async ({ page }) => {
  const harness = await interceptOffline(page, () => planningQuestions());
  await submitHome(page, originalText);
  const panel = await expectPending(page, harness, originalText);
  await expect(page.getByTestId('workspace-conversation')).toHaveCount(0);
  await expect(panel.locator('[data-workspace-handoff-focus]')).toBeFocused();
  await panel.getByTestId('boarding-pass-stop').click();
  await expect(page.getByTestId('brief-input')).toBeFocused();
  expect(harness.apiRequests.filter(({ path }) => path.endsWith('/control'))).toEqual([]);
  harness.release(true);
  await harness.firstResponseSettled;
  expectClean(harness);
});

for (const viewport of [
  { name: '桌面端', width: 1440, height: 900 },
  { name: '移动端', width: 390, height: 844 },
]) {
  test(`${viewport.name}首响应前使用生成面板，规划追问沿用同一节点`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const harness = await interceptOffline(page, (body) => body.gate_decision?.action === 'answer' ? planningGate() : planningQuestions());
    await submitHome(page, originalText);
    const panel = await expectPending(page, harness, originalText);
    const pendingPanel = await panel.elementHandle();
    expect(pendingPanel).not.toBeNull();

    harness.release();
    await expect(page.getByTestId('understanding-questions-card')).toBeVisible();
    await expect(panel).toHaveCount(1);
    expect(await panel.evaluate((node, previous) => node === previous, pendingPanel)).toBe(true);
    await expect(page.locator('.generation-workspace-conversation')).toHaveCount(0);
    await page.getByRole('button', { name: '慢慢逛，留出休息时间', exact: true }).click();
    await page.getByTestId('understanding-questions-submit').click();
    await expect.poll(() => harness.chatRequests.length).toBe(2);
    expect(harness.chatRequests[1].run_id).toBe(runId);
    expect(harness.chatRequests[1].gate_decision).toMatchObject({
      action: 'answer', approval_token: 'pending-e2e-approval', answers: [{ question_id: 'pace', text: '慢慢逛，留出休息时间' }],
    });
    await expect(page.getByTestId('trip-brief-plan-gate')).toBeVisible();
    await expect(page.getByTestId('trip-brief-plan-gate')).toContainText('慢慢逛');
    expect(await panel.evaluate((node, previous) => node === previous, pendingPanel)).toBe(true);
    await expect(page.getByTestId('new-trip-hero')).toHaveCount(0);
    expectClean(harness);
  });

  test(`${viewport.name}首响应前失败保留原文，可安全重试`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const harness = await interceptOffline(page, (_body, index) => index < 3
      ? { status: 503, contentType: 'application/json', body: JSON.stringify({ detail: `Service unavailable: ${privateDetail}` }) }
      : answer('fast_answer', '已重新连接，青岛海边适合慢游。', index));
    await submitHome(page, originalText);
    await expectPending(page, harness, originalText);
    harness.release();
    const retry = page.getByTestId('retry-send');
    await expect(retry).toBeVisible();
    await expect(page.getByText(originalText, { exact: true })).toBeVisible();
    await expect(page.locator('body')).not.toContainText(privateDetail);
    await expect(page.locator('body')).not.toContainText('upstream-private-trace-9f72');
    await expect(page.locator('body')).not.toContainText('/srv/internal/provider.py');
    expect(harness.chatRequests).toHaveLength(3);
    await retry.click();
    await expect.poll(() => harness.chatRequests.length).toBe(4);
    expect(harness.chatRequests[3].messages[0].content).toBe(originalText);
    expect(harness.chatRequests[3].run_id).toBeNull();
    await expect(page.getByText('已重新连接，青岛海边适合慢游。')).toBeVisible();
    expect(harness.apiRequests.filter(({ path }) => path.endsWith('/control'))).toEqual([]);
    expectClean(harness);
  });

  test(`${viewport.name}首响应前取消不伪造 Run，仍可继续对话`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const harness = await interceptOffline(page, (_body, index) => index === 0
      ? planningQuestions()
      : answer('fast_answer', '可以，春天去海边也很合适。', index));
    await submitHome(page, originalText);
    const panel = await expectPending(page, harness, originalText);
    await panel.getByTestId('boarding-pass-stop').focus();
    await panel.getByTestId('boarding-pass-stop').click();
    await expect(page.getByTestId('generation-journey-panel')).toHaveCount(0);
    await expect(page.getByTestId('brief-input')).toBeFocused();
    await expect(page.getByText(originalText, { exact: true })).toBeVisible();
    await expect(page.getByText('已停止等待。你可以补充需求或重新开始。', { exact: true })).toBeVisible();
    expect(harness.apiRequests.filter(({ path }) => path.endsWith('/control'))).toEqual([]);
    expect(new URL(page.url()).searchParams.has('run_id')).toBe(false);

    await page.getByTestId('brief-input').fill('春天去海边合适吗？');
    await page.getByTestId('send-button').click();
    await expect.poll(() => harness.chatRequests.length).toBe(2);
    expect(harness.chatRequests[1].messages[0].content).toBe('春天去海边合适吗？');
    expect(harness.chatRequests[1].run_id).toBeNull();
    expect(harness.chatRequests[1].session_id).toBeNull();
    await expect(page.getByText('可以，春天去海边也很合适。')).toBeVisible();
    // 迟到的首个响应不能在已取消的请求中创建 Run 或覆盖新的会话状态。
    harness.release(true);
    await harness.firstResponseSettled;
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
    await expect(page.getByTestId('generation-journey-panel')).toHaveCount(0);
    await expect(page.getByTestId('understanding-questions-card')).toHaveCount(0);
    await expect(page.getByText('可以，春天去海边也很合适。')).toBeVisible();
    expect(harness.apiRequests.filter(({ path }) => path.endsWith('/control'))).toEqual([]);
    expectClean(harness);
  });
}

test('横屏等待时长需求与停止按钮仍可滚动访问', async ({ page }) => {
  await page.setViewportSize({ width: 568, height: 320 });
  const text = `想去海边旅行。${'希望沿途有足够的休息时间，也想了解当地人文和美食。'.repeat(18)}`;
  const harness = await interceptOffline(page, () => planningQuestions());
  await submitHome(page, text);
  const panel = await expectPending(page, harness, text);
  const stop = panel.getByTestId('boarding-pass-stop');
  await stop.scrollIntoViewIfNeeded();
  const isUnobscured = await stop.evaluate((button) => {
    const rect = button.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    return x >= 0 && x <= innerWidth && y >= 0 && y <= innerHeight
      && button.contains(document.elementFromPoint(x, y));
  });
  expect(isUnobscured).toBe(true);
  await stop.click();
  await expect(page.getByTestId('generation-journey-panel')).toHaveCount(0);
  harness.release(true);
  await harness.firstResponseSettled;
  expectClean(harness);
});

test('普通问答离开待响应面板后仍可继续提问', async ({ page }) => {
  const harness = await interceptOffline(page, (_body, index) => answer('fast_answer', index === 0 ? '青岛十一月海边风大，记得带外套。' : '可以再带一件保暖内搭。', index));
  const text = '青岛十一月需要穿什么？';
  await submitHome(page, text);
  const panel = await expectPending(page, harness, text);
  await panel.getByTestId('boarding-pass-stop').focus();
  harness.release();
  await expect(page.getByText('青岛十一月海边风大，记得带外套。')).toBeVisible();
  await expect(page.getByTestId('brief-input')).toBeFocused();
  await expect(page.getByTestId('generation-journey-panel')).toHaveCount(0);
  await expect(page.getByTestId('understanding-questions-card')).toHaveCount(0);
  await page.getByTestId('brief-input').fill('还需要带什么？');
  await page.getByTestId('send-button').click();
  await expect.poll(() => harness.chatRequests.length).toBe(2);
  expect(harness.chatRequests[1].run_id).toBeNull();
  await expect(page.getByText('可以再带一件保暖内搭。')).toBeVisible();
  expectClean(harness);
});

test('路径确认可选择普通回答并继续对话', async ({ page }) => {
  const ambiguous = '想去海边，先告诉我天气怎么样？';
  const ambiguousDecision: RouteDecision = {
    ...decision('trip_planning'), confidence: 0.5,
    alternatives: [{ route: 'fast_answer', confidence: 0.45 }], requires_confirmation: true,
  };
  const harness = await interceptOffline(page, (_body, index) => index === 0
    ? sse([
      { type: 'route_confirmation', session_id: sessionId, message_id: 'assistant-route', route_decision: ambiguousDecision },
      { type: 'chat_complete', message_id: 'assistant-route' },
    ])
    : answer('fast_answer', '海边天气多变，出行前留意预报。', index));
  await submitHome(page, ambiguous);
  const panel = await expectPending(page, harness, ambiguous);
  await panel.getByTestId('boarding-pass-stop').focus();
  harness.release();
  const confirmation = page.getByRole('heading', { name: '你希望我先做哪件事？' });
  await expect(confirmation).toBeVisible();
  await expect(confirmation).toBeFocused();
  await expect(page.getByTestId('generation-journey-panel')).toHaveCount(0);
  await page.getByRole('button', { name: '只回答这个问题', exact: true }).click();
  await expect.poll(() => harness.chatRequests.length).toBe(2);
  expect(harness.chatRequests[1].messages[0].content).toBe(ambiguous);
  expect(harness.chatRequests[1].run_id).toBeNull();
  expect(harness.chatRequests[1].route).toBe('fast_answer');
  expect(harness.chatRequests[1].route_decision).toMatchObject({ route: 'fast_answer', requires_confirmation: false });
  await expect(page.getByText('海边天气多变，出行前留意预报。')).toBeVisible();
  await expect(page.getByTestId('brief-input')).toBeEnabled();
  expectClean(harness);
});

test('目的地推荐可选地点并继续进入规划追问', async ({ page }) => {
  const text = '想找个海边城市放松，但还不知道去哪里。';
  const harness = await interceptOffline(page, (_body, index) => index === 0
    ? answer('destination_discovery', '可以先看看甲地的海边与城区。', index)
    : planningQuestions());
  await submitHome(page, text);
  await expectPending(page, harness, text);
  harness.release();
  await expect(page.getByText('可以先看看甲地的海边与城区。')).toBeVisible();
  await expect(page.getByTestId('generation-journey-panel')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '选好目的地，继续完善这趟旅行' })).toBeVisible();
  await page.getByRole('textbox', { name: '目的地', exact: true }).fill('甲地');
  await page.getByRole('button', { name: /^甲地/ }).click();
  await page.getByRole('button', { name: '继续规划', exact: true }).click();
  await expect.poll(() => harness.chatRequests.length).toBe(2);
  expect(harness.chatRequests[1].route).toBe('trip_planning');
  expect(harness.chatRequests[1].run_id).toBeNull();
  expect(harness.chatRequests[1].messages[0].content).toContain('选择甲地，继续规划');
  await expect(page.getByTestId('generation-journey-panel')).toBeVisible();
  await expect(page.getByTestId('understanding-questions-card')).toBeVisible();
  await expect(page.getByRole('button', { name: '慢慢逛，留出休息时间', exact: true })).toBeEnabled();
  expectClean(harness);
});
