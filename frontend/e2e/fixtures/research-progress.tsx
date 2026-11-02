// 确定性的组件 fixture，不调用模型或 provider。
// 研究按目的地 → 交通 → 住宿串行推进：后续角色只有在前序角色
// 完成后才开始留下事件，按钮按同一顺序展开各阶段。
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ThinkingChain } from '../../src/features/chat/components/ThinkingChain';
import { type ThinkingStep } from '../../src/features/chat/types/messages';
import '../../src/index.css';
const timestamp = new Date();
const base = (id: string, agentName: string, extra: Partial<ThinkingStep>): ThinkingStep => ({ id, agentName, content: '', stepName: '', timestamp, ...extra });
const destinationPhase: ThinkingStep[] = [
  base('dispatch', '安排查询', { content: '正在按顺序安排调研任务{"research_packet_id":"packet-1"}' }),
  base('destination-start', '目的地调研', { progressStatus: 'running' }),
  base('museum', '目的地调研', { isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"长春 历史博物馆"}', toolResult: '找到 1 个结果', toolStatus: 'completed', resultPreview: [{ title: '伪满皇宫博物院', detail: '长春市宽城区光复北路', url: 'https://example.org/museum' }] }),
];
const destinationEnd = () => base('destination-end', '目的地调研', { progressStatus: 'completed', endTime: new Date(), content: '已整理 4 个目的地候选' });
const transportStart = () => base('transport-start', '交通查询', { progressStatus: 'running' });
const routeStep = (done: boolean) => base('route', '交通查询', { isToolCall: true, toolName: 'global_route_search', toolArgs: '{"from_name":"长春站","to_name":"市中心"}', toolResult: done ? '找到 1 条路线' : undefined, toolStatus: done ? 'completed' : 'running' });
const stayPhase: ThinkingStep[] = [
  base('transport-end', '交通查询', { progressStatus: 'completed', endTime: new Date(), content: '已整理 3 个交通候选' }),
  base('stay-start', '住宿查询', { progressStatus: 'running' }),
  base('no-details', '住宿查询', { isToolCall: true, toolName: 'global_place_search', toolResult: '找到 1 个结果', toolStatus: 'completed' }),
  base('ref', '住宿查询', { isToolCall: true, toolName: 'hotel_search', toolResult: '仅提供住宿位置参考，尚未获取该日期价格', toolStatus: 'capability_declared' }),
];
const directStay = base('direct-stay', '住宿查询', { progressStatus: 'completed', content: '已整理 1 个住宿候选' });
const activationSteps: ThinkingStep[] = [
  base('activation-place-knowledge', '整理旅行需求', { isToolCall: true, toolName: 'search_tools', toolArgs: '{"query":"global_place_search knowledge_search 地点与资料"}', toolResult: '激活工具：global_place_search, knowledge_search', toolStatus: 'completed' }),
  base('activation-web', '整理旅行需求', { isToolCall: true, toolName: 'search_tools', toolArgs: '{"query":"brave firecrawl free_web tavily 网页"}', toolResult: '激活工具：brave_local_search, brave_web_search, firecrawl_search, free_web_search, tavily_search', toolStatus: 'completed' }),
];
const failureSteps: ThinkingStep[] = [
  base('failed-tool', '目的地调研', { isToolCall: true, toolName: 'global_place_search', toolArgs: JSON.stringify({ query: '失败调用不应展示' }), toolResult: 'HTTP 500: upstream provider failed', toolStatus: 'failed', resultPreview: [{ title: '失败预览不应展示', detail: 'secret-token', url: 'https://example.org/failed' }] }),
  base('unmatched-tool', '整理旅行需求', { isToolCall: true, toolName: 'search_tools', toolArgs: JSON.stringify({ query: 'unknown_tool' }), toolResult: '未匹配到工具', toolStatus: 'completed' }),
  base('failed-activation', '整理旅行需求', { progressStatus: 'failed', content: '工具激活失败：内部错误不应展示' }),
  base('empty-success', '目的地调研', { isToolCall: true, toolName: 'global_place_search', toolArgs: JSON.stringify({ query: '雨天空结果' }), toolResult: '没有返回结果', toolStatus: 'completed' }),
];
const failedAfterResultStep = base('destination-failed', '目的地调研', { progressStatus: 'failed', content: '阶段失败正文不应展示' });
const supplementRoundSteps: ThinkingStep[] = [
  base('destination-round-2-start', '目的地调研（第2轮补充）', { progressStatus: 'running', content: '正在补充查询雨天备选' }),
  base('destination-round-2-result', '目的地调研（第2轮补充）', { isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"长春 雨天备选"}', toolResult: '找到 2 个结果', toolStatus: 'completed', resultPreview: [{ title: '吉林省博物院', detail: '适合雨天参观', url: 'https://example.org/jilin-museum' }] }),
];
// 组合补查 → 反馈目的地返研 → 返研后继续组合的代表事件序列：
// 事件名与真实后端一致（返研轮带轮次显示名），返研结论作为组合卡片的里程碑可见。
const compositionRedoSteps: ThinkingStep[] = [
  base('composition-start', '行程规划', { progressStatus: 'running', content: '正在把景点和交通排进每天路线' }),
  base('composition-query', '行程规划', { isToolCall: true, toolName: 'global_route_search', toolArgs: '{"from_name":"伪满皇宫博物院","to_name":"当晚酒店"}', toolResult: '找到 1 条路线，门到门 25 分钟', toolStatus: 'completed' }),
  base('composition-redo', '行程规划', { progressStatus: 'completed', content: '行程安排依赖的目的地调研成果无法直接使用，已要求按反馈重做' }),
  base('destination-redo-start', '目的地调研（第2轮补充）', { progressStatus: 'running', content: '正在按组合反馈重新调查' }),
  base('destination-redo-query', '目的地调研（第2轮补充）', { isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"长春 可直接安排的真实景点"}', toolResult: '找到 2 个结果', toolStatus: 'completed', resultPreview: [{ title: '长影旧址博物馆', detail: '返研修正后的候选', url: 'https://example.org/changying' }] }),
  base('composition-continue', '行程规划', { progressStatus: 'running', content: '正在吸收返研成果继续安排每天路线' }),
];
const edgeSteps: ThinkingStep[] = [
  base('four-results', '目的地调研', { isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"深圳湾公园 周边"}', toolResult: '找到 4 个结果：深圳湾公园、红树林、人才公园、海上世界', toolStatus: 'completed', resultPreview: [
    { title: '深圳湾公园', detail: '适合傍晚看海与散步', url: 'https://example.org/shenzhen-bay' },
    { title: '红树林保护区', detail: '沿海步道与观鸟点', url: 'https://example.org/mangrove' },
  ] }),
  base('only-summary', '目的地调研', { isToolCall: true, toolName: 'knowledge_search', toolArgs: '{"query":"当地雨天备选活动"}', toolResult: '已整理 3 条适合雨天的室内活动摘要', toolStatus: 'completed' }),
  base('no-input-result', '目的地调研', { isToolCall: true, toolName: 'some_new_mcp_tool', toolStatus: 'completed' }),
  base('json-leak', '目的地调研', { isToolCall: true, toolName: 'tavily_search', toolArgs: JSON.stringify({ query: '海边天气' }), toolResult: '{"success":true,"provider":"tavily_search","result":{"secret":"内部载荷"}}', toolStatus: 'completed' }),
  base('input-json', '目的地调研', { isToolCall: true, toolName: 'global_place_search', toolArgs: JSON.stringify({ query: '{"success":true,"provider":"tavily_search","sanitized_result":{}}' }), toolResult: '机器载荷输入已过滤', toolStatus: 'completed' }),
  base('input-contract', '目的地调研', { isToolCall: true, toolName: 'global_place_search', toolArgs: JSON.stringify({ query: 'research_packet_id=packet-1 tool_call_id=call-1' }), toolResult: '合同字段输入已过滤', toolStatus: 'completed' }),
  base('input-internal', '目的地调研', { isToolCall: true, toolName: 'global_place_search', toolArgs: JSON.stringify({ query: 'global_place_search brave_web_search 附近景点' }), toolResult: '内部标识输入已转换', toolStatus: 'completed' }),
  base('input-error', '目的地调研', { isToolCall: true, toolName: 'global_place_search', toolArgs: JSON.stringify({ query: 'Traceback (most recent call last): File "agent.py", line 42, in run' }), toolResult: '异常文本输入已过滤', toolStatus: 'completed' }),
];
function Fixture() {
  const [mode, setMode] = useState<'live' | 'done' | 'stopped'>('live');
  const [destinationDone, setDestinationDone] = useState(false);
  const [transportDone, setTransportDone] = useState(false);
  const [directResult, setDirectResult] = useState(false);
  const [extra, setExtra] = useState<ThinkingStep[]>([]);
  const [longQuery, setLongQuery] = useState(false);
  const [internalTools, setInternalTools] = useState(false);
  const [activation, setActivation] = useState(false);
  const [edgeCases, setEdgeCases] = useState(false);
  const [failures, setFailures] = useState(false);
  const [failedAfterResult, setFailedAfterResult] = useState(false);
  const [supplementRound, setSupplementRound] = useState(false);
  const [compositionRedo, setCompositionRedo] = useState(false);
  const [runKey, setRunKey] = useState('run-a');
  const longQueryStep = base('long-query', '目的地调研', { isToolCall: true, toolName: 'global_place_search', toolArgs: JSON.stringify({ query: '杭州西湖周边适合雨天慢慢散步、喝咖啡并避开人群的路线与街区，并给出上午、午后和傍晚三个时间段的具体安排' }), toolResult: '找到 1 个适合雨天散步的街区', toolStatus: 'completed', resultPreview: [{ title: '北山街雨天散步路线', detail: '沿途有树荫、咖啡馆和湖边休息点，适合放慢节奏。', url: 'https://example.org/hangzhou-rain' }] });
  const internalStep = base('internal-tools', '整理旅行需求', { isToolCall: true, toolName: 'search_tools', toolArgs: '{"query":"global_place_search 地点"}', toolResult: '已选择适合本次行程的地点与交通资料', toolStatus: 'completed' });
  const serialSteps = [
    ...destinationPhase,
    ...(destinationDone ? [destinationEnd(), transportStart(), routeStep(transportDone)] : []),
    ...(transportDone ? stayPhase : []),
  ];
  const sourceSteps = [
    ...(directResult ? [...serialSteps.filter(s => s.agentName !== '住宿查询'), directStay] : serialSteps),
    ...(longQuery ? [longQueryStep] : []),
    ...(internalTools ? [internalStep] : []),
    ...(activation ? activationSteps : []),
    ...(edgeCases ? edgeSteps : []),
    ...(failures ? failureSteps : []),
    ...(failedAfterResult ? [failedAfterResultStep] : []),
    ...extra,
  ];
  const displayed = [
    ...(compositionRedo ? compositionRedoSteps : []),
    ...(supplementRound ? [...sourceSteps, ...supplementRoundSteps] : sourceSteps),
  ];
  return <main style={{ maxWidth: 1100, margin: '32px auto', padding: '0 16px' }}>
    <p style={{ fontSize: 12 }}>交互验证样例 · 长春 4 日调研</p>
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 12 }}>
      <button onClick={() => setDestinationDone(true)}>目的地完成</button>
      <button onClick={() => setTransportDone(true)}>交通完成</button>
      <button onClick={() => setDirectResult(true)}>住宿直接返回</button>
      <button onClick={() => setMode('stopped')}>停止</button>
      <button onClick={() => setMode('done')}>全部结束</button>
      <button onClick={() => setLongQuery(true)}>长查询</button>
      <button onClick={() => setInternalTools(true)}>内部工具</button>
      <button onClick={() => setActivation(true)}>激活摘要</button>
      <button onClick={() => setEdgeCases(true)}>边界详情</button>
      <button onClick={() => setFailures(true)}>内部失败</button>
      <button onClick={() => setFailedAfterResult(true)}>结果后失败</button>
      <button onClick={() => setSupplementRound(true)}>补充轮次</button>
      <button onClick={() => setCompositionRedo(true)}>组合返研</button>
      <button onClick={() => setRunKey('run-b')}>新 Run</button>
      <button onClick={() => setExtra(previous => [...previous, base('unrelated-transport', '交通查询', { progressStatus: 'completed', content: '补充了一条无关的交通状态' })])}>无关事件</button>
      <button onClick={() => setExtra(previous => [...previous, base('route-stage', '行程规划', { progressStatus: 'running', content: '正在把景点和交通排进每天路线' })])}>路线阶段</button>
      <button onClick={() => setExtra(previous => [...previous, base('delivery-stage', '整理行程', { progressStatus: 'running', content: '正在整理每日行程与旅行地图' })])}>生成阶段</button>
    </div>
    <ThinkingChain steps={displayed} isGenerating={mode === 'live'} isSynthesizing={false} variant={mode === 'stopped' ? 'interrupted' : 'default'} regionId="research" runKey={runKey} startedAt={timestamp} layout="workspace" runStatus={mode === 'done' ? 'completed' : undefined} />
  </main>;
}
createRoot(document.getElementById('root')!).render(<Fixture />);
