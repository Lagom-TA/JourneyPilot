// 经过真实 SSE 呈现链的确定性生成工作区夹具，不调用模型或后端。
import React, { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { AppProvider } from '../../src/app/state/AppProvider';
import { useApp } from '../../src/app/state/AppContext';
import { useSendMessage } from '../../src/app/session/useSendMessage';
import { GenerationJourneyPanel } from '../../src/features/travel/components/workspace/GenerationJourneyPanel';
import '../../src/index.css';

const place = (name: string) => ({
  place_id: `osm:relation:${name}`,
  provider: 'osm' as const,
  kind: 'city' as const,
  name,
  display_name: `${name}，中国`,
  country_code: 'CN',
  latitude: phaseCoordinate(name).latitude,
  longitude: phaseCoordinate(name).longitude,
  admin_path: ['中国', name],
});

function phaseCoordinate(name: string) {
  return name === '青岛' ? { latitude: 36.07, longitude: 120.38 } : { latitude: 31.2, longitude: 121.4 };
}

const routeDecision = {
  route: 'trip_planning' as const,
  confidence: 1,
  alternatives: [],
  signals: ['explicit_ui_action'],
  requires_trip_draft: true,
  requires_confirmation: false,
};

const identity = {
  origin: place('上海'),
  destinations: [place('青岛')],
  start_date: '2026-11-05',
  end_date: '2026-11-08',
  party: { adults: 1, children: 0, elderly_companions: false, accessibility_required: false },
  style: { primary: '经典均衡', secondary_interests: ['当地美食'], source: 'current' as const },
};

type HarnessWindow = Window & {
  __generationSse?: {
    start: () => void;
  };
};

function Fixture() {
  const { state } = useApp();
  const { sendMessage } = useSendMessage();

  useEffect(() => {
    (window as HarnessWindow).__generationSse = {
      start() {
        void sendMessage('离线验证真实 thinking 事件形状', {
          assistantPendingLabel: '正在规划你的旅行',
          routeDecision,
          controlledTripIdentity: identity,
        });
      },
    };
  }, [sendMessage]);

  return (
    <main style={{ height: '100dvh', minHeight: 0 }}>
      <div className="generation-workspace" style={{ height: '100%' }}>
        {state.currentTripRunId ? <GenerationJourneyPanel /> : <p style={{ padding: 24 }}>等待离线 SSE 事件</p>}
      </div>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<AppProvider><Fixture /></AppProvider>);
