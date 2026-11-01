// 确定性的生成工作区组件夹具，不调用模型或后端。
import React, { useEffect } from 'react';
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
        party: { adults: 2, children: 0, elderly_companions: false, accessibility_required: false },
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
        dispatch({
          type: 'ADD_THINKING_STEP',
          payload: { id: 'destination', agentName: 'destination_researcher', content: '正在查找杭州与苏州的景点、美食和步行路线', stepName: '查询目的地体验', timestamp: new Date(), progressStatus: 'running' },
        });
        dispatch({
          type: 'ADD_THINKING_STEP',
          payload: { id: 'transport', agentName: 'transport_researcher', content: '', stepName: '查询城际交通', timestamp: new Date(), isToolCall: true, toolName: 'train_search', toolArgs: '{"from_name":"上海虹桥","to_name":"杭州东"}', toolResult: '已整理上海到杭州的火车衔接', toolStatus: 'completed', resultPreview: [{ title: '上海虹桥 → 杭州东', detail: '上午出发，约 1 小时到达', url: 'https://example.org/train' }] },
        });
      },
      specialParty() {
        dispatch({
          type: 'SET_CONTROLLED_TRIP_IDENTITY',
          payload: {
            origin: place('深圳'),
            destinations: [place('北京'), place('上海'), place('长春')],
            start_date: '2026-11-02',
            end_date: '2026-11-12',
            party: { adults: 2, children: 1, elderly_companions: true, accessibility_required: true },
            style: { primary: '轻松慢游', secondary_interests: ['当地美食', '人文体验'], source: 'current' },
          },
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
            party: { adults: 2, children: 0, elderly_companions: false, accessibility_required: false },
            style: { primary: '经典均衡', secondary_interests: ['当地美食'], source: 'current' },
          },
        });
      },
      longPlaceName() {
        dispatch({
          type: 'SET_CONTROLLED_TRIP_IDENTITY',
          payload: {
            origin: place('上海'),
            destinations: [place('克孜勒苏柯尔克孜自治州')],
            start_date: '2026-11-05',
            end_date: '2026-11-10',
            party: { adults: 2, children: 0, elderly_companions: false, accessibility_required: false },
            style: { primary: '经典均衡', secondary_interests: ['当地美食'], source: 'current' },
          },
        });
      },
      stop() {
        dispatch({ type: 'SET_STREAMING', payload: false });
        dispatch({ type: 'SET_TRIP_RUN_STATUS', payload: 'cancelled' });
        dispatch({ type: 'SET_CURRENT_TRIP_RUN', payload: { runId: 'run-generation-fixture', source: 'live', status: 'cancelled' } });
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
