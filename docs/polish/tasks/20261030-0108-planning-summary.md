# 规划侧栏按站序排城市，删除重复旅行信息

- 编号：20261030-0108-planning-summary
- 状态：待真人验收
- 创建：2026-10-30 01:08
- 执行前先读：[工作目录 README](../README.md)、AGENTS.md、docs/invariants.md、frontend/README.md、frontend/e2e/README.md、[本轮所有权/dirty隔离](../references/20261030-0108-feedback-workflow.md)

## 1 用户反馈

> 截图2规划中左侧城市标题排得清楚，不用“北京市＋上海市＋长春市”撑乱多行；左侧删除与标题/日期重复的“目的地”“行程”信息行，保留必要出发地、同行与偏好。

截图：`output/polish/20261030-0108-feedback-workflow/feedback/feedback-2.png`；指挥已 read。右侧同名运行项/行距问题归 `20261030-0108-process-disclosure`，实际需求与计划归 `20261030-0108-requirement-research-plan`，不在本项顺带修改。

## 2 现象与发生条件

正式 Run 准备/运行中，左侧旅行卡：北京、上海、长春完整城市名带加号，在固定窄侧栏自然断成两行；天数另占一行，下方再重复目的地列表、“11天·深圳市出发”，同行与偏好混在重复信息后。需同时覆盖 pending gate、取消/失败、历史只读及手机阅读顺序；摘要是真实受控身份的呈现，不是可编辑旅行事实。

## 3 根因

- `frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx:119–137` 用同一个 h1 内的多个 span 拼接完整地名及“＋”，没有给站序/多城独立布局；`frontend/src/index.css:4016–4044` 只让每个 segment 不换行，整体仍在 h1 里流式断行。加号可能落在下一行开头，并非数据错误。
- `GenerationJourneyPanel.tsx:146–150` 在已显示标题/天数、出发地与日期后，dl 再列“目的地”和“行程”，属于两个信息结构重复输出，不能只缩小字号掩盖。
- 当前该文件 dirty 增量是 **followup composer/只读说明**，不是本次标题根因。基线来自 `20261029-2325-workspace-followup-composer`，完整保留；标题/摘要原有长名来自已提交实现。旧 `20261029-1252-generation-layout` 的工作台尺寸/扫光要求继续有效。

## 4 方案

目标状态：多城按真实顺序形成清楚的标题/路线层级，完整站点可读，天数与日期易扫读；侧栏只保留一次出发地/日期、必要同行/偏好与真实状态操作。

必须做：

- 多目的地有清楚站序，1/3/5站、长城市/区域名都不会靠任意加号折行撑乱标题；无需固定显示完整行政后缀，但任何简写必须是安全展示且完整名称可读/可访问，不能改 PlaceIdentity 或只显示第一站/城市数来隐藏其余站点。
- 删除重复“目的地”“行程”dl行；出发地、日期范围、天数、同行人数/儿童/长辈/无障碍信息和偏好各在合理位置保留必要一次。出发地可留在副标题，不必为了“保留”再建一行。
- 不以扩大左栏或压缩右栏来挽救标题；工作台侧栏与审批原位结构保持稳定。停止/继续/只读/状态提示与焦点交接、手机可滚动阅读、reduced-motion不回归。
- 数据依旧来自当前 controlledTripIdentity，站序与首页排序/提交/恢复一致，不写本地猜测、缓存另一个标题事实源。

执行者自己决定：城市逐行/紧凑站序或其它清楚布局、字号字重和间距、是否抽一个纯展示小组件。优先修改当前摘要区域与选择器，不改全局 h1 或其他行程标题。

不许碰：后端、API/SSE、受控身份/日期规则、Run真值、审批/澄清流程、右侧过程模型、正式Bundle/地图/报告、恢复浮框/续聊及其既有脏改动。本项由唯一 frontend 写入者在需求任务前端和首页后顺序实施，只拥有 GenerationJourneyPanel 左摘要块、对应 CSS 和离线摘要测试增量；共享文件不可并行。只改本文状态与第7节，不自行提交/推送。`GenerationJourneyPanel.tsx` 和 `index.css` 均混有旧工作，禁止整文件 add。

## 5 停下来报告的情况

- 需要改变服务端地名/身份或持久化字段才能排版，先报告，不用字符串替换修改真实地点。
- 实际缺失站点不是渲染问题而是状态/归属错误，提供输入/输出和 Run 身份证据后停止。
- 若独立提交树因该文件旧 followupComposer import 而缺依赖，报告提交受阻；不自动暂存未跟踪 followupComposer 文件或整段 composer。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 深圳出发、北京→上海→长春、11天示例清楚显示真实站序，标题不再出现任意“＋长春市”断行；1/5站及长名称不溢出/裁切。
2. 不再有重复目的地/行程信息行；出发地/日期/天数、特殊同行与偏好均保留且不重复堆叠。
3. pending gate/运行/失败/取消/只读下侧栏稳定，原停止/继续生成与焦点可用；手机可读无横溢，右侧阅读宽度和底部旧composer不受影响。
4. 当前Run身份与站序未被改写；baseline旧改动不被删除或计为本轮提交内容。

### 6.2 必须运行的检查

只用本地 Vite 和浏览器内拦截（复用8088前核对；没有时 `npm run dev -- --host 127.0.0.1 --port 8088 --strictPort`）。在 frontend：

```bash
npm run type-check
JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --grep '生成工作区|2000px|390px|1440px' --workers=1 --output=../output/polish/20261030-0108-planning-summary/playwright-component
JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep 'gate|审批|特殊同行|special|history|read-only|generation|research' --workers=1 --output=../output/polish/20261030-0108-planning-summary/playwright-session
```

在既有生成工作区真实组件夹具添加截图同款三站、五站/长名与特殊同行，断言顺序/无重复/边界几何；保持既有单站、审批侧栏、只读、停止/恢复操作。若调整夹具名称，确保上述命令实际包含新增用例，在第7节记实际匹配数与命令。API/地图/外网未匹配即失败，不运行live/write套件。

### 6.3 实屏证据（执行者提供）

保存至 `output/polish/20261030-0108-planning-summary/`：2000×880、1440×900 三城与五站长名侧栏，390×844 三站和特殊同行；至少一张 pending gate/一张运行状态以证明侧栏一致。含完整工作区以确认不靠扩宽侧栏挤右栏。指挥必须 read 查看；附站序文本及无横溢测量。

### 6.4 真人验收（用户操作）

1. 从深圳选北京、上海、长春后开始规划 → 左侧城市排布清楚，顺序正确，天数/日期易读。
2. 看摘要下方 → 无重复“目的地”“行程”行，出发地、同行、偏好仍在。
3. 缩窄窗口并切待确认/运行/停止状态 → 不横溢，标题不挤停止按钮，工作台结构不跳变。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-30 02:10 · frontend

- 改动摘要：左侧标题改为按真实站序逐行展示，每站带序号，完整地名保留；天数仍作为独立标题信息。删除与标题/日期重复的“目的地”“行程”两个事实行，只保留同行和偏好标签；出发地、日期、天数仍在副标题/标题中保留一次。标题块采用纵向站点列表，不再把全角加号混在同一个流式 h1 里。
- 改动文件：`frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx`、`frontend/src/index.css`、`frontend/e2e/fixtures/generation-progress.tsx`、`frontend/e2e/research-progress.spec.ts`、`frontend/e2e/session-state.spec.ts`、本任务第 7 节。
- 实际运行的检查与结果：
  - `npm run type-check` → 通过；完整前端单测 `npm run test` → 107 passed。
  - `JP_COMPONENT_E2E=1 ... npx playwright test e2e/research-progress.spec.ts --grep '生成工作区|2000px|390px|1440px' --workers=1` → 11 passed。
  - `JP_SESSION_STATE_E2E=1 ... npx playwright test e2e/session-state.spec.ts --grep 'gate|审批|特殊同行|special|history|read-only|generation|research' --workers=1` → 10 passed；完整离线 session-state 套件 40 passed。
  - 新增夹具覆盖深圳出发、北京→上海→长春 11 天、五站长名和儿童/长辈/无障碍同行；断言站序、无重复目的地/行程行、无横向溢出。
- 实屏证据：`output/polish/20261030-0108-planning-summary/` 下 `generation-2000-three-cities.png`、`generation-2000-special-party.png`、`generation-390-special-party.png`、`generation-2000-five-long-cities.png`；`generation-2000-pending-gate.png` 复用同轮离线审批页；`sidebar-geometry.json` 记录站序、摘要文本与溢出。
- 未运行/已知风险：未连接真实 Run 或真实地名数据；截至本轮只有离线组件/会话夹具的 pending gate 与运行态证据，不含真实后端规划结果。超长行政区名会在站点行内自然换行，仍保留完整名称。
- 后端整合结论：未改后端、受控身份、日期规则、Run 真值或审批；数据仍来自 `controlledTripIdentity`。

### 第 2 轮 · 2026-10-30 02:35 · 返工（frontend）

- 改动摘要：城市行不再继承 `nowrap`，地点名允许在自身列内换行；标题字号微调为 26px、站序与天数间距收紧，使常规五站长名在桌面仍保持单行，同时让合法超长城市名在手机侧栏换行而不是覆盖天数。站序、天数、出发地、同行与偏好结构未变。
- 改动文件：`frontend/src/index.css`、`frontend/e2e/fixtures/generation-progress.tsx`、`frontend/e2e/research-progress.spec.ts`、本任务第 7 节。
- 偏离方案及理由：无。通过可读字号与真实换行规则修复，没有扩宽左栏、压缩右栏或改写地名。
- 实际运行的检查与结果：
  - `npm run type-check` → 通过；`npm run test` → 107 passed。
  - `JP_COMPONENT_E2E=1 ... npx playwright test e2e/research-progress.spec.ts --workers=1` → 21 passed；原“2000px 五站长名单行、标题不压停止按钮”断言继续通过，新增 390px“克孜勒苏柯尔克孜自治州”换行、右边界不越过天数、无横向溢出断言。
  - `JP_SESSION_STATE_E2E=1 ... npx playwright test e2e/session-state.spec.ts --workers=1` → 40 passed。
- 实屏证据：`output/polish/20261030-0108-planning-summary/long-name-390.png`、`long-name-390.json`；同一修复的复核截图 `output/polish/20261030-0108-feedback-workflow/review/long-name-390-fixed.png`。离线组件夹具，390×844。
- 遗留问题或需要指挥决定的事：无。

## 8 指挥验收（指挥填写）

### 本轮独立复核 · 2026-10-30

- 结论：本项代码验收通过，待真人验收；不表示整批需求计划任务已通过或已提交。
- 本轮抽查：核对 Generation 左摘要仍由当前受控身份按站序输出，删除重复目的地/行程事实行，完整地名可换行且不扩宽侧栏；read 查看原反馈与 `output/polish/20261030-0108-feedback-workflow/final-review/summary-1440-five-long.png`，五站长名与天数不重叠。baseline→当前差异未改旧 followup composer/只读块。
- 检查范围：沿用需求计划任务第8节“第4轮后独立复验”已运行的前端34项单测/type-check、过程21项、首页5项、intake7项、session19项及关键实屏结论；本轮纯后端排除修复未触碰前端，不重复运行，也不冒称本轮新跑。此次后端相关组合重新运行289 passed、定向Ruff及diff检查通过，但发现需求计划任务有非研究住宿展示要求重新启用被排除研究的P2，已另记返工，不属于本项视觉/交互缺陷。
- 边界：baseline存档16个哈希一致，无关恢复浮框、InputArea、followupComposer与旧任务原样保留，索引为空；本次不改产品代码、不暂存或提交。隔离dirty后的候选提交树留下一阶段独立验证，未计为通过；无真人结果，未标“已验收”。

### 第 6 轮后复核补记 · 2026-10-30

- 结论：本项仍为代码验收通过、待真人验收；需求计划任务上一轮的非研究住宿要求覆盖研究排除P2现已修复，整批未发现新的阻断项。未将任何任务标为“已验收”。
- 本轮重新运行后端相关组合293 passed、排除语义定向9 passed、Ruff及diff检查通过；两个原审查探针均通过，真实补充/批准/分派链路无住宿工具执行意图。详见需求计划任务第8节“第6轮后独立复验”。
- 本轮抽查四项任务覆盖、相关组件/断言与既有实屏；没有重跑前端单测/type-check或浏览器，先前结果仍为历史记录。baseline存档16个哈希及无关既有改动保留情况已核对；产品代码只读、index为空，未暂存/提交/推送。候选提交树交下一阶段独立验证，真实Provider端到端及真人验收未运行。

## 9 真人验收（指挥代录）
