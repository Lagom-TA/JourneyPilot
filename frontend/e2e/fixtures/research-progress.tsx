// 确定性的组件 fixture，不调用模型或 provider。
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ThinkingChain } from '../../src/features/chat/components/ThinkingChain';
import { type ThinkingStep } from '../../src/features/chat/types/messages';
import '../../src/index.css';
const timestamp = new Date();
const base = (id: string, agentName: string, extra: Partial<ThinkingStep>): ThinkingStep => ({ id, agentName, content: '', stepName: '', timestamp, ...extra });
const steps: ThinkingStep[] = [
  base('dispatch', '安排查询', { content: '正在分派并行调研任务{"contract_version":"journeypilot.research_packet.v5"}' }),
  base('destination-start', '目的地调研', { progressStatus: 'running' }),
  base('transport-start', '交通查询', { progressStatus: 'running' }),
  base('stay-start', '住宿查询', { progressStatus: 'running' }),
  base('museum', '目的地调研', { isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"长春 历史博物馆"}', toolResult: '找到 1 个结果', toolStatus: 'completed', resultPreview: [{ title: '伪满皇宫博物院', detail: '长春市宽城区光复北路', url: 'https://example.org/museum' }] }),
  base('route', '交通查询', { isToolCall: true, toolName: 'global_route_search', toolArgs: '{"from_name":"长春站","to_name":"市中心"}', toolStatus: 'running' }),
  base('no-details', '住宿查询', { isToolCall: true, toolName: 'global_place_search', toolResult: '找到 1 个结果', toolStatus: 'completed' }),
  base('ref', '住宿查询', { isToolCall: true, toolName: 'hotel_search', toolResult: '仅提供住宿位置参考，尚未获取该日期价格', toolStatus: 'capability_declared' }),
];
function Fixture() {
  const [mode, setMode] = useState<'live' | 'done' | 'stopped'>('live');
  const [destinationDone, setDestinationDone] = useState(false);
  const [directResult, setDirectResult] = useState(false);
  const [extra, setExtra] = useState<ThinkingStep[]>([]);
  const [longQuery, setLongQuery] = useState(false);
  const [internalTools, setInternalTools] = useState(false);
  const longQueryStep = base('long-query', '目的地调研', { isToolCall: true, toolName: 'global_place_search', toolArgs: JSON.stringify({ query: '杭州西湖周边适合雨天慢慢散步、喝咖啡并避开人群的路线与街区，并给出上午、午后和傍晚三个时间段的具体安排' }), toolResult: '找到 1 个适合雨天散步的街区', toolStatus: 'completed', resultPreview: [{ title: '北山街雨天散步路线', detail: '沿途有树荫、咖啡馆和湖边休息点，适合放慢节奏。', url: 'https://example.org/hangzhou-rain' }] });
  const internalStep = base('internal-tools', '整理旅行需求', { isToolCall: true, toolName: 'search_tools', toolArgs: '{"query":"global_place_search 地点"}', toolResult: '已选择适合本次行程的地点与交通资料', toolStatus: 'completed' });
  const sourceSteps = [...(directResult ? [...steps.filter(s => s.agentName !== '住宿查询'), base('direct-stay', '住宿查询', { progressStatus: 'completed', content: '已整理 1 个住宿候选' })] : steps), ...(longQuery ? [longQueryStep] : []), ...(internalTools ? [internalStep] : []), ...extra];
  const displayed = destinationDone ? [...sourceSteps, base('destination-end', '目的地调研', { progressStatus: 'completed', endTime: new Date() })] : sourceSteps;
  return <main style={{ maxWidth: 1100, margin: '32px auto', padding: '0 16px' }}>
    <p style={{ fontSize: 12 }}>交互验证样例 · 长春 4 日调研</p>
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 12 }}>
      <button onClick={() => setDirectResult(true)}>住宿直接返回</button>
      <button onClick={() => setDestinationDone(true)}>目的地完成</button>
      <button onClick={() => setMode('stopped')}>停止</button>
      <button onClick={() => setMode('done')}>全部结束</button>
      <button onClick={() => setLongQuery(true)}>长查询</button>
      <button onClick={() => setInternalTools(true)}>内部工具</button>
      <button onClick={() => setExtra(previous => [...previous, base('route-stage', '行程规划', { progressStatus: 'running', content: '正在把景点和交通排进每天路线' })])}>路线阶段</button>
      <button onClick={() => setExtra(previous => [...previous, base('delivery-stage', '整理行程', { progressStatus: 'running', content: '正在整理每日行程与旅行地图' })])}>生成阶段</button>
    </div>
    <ThinkingChain steps={displayed} isGenerating={mode === 'live'} isSynthesizing={false} variant={mode === 'stopped' ? 'interrupted' : 'default'} regionId="research" startedAt={timestamp} layout="workspace" />
  </main>;
}
createRoot(document.getElementById('root')!).render(<Fixture />);
