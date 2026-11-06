// 使用正式工作台、导航和状态投影；场景仅在浏览器内构造，不调用模型或数据库。
import React from 'react';
import { createRoot } from 'react-dom/client';
import { AppProvider } from '../../src/app/state/AppProvider';
import { useApp } from '../../src/app/state/AppContext';
import { MainLayout } from '../../src/app/layout/MainLayout';
import { TripWorkspaceShell } from '../../src/app/layout/TripWorkspaceShell';
import { MotionProviders } from '../../src/app/motion/MotionProviders';
import type { ThinkingStep } from '../../src/features/chat/types/messages';
import type { ControlledTripIdentity, UnderstandingQuestion } from '../../src/features/travel/types/planner';
import type { PlanApprovalGate } from '../../src/features/travel/types/planning';
import type { TripRunStatus } from '../../src/features/travel/types/runs';
import { deliveryBundle } from './sessionData';
import type { GenerationWorkspaceScene } from './generationWorkspace';
import '../../src/index.css';
import '../../src/styles/home.css';
import '../../src/styles/layout.css';
import '../../src/styles/workspace.css';

const runId = 'run-generation-workspace';
const stamp = new Date(Date.now() - 72_000);
const place = (name: string) => ({ place_id: `manual:${name}`, provider: 'manual_verified' as const, kind: 'city' as const, name, display_name: `${name}，中国`, country_code: 'CN', latitude: 30.6, longitude: 104, admin_path: ['中国', name] });
const identity: ControlledTripIdentity = {
  origin: place('上海'), destinations: [place('成都'), place('重庆')], start_date: '2026-12-01', end_date: '2026-12-07', dates_assumed: false,
  party: { total: 2, adults: 2, children: 0, elderly_companions: false, accessibility_required: false },
  style: { primary: '轻松慢游', secondary_interests: ['当地美食'], source: 'current' },
};
const step = (id: string, agentName: string, extra: Partial<ThinkingStep>): ThinkingStep => ({ id, agentName, stepName: agentName, timestamp: stamp, content: '', ...extra });
const research: ThinkingStep[] = [
  step('requirements', '整理旅行需求', { progressStatus: 'completed' }),
  step('destination-end', '目的地调研', { progressStatus: 'completed', content: '已整理成都与重庆的街区、美食与文化体验。' }),
  step('destination-place', '目的地调研', { isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"成都 玉林路"}', toolStatus: 'completed', toolResult: '找到 1 处街区资料', resultPreview: [{ title: '玉林路', detail: '成都武侯区，适合安排街区散步。', url: 'https://example.org/generation/yulin' }] }),
  step('transport-start', '交通查询', { progressStatus: 'running', content: '正在比较成都与重庆之间的城际交通。' }),
  step('train', '交通查询', { isToolCall: true, toolCallId: 'train-1', toolName: 'train_search', toolArgs: '{"from_name":"成都东","to_name":"重庆北","date":"2026-12-04"}', toolStatus: 'completed', toolResult: '已找到直达车次，正在核对两端车站的市内衔接。', resultPreview: [{ title: '成都东 → 重庆北', detail: '成都东出发，重庆北到达。', url: 'https://example.org/generation/train' }] }),
  step('transport-note', '交通查询', { kind: 'work_explanation', content: '会同时比较车站位置与到达后进入市区的交通。' }),
  step('stay-start', '住宿查询', { progressStatus: 'running', content: '正在比较靠近地铁、方便每天出行的住宿区域。' }),
  step('stay-tool', '住宿查询', { isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"春熙路 解放碑 住宿"}', toolStatus: 'running' }),
];
const gate: PlanApprovalGate = {
  gate: 'plan', runId, status: 'pending', source: 'restored', approvalToken: 'offline-generation-plan', revision: 0,
  decisionOptions: ['approve', 'supplement', 'cancel'], steps: [{ step: 1, agents: ['destination_researcher'] }, { step: 2, agents: ['transport_researcher', 'accommodation_researcher'] }],
  planText: '## 街区与当地生活\n\n围绕成都、重庆的老街区、美食和文化体验展开，午后留出休息时间。\n\n## 交通与住宿\n\n比较两城之间的交通衔接和方便出行的住宿区域，再组合每天路线。\n\n## 每日安排\n\n每天集中在相近区域，在散步、参观和休息之间留出余量。',
};
const questions: UnderstandingQuestion[] = [
  { id: 'pace', kind: 'single', question: '这趟旅行更想慢慢逛，还是多看几个地方？', options: [{ id: 'slow', label: '慢慢逛，留出休息时间' }, { id: 'full', label: '多看几个地方' }] },
  { id: 'interests', kind: 'multiple', question: '有哪些想多安排一些的体验？', options: [{ id: 'food', label: '当地美食' }, { id: 'culture', label: '街区与文化' }, { id: 'nature', label: '山水风景' }] },
  { id: 'dates', kind: 'date_range', question: '准备什么时候出发？', options: [] },
  { id: 'other', kind: 'single', question: '还有什么希望照顾到的地方？', options: [] },
];


function Harness() {
  const { dispatch } = useApp();
  const setScene = React.useCallback((scene: GenerationWorkspaceScene) => {
    dispatch({ type: 'SESSION_INITIALIZED' });
    dispatch({ type: 'SET_SIDEBAR_COLLAPSED', payload: true });
    dispatch({ type: 'SET_SESSION_ID', payload: 'generation-workspace' });
    dispatch({ type: 'SET_PLAN_APPROVAL_GATE', payload: null });
    dispatch({ type: 'SET_UNDERSTANDING_QUESTIONS', payload: null });
    dispatch({ type: 'SET_TRIP_SUMMARY_CARD', payload: null });
    dispatch({ type: 'CLEAR_SESSION_LOAD_ERROR' });
    if (scene === 'home') { dispatch({ type: 'CLEAR_CHAT' }); return; }
    const isPlan = scene.startsWith('plan');
    const isQuestion = ['questions', 'question-next', 'location-retry', 'research-retry'].includes(scene);
    const statuses: Partial<Record<GenerationWorkspaceScene, TripRunStatus>> = { completed: 'completed', partial: 'completed', failed: 'failed', cancelled: 'cancelled', stopping: 'cancel_requested', interrupted: 'interrupted', unrecoverable: 'interrupted', readonly: 'interrupted' };
    const status = isPlan || isQuestion ? 'awaiting_input' : statuses[scene] ?? 'running';
    dispatch({ type: 'SET_CURRENT_TRIP_RUN', payload: { runId, source: 'live', status, readOnly: scene === 'readonly' } });
    dispatch({ type: 'ENTER_WORKSPACE' });
    dispatch({ type: 'SET_TRIP_RUN_RECOVERY', payload: ['interrupted', 'readonly'].includes(scene) ? { status: 'resume_available', resumable: true, reason: null } : null });
    dispatch({ type: 'SET_CONTROLLED_TRIP_IDENTITY', payload: scene === 'pending' ? { ...identity, destinations: [], start_date: null, end_date: null, party: { total: null, adults: null, children: 0, elderly_companions: false, accessibility_required: false } } : scene === 'assumed' ? { ...identity, dates_assumed: true } : scene === 'long' ? { ...identity, destinations: ['克孜勒苏柯尔克孜自治州', '呼伦贝尔', '锡林郭勒', '阿拉善左旗', '额济纳旗'].map(place) } : identity });
    dispatch({ type: 'SET_STREAMING', payload: !isPlan && !isQuestion && ['running', 'cancel_requested'].includes(status) });
    if (scene === 'partial') {
      const bundle = deliveryBundle();
      bundle.manifest.run_id = runId;
      bundle.workspace.run_id = runId;
      (bundle.workspace.itinerary.unresolved as string[]).push('第 2 天傍晚尚未安排具体活动。');
      dispatch({ type: 'CONFIRM_DELIVERY_BUNDLE', payload: bundle });
    }
    dispatch({ type: 'SET_DELIVERY_BUNDLE_LOAD_STATE', payload: scene === 'recovery-loading' ? { status: 'loading', message: null } : scene === 'recovery-error' ? { status: 'error', message: '暂时无法重新加载这趟旅行。' } : { status: 'idle', message: null } });
    let steps = isPlan || isQuestion || scene === 'empty' || scene === 'pending' ? [] : [...research];
    if (scene === 'research-retry') steps = [...research, step('transport-failed', '交通查询', { progressStatus: 'failed' }), step('stay-complete', '住宿查询', { progressStatus: 'completed', content: '住宿区域资料已保留。' })];
    if (scene === 'route' || scene === 'redo') steps.push(step('route', '行程规划', { progressStatus: 'running', content: '正在把街区、交通和住宿组合成每天路线。' }));
    if (scene === 'redo') steps.push(step('redo', '目的地调研（第2轮补充）', { progressStatus: 'running', content: '正在按路线安排补充查询雨天备选。' }));
    if (scene === 'delivery') steps.push(step('delivery', '生成完整计划', { progressStatus: 'running', content: '正在整理日程、地图和阅读版。' }));
    dispatch({ type: 'SET_THINKING_STEPS', payload: steps });
    dispatch({ type: 'ADD_MESSAGE', payload: { id: `generation-${scene}-${Date.now()}`, role: 'assistant', runId, content: scene === 'failed' ? '这次规划未能完成，旅行要求已保留。' : '', displayContent: scene === 'failed' ? '这次规划未能完成，旅行要求已保留。' : '', type: scene === 'failed' ? 'error' : 'normal', timestamp: stamp, thinkingSteps: steps } });
    if (isPlan) dispatch({ type: 'SET_PLAN_APPROVAL_GATE', payload: { ...gate, source: scene === 'plan-live' ? 'live' : 'restored', planText: scene === 'plan-empty' ? '' : gate.planText, decisionOptions: scene === 'plan-failed' ? ['retry', 'supplement', 'cancel'] : gate.decisionOptions } });
    if (isQuestion) dispatch({ type: 'SET_UNDERSTANDING_QUESTIONS', payload: { runId, revision: scene === 'question-next' ? 1 : 0, approvalToken: 'offline-question', questions: scene === 'questions' ? questions : scene === 'question-next' ? [{ ...questions[0], question: '第二轮只确认节奏，还想调整吗？' }] : [], retryLocation: scene === 'location-retry', retryResearch: scene === 'research-retry', message: scene === 'research-retry' ? '交通查询未完成；目的地与住宿成果已保留。本次重试仍受当前研究时限限制。' : undefined } });
  }, [dispatch]);
  React.useEffect(() => {
    window.__generationWorkspace = { setScene, dispatch };
    setScene((new URLSearchParams(window.location.search).get('scene') as GenerationWorkspaceScene) || 'research');
  }, [setScene, dispatch]);
  return <MainLayout><TripWorkspaceShell /></MainLayout>;
}
createRoot(document.getElementById('root')!).render(<AppProvider><MotionProviders><Harness /></MotionProviders></AppProvider>);
