import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ThinkingChain } from '../../src/features/chat/components/ThinkingChain';
import { type ThinkingStep } from '../../src/features/chat/types/messages';
import '../../src/index.css';

const timestamp = new Date('2026-01-15T08:00:00.000Z');
const base = (id: string, agentName: string, extra: Partial<ThinkingStep>): ThinkingStep => ({
  id, agentName, content: '', stepName: '', timestamp, ...extra,
});
const note = base('destination-note', '目的地调研', {
  kind: 'work_explanation',
  content: '先核对目的地资料与开放信息，再比较适合家庭慢游的场馆和街区，优先筛选交通方便、介绍清楚且适合四日行程的备选地点。',
});
const destinationSteps: ThinkingStep[] = [
  base('dispatch', '安排查询', { progressStatus: 'completed', endTime: timestamp }),
  base('destination-done', '目的地调研', {
    progressStatus: 'completed', endTime: timestamp,
    content: '已筛选长春城区内适合慢游、便于串联安排的目的地候选。',
  }),
  note,
  base('destination-museum', '目的地调研', {
    isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"长春 历史博物馆"}',
    toolResult: '找到 1 个结果：伪满皇宫博物院', toolStatus: 'completed',
    resultPreview: [{ title: '伪满皇宫博物院', detail: '长春市宽城区光复北路，建议预留半天参观。', url: 'https://example.org/museum' }],
  }),
  base('destination-park', '目的地调研', {
    isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"长春 公园与城市步道"}',
    toolResult: '找到 1 个结果：南湖公园', toolStatus: 'completed',
    resultPreview: [{ title: '南湖公园', detail: '湖区步道平缓，适合安排轻松的户外散步。', url: 'https://example.org/park' }],
  }),
];
const transportSummary = '正在逐项比较长春站至主要游览区域的公共交通与步行接驳，优先核实路线是否直达、换乘次数、预计耗时以及带同行人出行时是否方便。';
const staySummary = '正在检查市中心与景点周边的住宿区域，综合考虑前往车站的便利程度、每日游览动线、周边餐饮选择和适合四日停留的安静程度。';

const longAgents = [
  { id: 'destination', name: '目的地调研' },
  { id: 'transport', name: '交通查询' },
  { id: 'stay', name: '住宿查询' },
];
const longSteps = longAgents.flatMap(({ id, name }) => [
  base(`long-${id}-intro`, name, { kind: 'work_explanation', content: '接着查看每条独立记录。' }),
  ...Array.from({ length: 14 }, (_, index) => {
    const number = String(index + 1).padStart(2, '0');
    const isPlace = index % 2 === 0;
    return base(`long-${id}-${number}`, name, {
      isToolCall: true,
      toolName: isPlace ? 'global_place_search' : 'maps_weather',
      toolArgs: JSON.stringify(isPlace ? { query: `长春第${number}处地点` } : { city: `长春第${number}区` }),
      toolStatus: 'completed',
      toolResult: index === 6
        ? `${'长记录包含适合家庭步行的交通接驳、开放时段和景点之间的距离。'.repeat(6)}长记录完整结束标记`
        : `第${number}条资料已核实`,
    });
  }),
]);

const repeatedPlace = {
  isToolCall: true,
  toolName: 'global_place_search',
  toolArgs: '{"query":"长春 长影旧址"}',
  toolResult: '找到长影旧址',
  toolStatus: 'completed' as const,
  resultPreview: [{ title: '长影旧址', detail: '保留这次查询的来源详情。', url: 'https://example.org/studio' }],
};
const aggregateSteps: ThinkingStep[] = [
  base('aggregate-intro', '目的地调研', {
    kind: 'work_explanation', stepName: '工作说明', content: '接下来分别核对两组目的地资料。',
  }),
  base('aggregate-01', '目的地调研', repeatedPlace),
  base('aggregate-02', '目的地调研', {
    isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"长春 雕塑公园"}',
    toolStatus: 'completed', toolResult: '找到雕塑公园',
    resultPreview: [{ title: '雕塑公园', detail: '保留另一条查询的来源详情。', url: 'https://example.org/sculpture' }],
  }),
  base('aggregate-03', '目的地调研', {
    isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"长春 文化广场"}', toolStatus: 'running',
  }),
  base('aggregate-separator', '目的地调研', {
    kind: 'work_explanation', stepName: '工作说明', content: '两组查询之间先比较资料，然后再继续确认相邻地点。',
  }),
  base('aggregate-04', '目的地调研', repeatedPlace),
  base('aggregate-05', '目的地调研', {
    isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"长春 动植物公园"}',
    toolStatus: 'completed', toolResult: '找到动植物公园',
    resultPreview: [{ title: '动植物公园', detail: '适合安排户外活动。', url: 'https://example.org/zoo' }],
  }),
  base('aggregate-06', '目的地调研', {
    isToolCall: true, toolName: 'global_place_search', toolArgs: '{"query":"长春 世界雕塑园"}',
    toolStatus: 'completed', toolResult: '找到世界雕塑园',
    resultPreview: [{ title: '世界雕塑园', detail: '保留第三条查询的来源详情。', url: 'https://example.org/world-sculpture' }],
  }),
];

function Fixture() {
  const [otherTasksDone, setOtherTasksDone] = useState(false);
  const [extraSummary, setExtraSummary] = useState(false);
  const [showLongSteps, setShowLongSteps] = useState(false);
  const [showAggregateSteps, setShowAggregateSteps] = useState(false);
  const [liveCount, setLiveCount] = useState(0);
  const [shortNotes, setShortNotes] = useState(0);
  const [pairCount, setPairCount] = useState(0);
  const suffix = extraSummary ? ' 同时整理备选方案与需要进一步确认的细节，方便后续按出行偏好调整。' : '';
  const dynamicSteps: ThinkingStep[] = [
    ...destinationSteps,
    ...(showLongSteps ? longSteps : []),
    ...(showAggregateSteps ? aggregateSteps : []),
    ...Array.from({ length: shortNotes }, (_, index) => base(`short-note-${index + 1}`, '行程规划', {
      kind: 'work_explanation', content: `简短说明第 ${index + 1} 条。`,
    })),
    ...(shortNotes ? [base('short-note-progress', '行程规划', { progressStatus: 'running', content: '正在整理每天的路线。' })] : []),
    ...(pairCount > 0 ? [
      base('pair-intro', '交通查询', { kind: 'work_explanation', content: '接下来核对交通路线。' }),
      ...Array.from({ length: pairCount }, (_, index) => base(`pair-${index + 1}`, '交通查询', {
        isToolCall: true, toolName: 'global_route_search', toolStatus: 'completed',
        toolArgs: JSON.stringify({ from_name: '长春站', to_name: `路线候选${index + 1}` }),
        toolResult: `路线候选${index + 1}已核对`,
      })),
      base('pair-end', '交通查询', { kind: 'work_explanation', content: '随后确认其他接驳方式。' }),
    ] : []),
    ...Array.from({ length: liveCount }, (_, index) => base(`live-${index + 1}`, '目的地调研', {
      kind: 'work_explanation', content: `实时新增记录 ${index + 1}。`,
    })),
    base('transport-tool', '交通查询', {
      isToolCall: true, toolName: 'global_route_search',
      toolArgs: '{"from_name":"长春站","to_name":"市中心"}',
      ...(otherTasksDone
        ? { toolStatus: 'completed' as const, toolResult: '路线资料已整理，建议按出发时段复核。' }
        : { toolStatus: 'running' as const }),
    }),
    base('transport-progress', '交通查询', {
      progressStatus: otherTasksDone ? 'completed' : 'running',
      ...(otherTasksDone ? { endTime: timestamp } : {}),
      content: `${transportSummary}${suffix}`,
    }),
    base('stay-tool', '住宿查询', {
      isToolCall: true, toolName: 'hotel_search',
      toolArgs: '{"location":"长春市中心","nights":3}',
      ...(otherTasksDone
        ? { toolStatus: 'completed' as const, toolResult: '住宿区域参考资料已整理。' }
        : { toolStatus: 'running' as const }),
    }),
    base('stay-progress', '住宿查询', {
      progressStatus: otherTasksDone ? 'completed' : 'running',
      ...(otherTasksDone ? { endTime: timestamp } : {}),
      content: `${staySummary}${suffix}`,
    }),
  ];

  return <main style={{ containerType: 'inline-size', width: '100%', maxWidth: 1600, margin: '0 auto', padding: '20px 16px' }}>
    <h1 style={{ margin: '0 0 12px', fontSize: 18 }}>长春旅行调研进度</h1>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 20 }}>
      <button type="button" aria-label="切换交通和住宿任务状态" onClick={() => setOtherTasksDone(value => !value)}>
        切换交通住宿状态
      </button>
      <button type="button" aria-label="追加交通和住宿长摘要" onClick={() => setExtraSummary(value => !value)}>
        追加长摘要
      </button>
      <button type="button" onClick={() => setShowLongSteps(true)}>注入各类长列表</button>
      <button type="button" onClick={() => setShowAggregateSteps(true)}>注入工具聚合</button>
      <button type="button" onClick={() => setLiveCount(value => value + 1)}>追加实时记录</button>
      <button type="button" onClick={() => setShortNotes(6)}>注入六条简短说明</button>
      <button type="button" onClick={() => setShortNotes(7)}>追加第七条说明</button>
      <button type="button" onClick={() => setPairCount(2)}>注入两条路线</button>
      <button type="button" onClick={() => setPairCount(3)}>追加第三条路线</button>
    </div>
    <ThinkingChain
      steps={dynamicSteps}
      isGenerating
      isSynthesizing={false}
      regionId="research-progress-layout"
      layout="workspace"
      runKey="research-progress-layout-fixed"
      serverTotalMs={0}
    />
  </main>;
}

createRoot(document.getElementById('root')!).render(<Fixture />);
