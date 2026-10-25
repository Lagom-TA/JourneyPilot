// Deterministic component fixture. No model or provider requests are made.
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ThinkingChain } from '../../src/features/chat/components/ThinkingChain';
import { type ThinkingStep } from '../../src/features/chat/types/messages';
import '../../src/index.css';
const timestamp = new Date();
const base = (id: string, agentName: string, extra: Partial<ThinkingStep>): ThinkingStep => ({ id, agentName, content: '', stepName: '', timestamp, ...extra });
const steps: ThinkingStep[] = [
  base('dispatch', '任务分发', { content: '正在分派并行调研任务{"contract_version":"journeypilot.research_packet.v5"}' }),
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
  const sourceSteps = directResult ? [...steps.filter(s => s.agentName !== '住宿查询'), base('direct-stay', '住宿查询', { progressStatus: 'completed', content: '已整理 1 个住宿候选', resultPreview: [{ title: '市中心酒店（测试样例）', detail: '长春市人民大街' }] })] : steps;
  const displayed = destinationDone ? [...sourceSteps, base('destination-end', '目的地调研', { progressStatus: 'completed', endTime: new Date() })] : sourceSteps;
  return <main style={{ maxWidth: 720, margin: '32px auto', padding: '0 16px' }}>
    <p style={{ fontSize: 12 }}>交互验证样例 · 长春 4 日调研</p>
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 12 }}>
      <button onClick={() => setDirectResult(true)}>住宿直接返回</button>
      <button onClick={() => setDestinationDone(true)}>目的地完成</button>
      <button onClick={() => setMode('stopped')}>停止</button>
      <button onClick={() => setMode('done')}>全部结束</button>
    </div>
    <ThinkingChain steps={displayed} isGenerating={mode === 'live'} isSynthesizing={false} variant={mode === 'stopped' ? 'interrupted' : 'default'} regionId="research" startedAt={timestamp} />
  </main>;
}
createRoot(document.getElementById('root')!).render(<Fixture />);
