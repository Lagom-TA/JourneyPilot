// 确定性的已交付行程组件夹具：只挂载现有 DeliveryWorkspace 与本地 Bundle，
// 不请求后端、不包含真实用户数据；地图瓦片由 Playwright 在浏览器内拦截。
import React, { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { AppProvider } from '../../src/app/state/AppProvider';
import { useApp } from '../../src/app/state/AppContext';
import { DeliveryWorkspace } from '../../src/features/travel/components/workspace/DeliveryWorkspace';
import { deliveryBundle } from './sessionData';
import '../../src/index.css';

const fixtureBundle = deliveryBundle();

function MapFixture() {
  const { state, dispatch } = useApp();
  useEffect(() => {
    dispatch({ type: 'SET_CURRENT_TRIP_RUN', payload: { runId: 'fixture-map-run', source: 'live', status: 'completed' } });
    dispatch({ type: 'CONFIRM_DELIVERY_BUNDLE', payload: fixtureBundle });
  }, [dispatch]);
  return state.deliveryBundle
    ? <DeliveryWorkspace bundle={state.deliveryBundle} />
    : <div data-testid="map-fixture-loading">正在准备离线行程…</div>;
}

createRoot(document.getElementById('root')!).render(
  <AppProvider>
    <MapFixture />
  </AppProvider>,
);
