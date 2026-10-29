import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';

const routeDecision = { route: 'trip_planning', confidence: 1, alternatives: [], signals: ['explicit_ui_action'], requires_trip_draft: true, requires_confirmation: false };
const place = (name: string, id: string) => ({ place_id: `osm:relation:${id}`, provider: 'osm', kind: 'city', name, display_name: `${name}，中国`, country_code: 'CN', latitude: 31.2, longitude: 121.4, admin_path: ['中国', name] });
const intake = {
  raw_input: '想找一个适合第一次独自旅行的海边城市，预算5000元', route_decision: routeDecision,
  controlled_identity: null, seed_destinations: [], missing_fields: ['origin', 'destinations', 'dates', 'place_confirmation'], ready_to_create: false,
  recognized_requirements: ['第一次独自旅行', '海边城市', '预算5000元'], understanding_status: 'ready',
  draft: { origin_query: '', destination_queries: [], start_date: '2026-11-05', end_date: '2026-11-08', duration_days: 4, party: { adults: 1, children: 0, elderly_companions: false, accessibility_required: false }, style: null, budget_text: '预算5000元', destination_decided: false, destination_suggestions: [{ name: '青岛', reason: '城市交通便利，海边散步和城市体验容易组合' }], confirmed_origin: null, confirmed_destinations: [] },
  questions: [{ id: 'budget', question: '5000元包括往返交通和住宿吗？', kind: 'single', options: [{ id: 'all', label: '包括往返交通和住宿' }, { id: 'local', label: '只算当地花费' }, { id: 'sensible_default', label: '按合理默认安排，不再补充' }] }],
  answers: [], additional_requirements: '',
};

for (const mobile of [false, true]) {
  test(`需求工作区保留答案、确认真实地点后启动规划${mobile ? '（手机）' : ''}`, async ({ page }) => {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 2000, height: 880 });
    const requests: Record<string, any>[] = [];
    let pending: any = null;
    let sessionLoaded = false;
    let releaseIntake: (() => void) | null = null;
    const intakeGate = new Promise<void>((resolve) => { releaseIntake = resolve; });
    const pageErrors: string[] = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    const loopIntake = structuredClone(intake);
    loopIntake.draft.end_date = '2026-11-10';
    loopIntake.draft.duration_days = 6;
    await page.addInitScript(() => localStorage.setItem('sta_last_session_id', 'intake-e2e'));
    await page.route('**/api/**', async route => {
      const pathname = new URL(route.request().url()).pathname;
      if (!pathname.startsWith('/api/')) return route.continue();
      const path = pathname.slice(4);
      const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
      if (path === '/chat-stream') {
        const body = route.request().postDataJSON(); requests.push(body);
        if (!body.controlled_trip_identity) {
          pending = structuredClone(loopIntake);
          await intakeGate;
        }
        const events = body.controlled_trip_identity ? [
          { type: 'chat_start', session_id: 'intake-e2e', run_id: 'trip-intake', message_id: 'assistant-run', route_decision: routeDecision },
          { type: 'approval_gate_raised', run_id: 'trip-intake', gate: 'plan', run_status: 'awaiting_input', payload: { gate: 'plan', revision: 0, revision_limit: 2, decision_options: ['approve', 'supplement', 'cancel'], plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '安排适合独自旅行的海边路线' } }] }, plan_text: '**本次旅行**：从上海出发，按青岛 → 苏州 → 南京 → 绍兴 → 宁波的顺序，2026-11-05 至 2026-11-10，独自旅行；偏好：经典均衡。\n\n**执行计划**\n### 步骤 1：目的地调研\n- **目的地调研**：安排适合独自旅行的海边路线\n\n**待核实或需要取舍**：海边天气与每日节奏是否适合独自出行', recognized_requirements: { hard: [], preferences: [{ requirement_id: 'solo', summary: '第一次独自旅行' }], attention: [{ requirement_id: 'duration', summary: '需要进一步说明：2—3天' }] }, unresolved_requirement_ids: ['duration'] } },
          { type: 'chat_complete', run_id: 'trip-intake', run_status: 'awaiting_input' },
        ] : [{ type: 'guided_intake', session_id: 'intake-e2e', guided_intake: pending }, { type: 'chat_complete' }];
        return route.fulfill({ status: 200, contentType: 'text/event-stream', body: events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('') });
      }
      if (path === '/sessions/intake-e2e/intake') { pending = route.request().postDataJSON(); return json(pending); }
      if (path === '/places/search') {
        const query = new URL(route.request().url()).searchParams.get('q') ?? '';
        const destinations = ['上海', '苏州', '南京', '宁波', '绍兴', '青岛'] as const;
        const ids = { 上海: '1', 苏州: '3', 南京: '4', 宁波: '5', 绍兴: '6', 青岛: '2' } as const;
        const name = destinations.find((item) => query.includes(item)) ?? '青岛';
        return json({ candidates: [{ place: place(name, ids[name]), confidence: 1, requires_confirmation: true }] });
      }
      const summary = { session_id: 'intake-e2e', title: '海边独旅', status: 'active', mode: 'deep', last_message_preview: '', created_at: '2026-10-28', updated_at: '2026-10-28' };
      if (path === '/user/sessions') return json([summary]);
      if (path === '/user/sessions/intake-e2e') { sessionLoaded = true; return json({ ...summary, messages: [], pending_clarify: pending, next_before: null, has_more: false }); }
      if (path === '/trip-runs') return json({ runs: [], total: 0 });
      if (path === '/trip-runs/trip-intake/events') return json({ run_id: 'trip-intake', requested_after_sequence: 0, replay_floor_sequence: 0, latest_sequence: 0, next_after_sequence: 0, window_expired: false, current_bundle_id: null, run_status: 'awaiting_input', events: [] });
      if (path === '/product/trip-planner') return json({ primary_styles: [{ id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 5000, inspiration_prompts: ['想去海边', '第一次独自旅行', '轻松一点'] });
      if (path === '/user/default-origin') return json({ place: null });
      if (path === '/presets' || path === '/user/preference-options') return json([]);
      if (path === '/user/profile') return json({ preferences: {} });
      if (path === '/user/memory/facts') return json({ facts: [] });
      return json({});
    });
    await page.goto('/');
    await expect.poll(() => sessionLoaded).toBe(true);
    await page.emulateMedia({ reducedMotion: mobile ? 'reduce' : 'no-preference' });
    await page.screenshot({ path: `../output/polish/20261029-1252-inline-intake/${mobile ? 'home-390-initial' : 'home-2000-initial'}.png`, fullPage: true });
    await page.getByTestId('new-trip-hero').evaluate((element) => element.setAttribute('data-mount-probe', 'kept'));
    await page.getByRole('textbox', { name: '一句话描述旅行', exact: true }).fill(loopIntake.raw_input);
    await page.getByRole('button', { name: '开始规划', exact: true }).click();
    await expect(page.getByTestId('new-trip-hero')).toHaveAttribute('data-mount-probe', 'kept');
    await expect(page.getByTestId('travel-atlas')).toBeVisible();
    await expect(page.locator('.planner-home-flow-status')).toContainText('正在理解你的旅行想法');
    await expect(page.getByTestId('guided-intake')).toHaveCount(0);
    await page.screenshot({ path: `../output/polish/20261029-1252-inline-intake/${mobile ? 'home-390-waiting' : 'home-2000-waiting'}.png`, fullPage: true });
    expect(requests).toHaveLength(1);
    releaseIntake?.();
    await expect(page.getByTestId('guided-intake')).toBeVisible();
    await expect(page.locator('.new-trip-content > .planner-card').getByTestId('guided-intake')).toBeVisible();
    await expect(page.getByTestId('new-trip-hero')).toHaveAttribute('data-mount-probe', 'kept');
    await expect(page.getByRole('button', { name: '按合理默认安排，不再补充', exact: true })).toBeVisible();
    await expect(page.getByText('不确定时可以选择「按合理默认安排，不再补充」', { exact: false })).toBeVisible();
    await expect(page.getByRole('heading', { name: '确认旅行信息', exact: true })).toBeVisible();
    await expect(page.getByText('信息已经足够了，正在为你开始规划。')).toHaveCount(0);
    mkdirSync('../output/polish/20261030-0108-requirement-research-plan', { recursive: true });
    await page.getByRole('button', { name: '按合理默认安排，不再补充', exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../output/polish/20261030-0108-requirement-research-plan/intake-${mobile ? '390' : '2000'}-question.png`, fullPage: true });
    await page.screenshot({ path: `../output/polish/20261029-1252-inline-intake/${mobile ? 'home-390-expanded' : 'home-2000-expanded'}.png`, fullPage: true });
    await page.getByRole('button', { name: '按合理默认安排，不再补充', exact: true }).click();
    await expect.poll(() => pending?.answers[0]?.selected_option_ids).toEqual(['sensible_default']);
    await page.reload();
    await expect(page.getByTestId('new-trip-hero')).toBeVisible();
    await expect(page.getByTestId('guided-intake')).toBeVisible();
    await expect(page.getByRole('button', { name: /5000元包括往返交通和住宿吗/ })).toContainText('按合理默认安排，不再补充');
    await page.getByRole('textbox', { name: '出发地', exact: true }).fill('上海');
    await page.getByRole('button', { name: '上海 上海，中国', exact: true }).click();
    await page.getByRole('button', { name: /青岛 城市交通便利/ }).click();
    await page.getByRole('button', { name: '青岛 青岛，中国', exact: true }).click();
    await expect(page.getByTestId('destination-token-0')).toContainText('青岛');
    await expect(page.locator('.destination-search')).toHaveCount(0);
    await page.getByTestId('add-destination').click();
    const secondDestination = page.locator('.destination-search input');
    await expect(secondDestination).toBeFocused();
    await secondDestination.fill('苏州');
    await page.getByRole('button', { name: '苏州 苏州，中国', exact: true }).click();
    await expect(page.getByTestId('destination-token-1')).toContainText('苏州');
    const chipBox = (await page.getByTestId('destination-token-0').boundingBox())!;
    const flowBox = (await page.locator('.destination-token-flow').boundingBox())!;
    expect(chipBox.width).toBeLessThan(flowBox.width / 2);
    await page.getByTestId('destination-token-0').focus();
    await page.getByTestId('destination-token-0').press('ArrowDown');
    await expect(page.getByTestId('destination-token-0')).toContainText('苏州');
    await expect(page.getByTestId('destination-token-1')).toContainText('青岛');
    await page.screenshot({ path: `../output/polish/20261029-1252-destination-tokens/destination-r9r10-intake-two-sorted-${mobile ? '390' : '2000'}.png`, fullPage: true });
    for (const name of ['南京', '宁波', '绍兴']) {
      const search = page.locator('.destination-search input');
      await expect(search).toHaveCount(1);
      await search.fill(name);
      await page.getByRole('button', { name: `${name} ${name}，中国`, exact: true }).click();
    }
    await expect(page.locator('.destination-token')).toHaveCount(5);
    await expect(page.locator('.destination-search')).toHaveCount(0);
    await expect(page.getByTestId('add-destination')).toHaveText('目的地到达上限');
    const fiveBeforeDrag = await page.locator('.destination-token-name').allTextContents();
    expect(fiveBeforeDrag).toEqual(['苏州', '青岛', '南京', '宁波', '绍兴']);
    const fiveHandle = (await page.getByTestId('destination-token-0').boundingBox())!;
    const fiveSecond = (await page.getByTestId('destination-token-1').boundingBox())!;
    await page.mouse.move(fiveHandle.x + 10, fiveHandle.y + fiveHandle.height / 2);
    await page.mouse.down();
    await page.mouse.move(fiveSecond.x + fiveSecond.width / 2, fiveSecond.y + fiveSecond.height / 2, { steps: 6 });
    await page.mouse.up();
    await expect(page.getByTestId('destination-token-0')).toContainText('青岛');
    await expect(page.getByTestId('destination-token-1')).toContainText('苏州');
    const fiveAfterMouse = await page.locator('.destination-token-name').allTextContents();
    expect(fiveAfterMouse).toEqual(['青岛', '苏州', '南京', '宁波', '绍兴']);
    await page.getByTestId('destination-token-4').focus();
    await page.getByTestId('destination-token-4').press('ArrowUp');
    const fiveAfterKeyboard = await page.locator('.destination-token-name').allTextContents();
    expect(fiveAfterKeyboard).toEqual(['青岛', '苏州', '南京', '绍兴', '宁波']);
    await page.screenshot({ path: `../output/polish/20261029-1252-destination-tokens/destination-r9r10-intake-five-sorted-${mobile ? '390' : '2000'}.png`, fullPage: true });
    await page.screenshot({ path: `../output/polish/20261029-1252-inline-intake/${mobile ? 'home-390-answered' : 'home-2000-answered'}.png`, fullPage: true });
    const plannerCard = page.locator('.new-trip-content > .planner-card');
    const expandedHeight = (await plannerCard.boundingBox())!.height;
    await page.getByRole('button', { name: '确认信息并开始规划', exact: true }).click();
    if (!mobile) {
      const collapsed = page.getByTestId('guided-intake-collapsed');
      await expect(collapsed).toBeVisible();
      await expect(collapsed).toContainText('正在准备正式规划');
      await expect.poll(async () => (await plannerCard.boundingBox())?.height ?? Number.POSITIVE_INFINITY).toBeLessThan(expandedHeight - 180);
      await page.screenshot({ path: '../output/polish/20261029-1252-inline-intake/home-2000-collapsing.png', fullPage: true });
    } else {
      await page.screenshot({ path: '../output/polish/20261029-1252-inline-intake/home-390-collapsing.png', fullPage: true });
    }
    await expect(page.getByTestId('generation-journey-panel')).toBeVisible();
    await expect(page.getByTestId('generation-journey-panel').locator('.generation-planning-sidebar')).toBeVisible();
    await expect(page.getByTestId('generation-journey-panel').locator('.generation-trip-card')).toBeVisible();
    await expect(page.getByTestId('new-trip-hero')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: '确认这趟旅行', exact: true })).toHaveCount(0);
    await expect(page.getByTestId('trip-brief-plan-gate')).toContainText('第一次独自旅行');
    await expect(page.getByTestId('trip-brief-plan-gate')).toContainText('已识别的旅行要求');
    await expect(page.getByTestId('trip-brief-plan-gate')).toContainText('本次会这样研究');
    await expect(page.getByTestId('trip-brief-plan-gate')).toContainText('从上海出发，按青岛 → 苏州 → 南京 → 绍兴 → 宁波的顺序');
    await expect(page.getByTestId('trip-brief-plan-gate')).toContainText('安排适合独自旅行的海边路线');
    await expect(page.getByTestId('trip-brief-plan-gate')).toContainText('待核实或需要取舍');
    await expect(page.getByTestId('trip-brief-plan-gate')).not.toContainText('责任');
    await page.screenshot({ path: `../output/polish/20261030-0108-requirement-research-plan/gate-${mobile ? '390' : '2000'}-plan.png`, fullPage: true });
    if (!mobile) {
      const gateWidth = await page.getByTestId('trip-brief-plan-gate').evaluate(element => element.getBoundingClientRect().width);
      expect(gateWidth).toBeGreaterThan(600);
    }
    await expect(page.getByTestId('trip-brief-plan-gate')).not.toContainText('需要进一步说明：2—3天');
    await expect(page.getByRole('checkbox')).toHaveCount(0);
    await expect(page.getByRole('button', { name: '确认并开始生成', exact: true })).toBeEnabled();
    await expect(page.getByTestId('guided-intake')).toHaveCount(0);
    await expect(page.getByTestId('trip-brief-plan-gate')).toHaveCSS('opacity', '1');
    await expect(page.getByRole('heading', { name: '接下来，我们会这样安排' })).toHaveCount(0);
    await page.screenshot({ path: `../output/polish/20261029-1817-unified-planning-workspace/intake-${mobile ? '390' : '2000'}-gate.png`, fullPage: true });
    expect(requests).toHaveLength(2);
    expect(requests[1].controlled_trip_identity.destinations.map((item: { name: string }) => item.name)).toEqual(['青岛', '苏州', '南京', '绍兴', '宁波']);
    expect(requests[1].guided_intake.draft.confirmed_destinations.map((item: { name: string }) => item.name)).toEqual(['青岛', '苏州', '南京', '绍兴', '宁波']);
    expect(requests[1].guided_intake.answers[0].selected_option_ids).toEqual(['sensible_default']);
    expect(requests[1].guided_intake.raw_input).toBe(loopIntake.raw_input);
    mkdirSync('../output/polish/20261029-1252-destination-tokens', { recursive: true });
    writeFileSync(`../output/polish/20261029-1252-destination-tokens/destination-r9r10-intake-five-order-${mobile ? '390' : '2000'}.json`, JSON.stringify({
      before: fiveBeforeDrag,
      afterMouse: fiveAfterMouse,
      afterKeyboard: fiveAfterKeyboard,
      submitted: requests[1].controlled_trip_identity.destinations.map((item: { name: string }) => item.name),
    }, null, 2));
    expect(pageErrors).toEqual([]);
    await expect(page.getByTestId('guided-intake')).toHaveCount(0);
  });
}

test('确认开始失败时保留首页内表单与已确认地点，重试后进入正式规划', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let controlledAttempts = 0;
  let pending: any = structuredClone(intake);
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('sta_last_session_id', 'intake-retry'));
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.startsWith('/api/')) return route.continue();
    const path = pathname.slice(4);
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/chat-stream') {
      controlledAttempts += 1;
      if (controlledAttempts <= 3) return json({ detail: '服务暂时不可用' }, 503);
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: [
          { type: 'chat_start', session_id: 'intake-retry', run_id: 'trip-retry', message_id: 'assistant-retry', route_decision: routeDecision },
          { type: 'approval_gate_raised', run_id: 'trip-retry', gate: 'plan', run_status: 'awaiting_input', payload: { gate: 'plan', revision: 0, revision_limit: 2, decision_options: ['approve', 'supplement', 'cancel'], plan: { steps: [{ step: 1, agents: ['destination_researcher'], tasks: { destination_researcher: '安排海边路线' } }] }, recognized_requirements: { hard: [], preferences: [], attention: [] }, unresolved_requirement_ids: [] } },
          { type: 'chat_complete', run_id: 'trip-retry', run_status: 'awaiting_input' },
        ].map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
      });
    }
    if (path === '/sessions/intake-retry/intake') { pending = route.request().postDataJSON(); return json(pending); }
    if (path === '/places/search') {
      const query = new URL(route.request().url()).searchParams.get('q') ?? '';
      const name = query.includes('上海') ? '上海' : '青岛';
      return json({ candidates: [{ place: place(name, name === '上海' ? '11' : '12'), confidence: 1, requires_confirmation: true }] });
    }
    const summary = { session_id: 'intake-retry', title: '海边独旅', status: 'active', mode: 'deep', last_message_preview: '', created_at: '2026-10-28', updated_at: '2026-10-28' };
    if (path === '/user/sessions') return json([summary]);
    if (path === '/user/sessions/intake-retry') return json({ ...summary, messages: [], pending_clarify: pending, next_before: null, has_more: false });
    if (path === '/trip-runs') return json({ runs: [], total: 0 });
    if (path === '/product/trip-planner') return json({ primary_styles: [{ id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 5000, inspiration_prompts: [] });
    if (path === '/user/default-origin') return json({ place: null });
    if (path === '/presets' || path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: [] });
    return json({});
  });
  await page.goto('/');
  await expect(page.getByTestId('new-trip-hero')).toBeVisible();
  await expect(page.getByTestId('guided-intake')).toBeVisible();
  await page.getByRole('button', { name: '包括往返交通和住宿', exact: true }).click();
  await page.getByRole('textbox', { name: '出发地', exact: true }).fill('上海');
  await page.getByRole('button', { name: '上海 上海，中国', exact: true }).click();
  await page.getByRole('button', { name: /青岛 城市交通便利/ }).click();
  await page.getByRole('button', { name: '青岛 青岛，中国', exact: true }).click();
  await page.getByRole('button', { name: '确认信息并开始规划', exact: true }).click();
  await expect(page.getByText('暂时无法开始规划，旅行信息已保留，请重试。', { exact: true })).toBeVisible();
  await expect(page.getByTestId('new-trip-hero')).toBeVisible();
  await expect(page.getByTestId('guided-intake')).toBeVisible();
  await expect(page.getByRole('textbox', { name: '出发地', exact: true })).toHaveValue('上海');
  await expect(page.getByTestId('destination-token-0')).toContainText('青岛');
  await expect(page.getByRole('button', { name: '确认信息并开始规划', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '确认信息并开始规划', exact: true }).click();
  await expect(page.getByTestId('generation-journey-panel')).toBeVisible();
  await expect(page.getByTestId('generation-journey-panel').locator('.generation-planning-sidebar')).toBeVisible();
  await expect(page.getByTestId('trip-brief-plan-gate')).toBeVisible();
  await expect(page.getByTestId('new-trip-hero')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '确认这趟旅行', exact: true })).toHaveCount(0);
  expect(controlledAttempts).toBe(4);
  expect(pageErrors).toEqual([]);
});

test('延迟最终保存期间切回新旅行后不提交旧会话规划', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let pending: any = structuredClone(intake);
  let holdSave = false;
  let saveStarted = false;
  let releaseSave: (() => void) | null = null;
  const saveGate = new Promise<void>((resolve) => { releaseSave = resolve; });
  const streamRequests: any[] = [];
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('sta_last_session_id', 'intake-switch'));
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.startsWith('/api/')) return route.continue();
    const path = pathname.slice(4);
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/chat-stream') { streamRequests.push(route.request().postDataJSON()); return json({ detail: '不应提交' }, 500); }
    if (path === '/sessions/intake-switch/intake') {
      pending = route.request().postDataJSON();
      if (holdSave) {
        saveStarted = true;
        await saveGate;
      }
      return json(pending);
    }
    if (path === '/places/search') {
      const query = new URL(route.request().url()).searchParams.get('q') ?? '';
      const name = query.includes('上海') ? '上海' : '青岛';
      return json({ candidates: [{ place: place(name, name === '上海' ? '21' : '22'), confidence: 1, requires_confirmation: true }] });
    }
    const summary = { session_id: 'intake-switch', title: '待切换旅行', status: 'active', mode: 'deep', last_message_preview: '', created_at: '2026-10-28', updated_at: '2026-10-28' };
    if (path === '/user/sessions') return json([summary]);
    if (path === '/user/sessions/intake-switch') return json({ ...summary, messages: [], pending_clarify: pending, next_before: null, has_more: false });
    if (path === '/trip-runs') return json({ runs: [], total: 0 });
    if (path === '/product/trip-planner') return json({ primary_styles: [{ id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 5000, inspiration_prompts: [] });
    if (path === '/user/default-origin') return json({ place: null });
    if (path === '/presets' || path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: [] });
    return json({});
  });
  await page.goto('/');
  await expect(page.getByTestId('guided-intake')).toBeVisible();
  await page.getByRole('button', { name: '包括往返交通和住宿', exact: true }).click();
  await page.getByRole('textbox', { name: '出发地', exact: true }).fill('上海');
  await page.getByRole('button', { name: '上海 上海，中国', exact: true }).click();
  await page.getByRole('button', { name: /青岛 城市交通便利/ }).click();
  await page.getByRole('button', { name: '青岛 青岛，中国', exact: true }).click();
  holdSave = true;
  await page.getByRole('button', { name: '确认信息并开始规划', exact: true }).click();
  await expect.poll(() => saveStarted).toBe(true);
  await page.getByRole('link', { name: 'JourneyPilot 新旅行' }).click();
  await expect(page.getByTestId('natural-trip-input')).toBeVisible();
  await expect(page.getByTestId('guided-intake')).toHaveCount(0);
  releaseSave?.();
  await page.waitForTimeout(800);
  expect(streamRequests).toEqual([]);
  await expect(page.getByTestId('new-trip-hero')).toBeVisible();
  await expect(page.getByTestId('natural-trip-input')).toHaveValue('');
  expect(pageErrors).toEqual([]);
});

test('恢复多段未确认搜索草稿后自动保存、刷新并逐项确认', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let pending: any = structuredClone(intake);
  pending.draft.confirmed_destinations = [place('青岛', '31')];
  pending.draft.destination_queries = ['青岛', '苏州', '杭州'];
  const saves: any[] = [];
  await page.addInitScript(() => localStorage.setItem('sta_last_session_id', 'restore-query'));
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.startsWith('/api/')) return route.continue();
    const path = pathname.slice(4);
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/sessions/restore-query/intake') {
      pending = route.request().postDataJSON();
      saves.push(structuredClone(pending));
      return json(pending);
    }
    if (path === '/places/search') {
      const query = new URL(route.request().url()).searchParams.get('q') ?? '';
      const name = query.includes('苏州') ? '苏州' : query.includes('杭州') ? '杭州' : '青岛';
      const id = name === '苏州' ? '32' : name === '杭州' ? '33' : '31';
      return json({ candidates: [{ place: place(name, id), confidence: 1, requires_confirmation: true }] });
    }
    const summary = { session_id: 'restore-query', title: '恢复搜索草稿', status: 'active', mode: 'deep', last_message_preview: '', created_at: '2026-10-28', updated_at: '2026-10-28' };
    if (path === '/user/sessions') return json([summary]);
    if (path === '/user/sessions/restore-query') return json({ ...summary, messages: [], pending_clarify: pending, next_before: null, has_more: false });
    if (path === '/trip-runs') return json({ runs: [], total: 0 });
    if (path === '/product/trip-planner') return json({ primary_styles: [{ id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] }], secondary_interests: [], default_adults: 1, default_children: 0, default_elderly_companions: false, default_accessibility_required: false, max_secondary_interests: 3, inspiration_rotation_ms: 5000, inspiration_prompts: [] });
    if (path === '/user/default-origin') return json({ place: null });
    if (path === '/presets' || path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: [] });
    return json({});
  });

  const savedQueries = () => saves.at(-1)?.draft.destination_queries;
  const savedNames = () => saves.at(-1)?.draft.confirmed_destinations.map((item: { name: string }) => item.name);
  const search = page.locator('.destination-search input');
  const tokens = page.locator('.destination-token');

  await page.goto('/');
  await expect(page.getByTestId('destination-token-0')).toContainText('青岛');
  await expect(tokens).toHaveCount(1);
  await expect(search).toHaveValue('苏州');
  await expect.poll(() => saves.length).toBeGreaterThan(0);
  const firstSaveCount = saves.length;
  expect(savedQueries()).toEqual(['青岛', '苏州', '杭州']);
  expect(savedNames()).toEqual(['青岛']);

  await page.reload();
  await expect(tokens).toHaveCount(1);
  await expect(page.getByTestId('destination-token-0')).toContainText('青岛');
  await expect(search).toHaveValue('苏州');
  await expect.poll(() => saves.length).toBeGreaterThan(firstSaveCount);
  expect(savedQueries()).toEqual(['青岛', '苏州', '杭州']);
  expect(savedNames()).toEqual(['青岛']);

  await page.getByRole('button', { name: '苏州 苏州，中国', exact: true }).click();
  await expect(tokens).toHaveCount(2);
  await expect(page.getByTestId('destination-token-0')).toContainText('青岛');
  await expect(page.getByTestId('destination-token-1')).toContainText('苏州');
  await expect(search).toHaveValue('杭州');
  await expect.poll(savedNames).toEqual(['青岛', '苏州']);
  expect(savedQueries()).toEqual(['青岛', '苏州', '杭州']);

  const secondSaveCount = saves.length;
  await page.reload();
  await expect(tokens).toHaveCount(2);
  await expect(search).toHaveValue('杭州');
  await expect.poll(() => saves.length).toBeGreaterThan(secondSaveCount);
  expect(savedQueries()).toEqual(['青岛', '苏州', '杭州']);
  expect(savedNames()).toEqual(['青岛', '苏州']);

  await page.getByRole('button', { name: '杭州 杭州，中国', exact: true }).click();
  await expect(tokens).toHaveCount(3);
  await expect(page.getByTestId('destination-token-2')).toContainText('杭州');
  await expect.poll(savedNames).toEqual(['青岛', '苏州', '杭州']);
  expect(savedQueries()).toEqual(['青岛', '苏州', '杭州']);

  await page.reload();
  await expect(tokens).toHaveCount(3);
  await expect(page.getByTestId('destination-token-0')).toContainText('青岛');
  await expect(page.getByTestId('destination-token-1')).toContainText('苏州');
  await expect(page.getByTestId('destination-token-2')).toContainText('杭州');
  const threeConfirmedSaves = saves.length;

  pending.draft.confirmed_destinations = [place('青岛', '31')];
  pending.draft.destination_queries = ['青岛', '苏州', '杭州'];
  await page.reload();
  await expect(tokens).toHaveCount(1);
  await expect(search).toHaveValue('苏州');
  await expect.poll(() => saves.length).toBeGreaterThan(threeConfirmedSaves);
  await page.getByTestId('destination-token-0').locator('.destination-token-remove').click();
  await expect(tokens).toHaveCount(0);
  await expect(page.getByTestId('destination-token-field')).toHaveAttribute('data-state', 'base');
  await expect(search).toBeVisible();
  await expect(search).toHaveValue('苏州');
  await expect.poll(savedNames).toEqual([]);
  expect(savedQueries()).toEqual(['苏州', '杭州']);
  const afterLastDeleteSaves = saves.length;
  await page.reload();
  await expect(tokens).toHaveCount(0);
  await expect(search).toHaveValue('苏州');
  await expect.poll(() => saves.length).toBeGreaterThan(afterLastDeleteSaves);
  expect(savedQueries()).toEqual(['苏州', '杭州']);
  expect(savedNames()).toEqual([]);
  await page.getByRole('button', { name: '苏州 苏州，中国', exact: true }).click();
  await expect(tokens).toHaveCount(1);
  await expect(search).toHaveValue('杭州');
  await expect.poll(savedNames).toEqual(['苏州']);
  const afterResume = { queries: savedQueries(), names: savedNames() };
  mkdirSync('../output/polish/20261029-1252-destination-tokens', { recursive: true });
  writeFileSync('../output/polish/20261029-1252-destination-tokens/destination-r9r10-delete-last-queue.json', JSON.stringify({
    afterDelete: { confirmed: [], queries: ['苏州', '杭州'], draftVisible: '苏州' },
    afterReload: { queries: ['苏州', '杭州'], names: [] },
    afterResume,
    saves: saves.map((save) => ({
      confirmed: save.draft.confirmed_destinations.map((item: { name: string }) => item.name),
      queries: save.draft.destination_queries,
    })),
  }, null, 2));
  writeFileSync('../output/polish/20261029-1252-destination-tokens/destination-r9r10-draft-saves.json', JSON.stringify(
    saves.map((save) => ({
      confirmed: save.draft.confirmed_destinations.map((item: { name: string }) => item.name),
      queries: save.draft.destination_queries,
    })),
    null,
    2,
  ));
});


const handoffEvidence = '../output/polish/20261029-1252-inline-intake';
const plannerConfiguration = {
  primary_styles: [{ id: 'balanced', label: '经典均衡', is_default: true, inference_keywords: [] }],
  secondary_interests: [],
  default_adults: 1,
  default_children: 0,
  default_elderly_companions: false,
  default_accessibility_required: false,
  max_secondary_interests: 3,
  inspiration_rotation_ms: 5000,
  inspiration_prompts: [],
};

function readyGuidedIntake() {
  const value = structuredClone(intake);
  value.questions = [];
  value.answers = [];
  value.missing_fields = [];
  value.ready_to_create = true;
  value.draft = {
    ...value.draft,
    origin_query: '上海',
    destination_queries: ['青岛'],
    confirmed_origin: place('上海', '41'),
    confirmed_destinations: [place('青岛', '42')],
  };
  return value;
}

async function openHandoffFixture(page: Page, options: {
  sessionId: string;
  pending: unknown;
  runId: string;
  defaultOrigin?: unknown;
}) {
  const pageErrors: string[] = [];
  const consoleWarnings: string[] = [];
  const networkStreamRequests: string[] = [];
  let pending = structuredClone(options.pending);
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'warning' || message.type() === 'error') consoleWarnings.push(message.text());
  });
  await page.addInitScript((sessionId) => {
    localStorage.setItem('sta_last_session_id', sessionId);
    const state: {
      controller: ReadableStreamDefaultController<Uint8Array> | null;
      opened: boolean;
      requests: number;
    } = { controller: null, opened: false, requests: 0 };
    const win = window as unknown as {
      __handoffSse: {
        push: (event: unknown) => void;
        close: () => void;
        opened: () => boolean;
        requests: () => number;
      };
    };
    win.__handoffSse = {
      push(event) {
        state.controller?.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
      },
      close() {
        try { state.controller?.close(); } catch { /* stream already closed */ }
        state.controller = null;
      },
      opened: () => state.opened,
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
          state.opened = true;
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
  }, options.sessionId);
  await page.addInitScript(() => {
    const win = window as unknown as {
      __handoffProbe: {
        frames: Array<Record<string, unknown>>;
        start: () => void;
        stop: () => void;
      };
    };
    const probe = {
      frames: [] as Array<Record<string, unknown>>,
      stopped: false,
      start() {
        probe.stopped = false;
        probe.frames = [];
        const started = performance.now();
        let previous = '';
        const sample = () => {
          if (probe.stopped) return;
          const outgoing = document.querySelector<HTMLElement>('[data-testid="workspace-conversation"]');
          const journey = document.querySelector<HTMLElement>('[data-testid="journey-workspace"]');
          const panel = (element: HTMLElement | null) => {
            if (!element) return null;
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            const left = Math.max(0, rect.left);
            const top = Math.max(0, rect.top);
            const right = Math.min(window.innerWidth, rect.right);
            const bottom = Math.min(window.innerHeight, rect.bottom);
            const visibleWidth = Math.max(0, right - left);
            const visibleHeight = Math.max(0, bottom - top);
            const viewportRatio = (visibleWidth * visibleHeight) / (window.innerWidth * window.innerHeight);
            const opacity = Number.parseFloat(style.opacity);
            return {
              top: Math.round(rect.top * 10) / 10,
              left: Math.round(rect.left * 10) / 10,
              width: Math.round(rect.width * 10) / 10,
              height: Math.round(rect.height * 10) / 10,
              visibleWidth: Math.round(visibleWidth * 10) / 10,
              visibleHeight: Math.round(visibleHeight * 10) / 10,
              viewportRatio: Math.round(viewportRatio * 1000) / 1000,
              effectiveArea: Math.round(viewportRatio * opacity * 1000) / 1000,
              opacity: Math.round(opacity * 1000) / 1000,
              position: style.position,
            };
          };
          const contentVisible = (root: HTMLElement | null, selector: string) => {
            const node = root?.querySelector<HTMLElement>(selector);
            if (!node) return false;
            const rect = node.getBoundingClientRect();
            const style = getComputedStyle(node);
            return rect.width > 0
              && rect.height > 0
              && rect.bottom > 0
              && rect.top < window.innerHeight
              && rect.right > 0
              && rect.left < window.innerWidth
              && style.visibility !== 'hidden'
              && style.display !== 'none'
              && Number.parseFloat(style.opacity) > 0.01;
          };
          const snapshot = {
            outgoing: Boolean(outgoing),
            outgoingHome: Boolean(outgoing?.querySelector('[data-testid="new-trip-hero"]')),
            outgoingChatInput: Boolean(outgoing?.querySelector('[data-testid="brief-input"]')),
            outgoingIntake: Boolean(outgoing?.querySelector('[data-testid="guided-intake"], [data-testid="guided-intake-collapsed"]')),
            outgoingContentVisible: contentVisible(outgoing, '.new-trip-content'),
            outgoingHidden: outgoing?.getAttribute('aria-hidden') ?? null,
            outgoingInert: outgoing?.hasAttribute('inert') ?? null,
            outgoingPanel: panel(outgoing),
            journey: Boolean(journey),
            journeyThinking: Boolean(journey?.querySelector('[data-testid="thinking-chain"]')),
            journeyContentVisible: contentVisible(journey, '[data-testid="thinking-chain"]'),
            journeyPanel: panel(journey),
          };
          const key = JSON.stringify(snapshot);
          if (key !== previous) {
            probe.frames.push({ ms: Math.round(performance.now() - started), ...snapshot });
            previous = key;
          }
          if (performance.now() - started < 6000) requestAnimationFrame(sample);
        };
        requestAnimationFrame(sample);
      },
      stop() {
        probe.stopped = true;
      },
    };
    win.__handoffProbe = probe;
  });
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.startsWith('/api/')) return route.continue();
    const path = pathname.slice(4);
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/chat-stream') {
      networkStreamRequests.push(route.request().postData() ?? '');
      return json({ detail: 'chat-stream must stay synthetic in this handoff test' }, 500);
    }
    if (path === `/sessions/${options.sessionId}/intake`) {
      pending = route.request().postDataJSON();
      return json(pending);
    }
    if (path === '/places/search') {
      const query = new URL(route.request().url()).searchParams.get('q') ?? '';
      const name = query.includes('上海') ? '上海' : query.includes('苏州') ? '苏州' : '青岛';
      return json({ candidates: [{ place: place(name, name === '上海' ? '51' : name === '苏州' ? '53' : '52'), confidence: 1, requires_confirmation: true }] });
    }
    const summary = {
      session_id: options.sessionId,
      title: '离线交接样例',
      status: 'active',
      mode: 'deep',
      last_message_preview: '',
      created_at: '2026-10-28',
      updated_at: '2026-10-28',
    };
    if (path === '/user/sessions') return json([summary]);
    if (path === `/user/sessions/${options.sessionId}`) {
      return json({ ...summary, messages: [], pending_clarify: pending, next_before: null, has_more: false });
    }
    if (path === '/trip-runs') return json({ runs: [], total: 0 });
    if (path === `/trip-runs/${options.runId}/events`) {
      return json({
        run_id: options.runId,
        requested_after_sequence: 0,
        replay_floor_sequence: 0,
        latest_sequence: 0,
        next_after_sequence: 0,
        window_expired: false,
        current_bundle_id: null,
        run_status: 'running',
        events: [],
      });
    }
    if (path === '/product/trip-planner') return json(plannerConfiguration);
    if (path === '/user/default-origin') return json({ place: options.defaultOrigin ?? null });
    if (path === '/presets' || path === '/user/preference-options') return json([]);
    if (path === '/user/profile') return json({ preferences: {} });
    if (path === '/user/memory/facts') return json({ facts: [] });
    return json({});
  });
  return { pageErrors, consoleWarnings, networkStreamRequests };
}

const handoffRouteDecision = routeDecision;

function handoffChatStart(sessionId: string, runId: string) {
  return {
    type: 'chat_start',
    session_id: sessionId,
    run_id: runId,
    message_id: `assistant-${runId}`,
    route_decision: handoffRouteDecision,
  };
}

function handoffProgress(runId: string) {
  return {
    type: 'agent_progress',
    run_id: runId,
    agent_name: 'destination_researcher',
    content: '正在查找青岛的海边路线与适合独自旅行的体验',
    step_name: '调研目的地体验',
    progress_status: 'running',
    ts_ms: 1761740000000,
  };
}

async function chooseStructuredTrip(page: Page) {
  await page.getByRole('tab', { name: '按条件规划' }).click();
  await expect(page.getByTestId('destination-token-field')).toBeVisible();
  const search = page.locator('.destination-search input');
  await search.fill('青岛');
  const candidate = page.getByTestId('destination-candidates').getByRole('button').filter({ hasText: '青岛' }).first();
  await expect(candidate).toBeVisible();
  await candidate.click();
  await page.getByTestId('date-range-trigger').click();
  const dialog = page.getByTestId('date-range-dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: /^选择 2026-10-30/ }).click();
  await dialog.getByRole('button', { name: /^选择 2026-10-31/ }).click();
  await dialog.getByRole('button', { name: /^确认日期/ }).click();
  await expect(dialog).toHaveCount(0);
}

test('确认后旧首页保持到退场结束，延迟首帧在新工作区连续等待', async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 2000, height: 880 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  const fixture = await openHandoffFixture(page, {
    sessionId: 'handoff-guided',
    pending: readyGuidedIntake(),
    runId: 'trip-handoff-guided',
  });
  await page.goto('/');
  await expect(page.getByTestId('guided-intake')).toBeVisible();
  await page.screenshot({ path: `${handoffEvidence}/r6-handoff-2000-before-confirm.png`, fullPage: true });
  await page.evaluate(() => (window as unknown as { __handoffProbe: { start: () => void } }).__handoffProbe.start());
  await page.getByRole('button', { name: '确认信息并开始规划', exact: true }).click();
  await expect(page.getByTestId('guided-intake-collapsed')).toContainText('正在准备正式规划');
  await expect.poll(() => page.evaluate(() => (window as unknown as { __handoffSse: { opened: () => boolean } }).__handoffSse.opened())).toBe(true);
  await page.waitForTimeout(250);
  await expect(page.getByTestId('new-trip-hero')).toBeVisible();
  await expect(page.getByTestId('journey-workspace')).toHaveCount(0);
  await expect(page.getByTestId('workspace-conversation').getByTestId('brief-input')).toHaveCount(0);
  await page.screenshot({ path: `${handoffEvidence}/r6-handoff-2000-collapsing-waiting.png`, fullPage: true });

  await page.evaluate((event) => (window as unknown as { __handoffSse: { push: (value: unknown) => void } }).__handoffSse.push(event), handoffChatStart('handoff-guided', 'trip-handoff-guided'));
  await page.waitForTimeout(70);
  await page.screenshot({ path: `${handoffEvidence}/r6-handoff-2000-mid-transition.png` });
  await expect(page.getByTestId('journey-workspace')).toBeAttached();
  await expect(page.getByTestId('thinking-chain')).toContainText('整理旅行需求');
  await expect(page.getByTestId('thinking-chain')).toContainText('正在根据已确认的信息准备旅行计划');
  await expect.poll(() => page.evaluate(() => document.activeElement?.hasAttribute('data-workspace-handoff-focus') ?? false)).toBe(true);
  await expect(page.getByTestId('workspace-conversation')).toHaveCount(0);
  await page.screenshot({ path: `${handoffEvidence}/r6-handoff-2000-workspace-waiting.png`, fullPage: true });

  await page.evaluate((event) => (window as unknown as { __handoffSse: { push: (value: unknown) => void } }).__handoffSse.push(event), handoffProgress('trip-handoff-guided'));
  await expect(page.getByTestId('research-agent-destination')).toBeVisible();
  await expect(page.getByTestId('thinking-chain')).toContainText('查找旅行资料');
  await page.screenshot({ path: `${handoffEvidence}/r6-handoff-2000-first-progress.png`, fullPage: true });

  await page.evaluate((event) => (window as unknown as { __handoffSse: { push: (value: unknown) => void } }).__handoffSse.push(event), {
    type: 'run_failed',
    run_id: 'trip-handoff-guided',
    message: '离线合成：生成未完成，已保留本次旅行信息。',
    run_status: 'failed',
  });
  await expect(page.locator('.generation-progress > h2')).toHaveText('旅行规划未完成');
  await expect(page.getByText('离线合成：生成未完成，已保留本次旅行信息。', { exact: true })).toBeVisible();
  await expect(page.getByTestId('new-trip-hero')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '返回新旅行', exact: true })).toBeVisible();
  await page.screenshot({ path: `${handoffEvidence}/r6-handoff-2000-failure.png`, fullPage: true });

  const frames = await page.evaluate(() => {
    const probe = (window as unknown as { __handoffProbe: { stop: () => void; frames: Array<Record<string, unknown>> } }).__handoffProbe;
    probe.stop();
    return probe.frames;
  });
  await page.evaluate(() => (window as unknown as { __handoffSse: { close: () => void } }).__handoffSse.close());
  mkdirSync(handoffEvidence, { recursive: true });

  expect(frames.filter((frame) => frame.outgoing && (!frame.outgoingHome || frame.outgoingChatInput))).toEqual([]);
  const exiting = frames.filter((frame) => frame.outgoing && frame.outgoingHidden === 'true');
  expect(exiting.length).toBeGreaterThan(0);
  expect(exiting.every((frame) => frame.outgoingHome && frame.outgoingIntake)).toBe(true);
  const exitingWithoutInert = exiting.filter((frame) => frame.outgoingInert !== true);
  expect(exitingWithoutInert).toEqual([]);
  expect(exiting.every((frame) => (frame.outgoingPanel as { position?: string } | null)?.position === 'absolute')).toBe(true);
  expect(frames.some((frame) => frame.journey && frame.journeyThinking)).toBe(true);

  const relevantFrames = frames.filter((frame) => frame.outgoing || frame.journey);
  const panelVisibleArea = (frame: Record<string, unknown>) => Math.max(
    (frame.outgoingPanel as { effectiveArea?: number } | null)?.effectiveArea ?? 0,
    (frame.journeyPanel as { effectiveArea?: number } | null)?.effectiveArea ?? 0,
  );
  const blankFrames = relevantFrames.filter((frame) => panelVisibleArea(frame) < 0.02);
  expect(blankFrames).toEqual([]);
  const blankContentFrames = relevantFrames.filter((frame) => {
    const outgoingArea = (frame.outgoingPanel as { effectiveArea?: number } | null)?.effectiveArea ?? 0;
    const journeyArea = (frame.journeyPanel as { effectiveArea?: number } | null)?.effectiveArea ?? 0;
    return !((Boolean(frame.outgoingContentVisible) && outgoingArea >= 0.02)
      || (Boolean(frame.journeyContentVisible) && journeyArea >= 0.02));
  });
  expect(blankContentFrames).toEqual([]);
  const journeyOutsideViewport = frames.filter((frame) => {
    const panel = frame.journeyPanel as { opacity?: number; viewportRatio?: number } | null;
    return frame.journey && (panel?.opacity ?? 0) > 0.05 && (panel?.viewportRatio ?? 0) < 0.8;
  });
  expect(journeyOutsideViewport).toEqual([]);
  const outgoingOutsideViewport = exiting.filter((frame) => ((frame.outgoingPanel as { viewportRatio?: number } | null)?.viewportRatio ?? 0) < 0.8);
  expect(outgoingOutsideViewport).toEqual([]);
  const refWarnings = fixture.consoleWarnings.filter((text) => /cannot be given refs|PopChild/i.test(text));
  expect(refWarnings).toEqual([]);

  writeFileSync(`${handoffEvidence}/r6-handoff-2000-normal.json`, JSON.stringify({
    fixture: 'synthetic restored intake; chat-stream segmented in page; all API offline',
    summary: {
      outgoingFrames: frames.filter((frame) => frame.outgoing).length,
      exitingFrames: exiting.length,
      exitingAllInert: exiting.every((frame) => frame.outgoingInert === true),
      minimumVisibleArea: Math.min(...relevantFrames.map(panelVisibleArea)),
      blankFrames: blankFrames.length,
      blankContentFrames: blankContentFrames.length,
      journeyOutsideViewport: journeyOutsideViewport.length,
      outgoingOutsideViewport: outgoingOutsideViewport.length,
      refWarnings,
    },
    frames,
    pageErrors: fixture.pageErrors,
    consoleWarnings: fixture.consoleWarnings,
    networkStreamRequests: fixture.networkStreamRequests,
  }, null, 2));

  expect(fixture.pageErrors).toEqual([]);
  expect(fixture.networkStreamRequests).toEqual([]);
});

test('条件规划直接开始 reduced-motion 无等待交接，旧运行不污染新旅行', async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.clock.setFixedTime(new Date('2026-10-29T10:00:00+08:00'));
  const fixture = await openHandoffFixture(page, {
    sessionId: 'handoff-direct',
    pending: null,
    runId: 'trip-handoff-direct',
    defaultOrigin: place('上海', '61'),
  });
  await page.goto('/');
  await expect(page.getByTestId('natural-trip-input')).toBeVisible();
  await chooseStructuredTrip(page);
  await page.evaluate(() => (window as unknown as { __handoffProbe: { start: () => void } }).__handoffProbe.start());
  await page.getByRole('button', { name: '开始规划', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __handoffSse: { opened: () => boolean } }).__handoffSse.opened())).toBe(true);
  await page.waitForTimeout(200);
  await expect(page.getByTestId('new-trip-hero')).toBeVisible();
  await expect(page.getByTestId('journey-workspace')).toHaveCount(0);
  await expect(page.getByTestId('workspace-conversation').getByTestId('brief-input')).toHaveCount(0);
  await page.screenshot({ path: `${handoffEvidence}/r6-handoff-390-reduced-waiting-chat-start.png`, fullPage: true });

  const visibleMs = await page.evaluate((event) => new Promise<number>((resolve) => {
    const control = (window as unknown as { __handoffSse: { push: (value: unknown) => void } }).__handoffSse;
    const started = performance.now();
    control.push(event);
    const sample = () => {
      const target = document.querySelector<HTMLElement>('[data-testid="journey-workspace"]');
      if (target && Number.parseFloat(getComputedStyle(target).opacity) >= 0.99) {
        resolve(performance.now() - started);
        return;
      }
      if (performance.now() - started > 1500) {
        resolve(9999);
        return;
      }
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  }), handoffChatStart('handoff-direct', 'trip-handoff-direct'));
  expect(visibleMs).toBeLessThan(200);
  await expect(page.getByTestId('thinking-chain')).toContainText('整理旅行需求');
  await expect(page.getByTestId('thinking-chain')).toContainText('正在整理旅行信息');
  await expect.poll(() => page.evaluate(() => document.activeElement?.hasAttribute('data-workspace-handoff-focus') ?? false)).toBe(true);
  await page.screenshot({ path: `${handoffEvidence}/r6-handoff-390-reduced-workspace-waiting.png`, fullPage: true });
  const handoffFrames = await page.evaluate(() => {
    const probe = (window as unknown as { __handoffProbe: { frames: Array<Record<string, unknown>> } }).__handoffProbe;
    return probe.frames.slice();
  });

  await page.getByRole('link', { name: 'JourneyPilot 新旅行' }).click();
  await expect(page.getByTestId('new-trip-hero')).toBeVisible();
  await expect(page.getByTestId('journey-workspace')).toHaveCount(0);
  await expect(page.getByTestId('natural-trip-input')).toHaveValue('');
  const oldEventsAccepted = await page.evaluate((events) => {
    try {
      const control = (window as unknown as { __handoffSse: { push: (value: unknown) => void } }).__handoffSse;
      for (const event of events) control.push(event);
      return true;
    } catch {
      return false;
    }
  }, [handoffProgress('trip-handoff-direct'), {
    type: 'run_failed',
    run_id: 'trip-handoff-direct',
    message: '离线旧运行失败，不应回写新旅行。',
    run_status: 'failed',
  }]);
  await page.waitForTimeout(300);
  await expect(page.getByTestId('new-trip-hero')).toBeVisible();
  await expect(page.getByTestId('generation-journey-panel')).toHaveCount(0);
  await expect(page.getByText('离线旧运行失败，不应回写新旅行。', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: `${handoffEvidence}/r6-handoff-390-reduced-switched-new-trip.png`, fullPage: true });

  const frames = await page.evaluate(() => {
    const probe = (window as unknown as { __handoffProbe: { stop: () => void; frames: Array<Record<string, unknown>> } }).__handoffProbe;
    probe.stop();
    return probe.frames;
  });
  await page.evaluate(() => (window as unknown as { __handoffSse: { close: () => void } }).__handoffSse.close());
  mkdirSync(handoffEvidence, { recursive: true });
  const handoffRelevantFrames = handoffFrames.filter((frame) => frame.outgoing || frame.journey);
  const handoffBlankFrames = handoffRelevantFrames.filter((frame) => Math.max(
    (frame.outgoingPanel as { effectiveArea?: number } | null)?.effectiveArea ?? 0,
    (frame.journeyPanel as { effectiveArea?: number } | null)?.effectiveArea ?? 0,
  ) < 0.02);
  const handoffBlankContentFrames = handoffRelevantFrames.filter((frame) => {
    const outgoingArea = (frame.outgoingPanel as { effectiveArea?: number } | null)?.effectiveArea ?? 0;
    const journeyArea = (frame.journeyPanel as { effectiveArea?: number } | null)?.effectiveArea ?? 0;
    return !((Boolean(frame.outgoingContentVisible) && outgoingArea >= 0.02)
      || (Boolean(frame.journeyContentVisible) && journeyArea >= 0.02));
  });
  const handoffJourneyOutsideViewport = handoffFrames.filter((frame) => {
    const panel = frame.journeyPanel as { opacity?: number; viewportRatio?: number } | null;
    return frame.journey && (panel?.opacity ?? 0) > 0.05 && (panel?.viewportRatio ?? 0) < 0.8;
  });
  const refWarnings = fixture.consoleWarnings.filter((text) => /cannot be given refs|PopChild/i.test(text));
  writeFileSync(`${handoffEvidence}/r6-handoff-390-reduced.json`, JSON.stringify({
    fixture: 'synthetic structured trip; reduced-motion; chat-stream segmented in page; all API offline',
    visibleMs,
    oldEventsAccepted,
    summary: {
      handoffFrames: handoffFrames.length,
      handoffBlankFrames: handoffBlankFrames.length,
      handoffBlankContentFrames: handoffBlankContentFrames.length,
      handoffJourneyOutsideViewport: handoffJourneyOutsideViewport.length,
      refWarnings,
    },
    handoffFrames,
    frames,
    pageErrors: fixture.pageErrors,
    consoleWarnings: fixture.consoleWarnings,
    networkStreamRequests: fixture.networkStreamRequests,
  }, null, 2));

  expect(handoffBlankFrames).toEqual([]);
  expect(handoffBlankContentFrames).toEqual([]);
  expect(handoffJourneyOutsideViewport).toEqual([]);
  expect(refWarnings).toEqual([]);
  expect(frames.filter((frame) => frame.outgoing && (!frame.outgoingHome || frame.outgoingChatInput))).toEqual([]);
  expect(fixture.pageErrors).toEqual([]);
  expect(fixture.networkStreamRequests).toEqual([]);
});
