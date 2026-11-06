// 确定性的生成工作区组件夹具，不调用模型或后端。
import { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { AppProvider } from '../../src/app/state/AppProvider';
import { useApp } from '../../src/app/state/AppContext';
import { GenerationJourneyPanel } from '../../src/features/travel/components/workspace/GenerationJourneyPanel';
import '../../src/index.css';

const timestamp = new Date();
const place = (name: string) => ({ place_id: `osm:relation:${name}`, provider: 'osm' as const, kind: 'city' as const, name, display_name: `${name}，中国`, country_code: 'CN', latitude: 31.2, longitude: 121.4, admin_path: ['中国', name] });

function Fixture() {
  const { dispatch } = useApp();
  useEffect(() => {
    dispatch({
      type: 'SET_CONTROLLED_TRIP_IDENTITY',
      payload: {
        origin: place('深圳'),
        destinations: [place('北京'), place('上海'), place('长春')],
        start_date: '2026-11-02',
        end_date: '2026-11-12',
        dates_assumed: false,
        party: { total: 2, adults: 2, children: 0, elderly_companions: false, accessibility_required: false },
        style: { primary: '经典均衡', secondary_interests: ['当地美食'], source: 'current' },
      },
    });
    dispatch({ type: 'SET_CURRENT_TRIP_RUN', payload: { runId: 'run-generation-fixture', source: 'live', status: 'running' } });
    dispatch({ type: 'SET_STREAMING', payload: true });
    dispatch({
      type: 'ADD_THINKING_STEP',
      payload: { id: 'planning', agentName: 'understanding_agent', content: '正在整理需求并查询相关资料', stepName: '整理旅行需求', timestamp, progressStatus: 'running' },
    });
    (window as unknown as { __generationFixture?: unknown }).__generationFixture = {
      addResearch() {
        // 串行链上研究开始前，需求理解已留下完成记录。
        dispatch({
          type: 'ADD_THINKING_STEP',
          payload: { id: 'planning-completed', agentName: 'understanding_agent', content: '', stepName: '整理旅行需求', timestamp: new Date(), progressStatus: 'completed', endTime: new Date() },
        });
        dispatch({
          type: 'ADD_THINKING_STEP',
          payload: { id: 'destination', agentName: 'destination_researcher', content: '正在查找杭州与苏州的景点、美食和步行路线', stepName: '查询目的地体验', timestamp: new Date(), progressStatus: 'running' },
        });
        dispatch({
          type: 'ADD_THINKING_STEP',
          payload: { id: 'transport', agentName: 'transport_researcher', content: '', stepName: '查询城际交通', timestamp: new Date(), isToolCall: true, toolName: 'train_search', toolArgs: '{"from_name":"上海虹桥","to_name":"杭州东"}', toolResult: '已整理上海到杭州的火车衔接', toolStatus: 'completed', resultPreview: [{ title: '上海虹桥 → 杭州东', detail: '上午出发，约 1 小时到达', url: 'https://example.org/train' }] },
        });
      },
      compositionRedo() {
        // 组合补查 → 反馈目的地返研（带轮次显示名）→ 返研后继续组合：
        // 事件名与真实后端一致，用于验证真实工作台面板的焦点与归组。
        dispatch({
          type: 'ADD_THINKING_STEP',
          payload: { id: 'destination-completed', agentName: 'destination_researcher', content: '已整理 4 个目的地候选', stepName: '查询目的地体验', timestamp: new Date(), progressStatus: 'completed', endTime: new Date() },
        });
        dispatch({
          type: 'ADD_THINKING_STEP',
          payload: { id: 'composition-start', agentName: 'itinerary_planner', content: '正在把景点和交通排进每天路线', stepName: '行程规划', timestamp: new Date(), progressStatus: 'running' },
        });
        dispatch({
          type: 'ADD_THINKING_STEP',
          payload: { id: 'composition-query', agentName: 'itinerary_planner', content: '', stepName: '行程规划', timestamp: new Date(), isToolCall: true, toolName: 'global_route_search', toolArgs: '{"from_name":"西湖","to_name":"酒店"}', toolResult: '找到 1 条路线，门到门 25 分钟', toolStatus: 'completed' },
        });
        dispatch({
          type: 'ADD_THINKING_STEP',
          payload: { id: 'composition-redo', agentName: 'itinerary_planner', content: '行程安排依赖的目的地调研成果无法直接使用，已要求按反馈重做', stepName: '行程规划', timestamp: new Date(), progressStatus: 'completed', endTime: new Date() },
        });
        dispatch({
          type: 'ADD_THINKING_STEP',
          payload: { id: 'destination-redo', agentName: '目的地调研（第2轮补充）', content: '正在按组合反馈重新调查', stepName: '目的地调研（第2轮补充）', timestamp: new Date(), progressStatus: 'running' },
        });
        dispatch({
          type: 'ADD_THINKING_STEP',
          payload: { id: 'destination-redo-query', agentName: '目的地调研（第2轮补充）', content: '', stepName: '目的地调研（第2轮补充）', timestamp: new Date(), isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"可直接安排的真实景点"}', toolResult: '找到 2 个结果', toolStatus: 'completed', resultPreview: [{ title: '长影旧址博物馆', detail: '返研修正后的候选', url: 'https://example.org/changying' }] },
        });
      },
      compositionContinue() {
        dispatch({
          type: 'ADD_THINKING_STEP',
          payload: { id: 'composition-continue', agentName: 'itinerary_planner', content: '正在吸收返研成果继续安排每天路线', stepName: '行程规划', timestamp: new Date(), progressStatus: 'running' },
        });
      },
      longTitle() {
        dispatch({
          type: 'SET_CONTROLLED_TRIP_IDENTITY',
          payload: {
            origin: place('上海'),
            destinations: ['呼伦贝尔', '锡林郭勒', '阿拉善左旗', '额济纳旗', '乌兰浩特'].map(place),
            start_date: '2026-11-05',
            end_date: '2026-11-10',
            dates_assumed: false,
            party: { total: 2, adults: 2, children: 0, elderly_companions: false, accessibility_required: false },
            style: { primary: '经典均衡', secondary_interests: ['当地美食'], source: 'current' },
          },
        });
      },
      failAfterPlanning() {
        dispatch({
          type: 'SET_THINKING_STEPS',
          payload: [{ id: 'planning-completed', agentName: 'understanding_agent', content: '', stepName: '整理旅行需求', timestamp, endTime: new Date() }],
        });
        dispatch({ type: 'SET_STREAMING', payload: false });
        dispatch({ type: 'SET_TRIP_RUN_STATUS', payload: 'failed' });
        dispatch({ type: 'SET_CURRENT_TRIP_RUN', payload: { runId: 'run-generation-fixture', source: 'live', status: 'failed' } });
        dispatch({
          type: 'ADD_MESSAGE',
          payload: {
            id: 'generation-failure',
            runId: 'run-generation-fixture',
            role: 'assistant',
            content: '旅行方案暂时无法生成，请稍后重试。',
            displayContent: '旅行方案暂时无法生成，请稍后重试。',
            timestamp: new Date(),
            type: 'error',
          },
        });
      },
      cancelAfterPlanning() {
        dispatch({
          type: 'SET_THINKING_STEPS',
          payload: [{ id: 'planning-completed', agentName: 'understanding_agent', content: '', stepName: '整理旅行需求', timestamp, endTime: new Date() }],
        });
        dispatch({ type: 'SET_STREAMING', payload: false });
        dispatch({ type: 'SET_TRIP_RUN_STATUS', payload: 'cancelled' });
        dispatch({ type: 'SET_CURRENT_TRIP_RUN', payload: { runId: 'run-generation-fixture', source: 'live', status: 'cancelled' } });
      },
      requestCancelAfterPlanning() {
        dispatch({
          type: 'SET_THINKING_STEPS',
          payload: [{ id: 'planning-completed', agentName: 'understanding_agent', content: '', stepName: '整理旅行需求', timestamp, endTime: new Date() }],
        });
        dispatch({ type: 'SET_STREAMING', payload: false });
        dispatch({ type: 'SET_TRIP_RUN_STATUS', payload: 'cancel_requested' });
        dispatch({ type: 'SET_CURRENT_TRIP_RUN', payload: { runId: 'run-generation-fixture', source: 'live', status: 'cancel_requested' } });
      },
      finish() {
        dispatch({ type: 'SET_STREAMING', payload: false });
        dispatch({ type: 'SET_TRIP_RUN_STATUS', payload: 'completed' });
      },
    };
  }, [dispatch]);
  return (
    <main style={{ height: '100dvh', minHeight: 0 }}>
      <div className="generation-workspace" style={{ height: '100%' }}>
        <GenerationJourneyPanel />
      </div>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<AppProvider><Fixture /></AppProvider>);
