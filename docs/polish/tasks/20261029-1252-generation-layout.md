# 规划页摘要卡与过程区去重，终态只显示准确的一条进度说明

- 编号：20261029-1252-generation-layout
- 状态：待真人验收
- 创建：2026-10-29 12:52
- 执行前先读：[工作目录 README](../README.md)、frontend/README.md、frontend/e2e/README.md、docs/invariants.md

## 1 用户反馈

第二张截图标注：左上旅行摘要“应该做成一张卡片”；“规划进度”与“正在整理这趟旅行的基本信息。”两处“删掉这两个重复的”；右侧“规划过程 / 每一步安排，都有据可查 / 查看不同阶段的思考摘要、查询内容和已找到的旅行资料。”标注“全部删除”；当前阶段“针对正在进行的任务要加入扫光特效”。绿色框圈出右侧应使用的过程展示区域。

截图：output/polish/20261029-1252-generation-layout/feedback-1.png，2000×880。

本轮反馈：

> 我们又出现了这种信息冗余的情况

截图：`output/polish/20261029-1252-generation-layout/feedback-2.png`，2000×880。绿色框圈出“理解偏好，准备相关查询”，下方又显示“旅行需求已整理，正在准备相关查询”。本轮以第 2–6 节修订方案为准，之前已通过的摘要卡、宽度与扫光效果作为回归边界。

## 2 现象与发生条件

正式规划工作区，仅“整理旅行需求”阶段有过程记录，随后 Run 失败。右侧显示“调研已停止”，阶段标题为“整理旅行需求 ✓ 已结束”，同时展示固定说明和动态摘要两行近义文案；动态摘要还继续声称“正在准备相关查询”。本轮只负责前端内容层次与终态文案，实际规划失败另立后端任务。

## 3 根因

- `frontend/src/features/chat/model/researchProgress.ts:33–35` 为 planning 组写入固定说明“理解偏好，准备相关查询”。
- `frontend/src/features/chat/components/ThinkingChain.tsx:75–79` 为已结束且无工具结果的 planning 组硬编码“旅行需求已整理，正在准备相关查询”；`:87–93` 无条件并列标题、状态、固定说明、动态摘要。这是渲染职责重叠，单改其中一句仍会重复。
- 该完成态摘要没有考虑 Run 已停止的上下文。阶段确实完成可以保留“已结束”，但不能因此继续承诺后续工作正在运行。`:80–82` 的 milestones 只过滤相同字符串和少量固定句，不能证明展开后有额外有效信息。

## 4 方案

目标状态：阶段卡保留名称和真实状态，下面最多一条有信息增量的进度或结果说明；停止/失败后不继续显示“正在准备”之类运行中承诺。保留已有旅行摘要卡、过程区利用宽高与真实 active 阶段扫光。

必须做：

- 在过程卡公共渲染责任方消除固定职责说明与动态状态摘要的重叠。已有有效动态信息时，不再额外展示近义固定说明；没有新信息时允许仅保留名称与状态。不能只按截图字符串打补丁。
- 同时核对 planning、目的地、交通、住宿和行程组：查询数、需留意项、来源与结果等不同信息保留；不为删重隐藏可用错误、恢复入口或真实查询详情。
- 基于现有阶段与 Run 展示上下文生成准确文案。失败/停止/取消后不说仍在准备下一步，已完成阶段仍可显示真实完成状态，不能把全部阶段强制改成失败。
- 无工具结果的准备阶段不生成虚构成果或无增量详情。折叠展开仍保留实际里程碑、查询和来源，避免同一进度在卡头与正文重复呈现。
- 不回归已有摘要卡、长目的地标题与天数整体、过程区伸展、手机阅读顺序，以及仅实际 active 时扫光和 reduced-motion 关闭。

执行者自己决定：删除固定 description 展示还是按信息层次选择摘要、终态的一句产品文案、如何在现有组件边界传递展示上下文。优先删去多余信息，不引入近义句比较器。

不许碰：后端/API/SSE、Run 或阶段真值推导、计划门批准规则、实际规划失败根因、付费工具、真实数据和交付内容。不提交不推送。

## 5 停下来报告的情况

若证据显示阶段或 Run 的真值本身错误，而非文案/渲染重复，单独报告责任链，不在本任务顺手改状态协议。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 截图对应的“已完成需求整理 + Run 失败”场景不再同时展示两条近义说明，也不声称仍在准备查询；真实阶段完成与 Run 失败可以同时准确表达。
2. 正常运行、阶段完成、取消、失败各状态只展示有增量的信息；其他研究组保留可用查询、结果、来源与异常提示。
3. 无工具准备阶段的折叠内容没有重复占位；原有卡片、长标题、宽高、扫光和 reduced-motion 行为不回归。

### 6.2 必须运行的检查

在 `frontend/` 下运行：

- `npm run type-check`
- `JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1`

补充离线夹具的“完成需求整理后失败”、运行中无工具、正常研究、取消状态，断言文案无重复且符合终态；复用真实 ThinkingChain/GenerationJourneyPanel 组件，保留查询展开、来源、防 JSON 泄露与现有几何/motion 覆盖。若修改 `researchProgress` 展示投影，再定向运行 `npm run test -- src/features/chat/model/researchProgress.test.ts`。不请求模型或写真实会话；端口以实际 Vite 服务为准。

### 6.3 实屏证据（执行者提供）

2000×880：仅需求整理完成随后 Run 失败、正常并行研究；390×844：同类失败卡片。需能看清卡片名称、状态及唯一说明，展开后能核对增量详情。存本任务 output 目录，文件名区分本轮。

### 6.4 真人验收（用户操作）

1. 查看规划过程卡 → 名称、状态下面没有两行近义说明。
2. 查看已停止/失败的规划 → 不再显示仍在准备后续查询；展开已有研究记录 → 查询与来源仍可查看。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-29 13:25 · pi 编码代理

- 改动摘要：旅行摘要改为独立卡片；删除左侧“规划进度”眉题与重复状态句，删除右侧“规划过程 / 每一步安排，都有据可查 / 查看不同阶段…”整块宣传标题，保留失败、取消、中断、完成等必要状态。右侧真实过程卡片取消 860px 最大宽，随正文区域伸展，空态与内容态都使用可用宽度。当前 active 阶段加 4.6 秒低对比扫光，只在真实运行中生效，停止/完成/取消/失败与 reduced-motion 关闭。
- 改动文件：`frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx`、`frontend/src/index.css`、`frontend/e2e/research-progress.spec.ts`、`frontend/e2e/session-state.spec.ts`、`frontend/e2e/fixtures/generation-progress.tsx`（新增夹具）、`frontend/e2e/fixtures/generation-progress.html`（新增夹具）。
- 偏离方案及理由：扫光只作用于当前 `li.is-active`，并由 `generation-progress[data-active='true']` 绑定真实 `isStreaming` 与 Run 状态；没有为动画伪造步骤。新增确定性组件夹具验证宽屏几何与 motion，不调用模型或后端。
- 实际运行的检查与结果：`npm run type-check` 通过；`JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1` 通过（6 项，含 2000px 过程区占满、卡片样式、扫光 4.6s、停止与 reduced-motion 关闭、390px 无横向溢出）；`JP_SESSION_STATE_E2E=1 ... e2e/session-state.spec.ts` 17 项通过，已替换对删除标题的旧断言。
- 实屏证据：`output/polish/20261029-1252-generation-layout/generation-2000-waiting.png`、`generation-2000-research.png`、`generation-1440-active.png`、`generation-390-phone.png`；测试实测 2000px 下 `research/activity > 0.88` 且过程区宽度 >1200px，扫光 `animationName=generation-stage-sweep`、`animationDuration=4.6s`，停止后 `data-active=false` 且伪元素 `animationName=none`。
- 遗留问题或需要指挥决定的事：无。


### 第 2 轮 · 2026-10-29 14:05 · pi 编码代理

- 改动摘要：R1 把标题拆成每个目的地一个不换行片段和独立的“天数 + 日”整体；长目的地只在目的地之间换行，天数始终与“日”同排。宽屏侧栏从 300–360px 调整为 360–400px，给短标题和长标题留足空间，停止按钮仍固定在右上且不挤压。夹具新增五站长名称状态和定向断言。
- 改动文件：`frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx`、`frontend/src/index.css`、`frontend/e2e/research-progress.spec.ts`、`frontend/e2e/fixtures/generation-progress.tsx`。
- 偏离方案及理由：用 flex + nowrap 片段而不是缩小字体来消除孤字；这样目的地名称不被拆开，天数单位也不会被拆开。
- 实际运行的检查与结果：`npm run type-check` 通过；`JP_COMPONENT_E2E=1 e2e/research-progress.spec.ts -g "生成工作区"` 3 项通过；2000px 断言长标题每个目的地片段高度不超过单行、天数片段高度不超过单行且标题右边界不越过停止按钮；1440/390 几何与扫光检查继续通过。
- 实屏证据：`output/polish/20261029-1252-generation-layout/generation-2000-waiting.png`（“杭州＋苏州 4 日”同排）、`generation-2000-long-title.png`（五站长名称、天数不孤行、停止按钮不被挤压）；原有 1440/390 截图继续有效。
- 遗留问题或需要指挥决定的事：无。

### 第 3 轮 · 2026-10-29 15:39 · pi 编码代理

- 改动摘要：过程卡移除固定职责说明，摘要只取真实工具动作、工具结果或已完成的进度结果；删除 planning 的“正在准备相关查询”兜底和通用占位文案。终态与停止态不再显示运行中承诺，折叠正文过滤 running 占位；失败、取消、停止请求中、中断分别使用准确标题，无过程记录时改为中性终态文案。补充完成需求整理后失败、运行中无工具、取消/停止请求、正常研究和 390px 失败卡片的离线组件夹具断言。
- 改动文件：`frontend/src/features/chat/components/ThinkingChain.tsx`、`frontend/src/features/chat/model/researchProgress.ts`、`frontend/src/features/chat/model/researchProgress.test.ts`、`frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx`、`frontend/src/index.css`、`frontend/e2e/research-progress.spec.ts`、`frontend/e2e/fixtures/generation-progress.tsx`、`frontend/e2e/session-state.spec.ts`。
- 偏离方案及理由：无。选择直接删除固定 `description`，摘要优先取已完成进度结果、其次工具结果；没有增加近义句比较器。同步更新 `session-state.spec.ts` 中“已完成住宿卡仍显示进行中文案”的旧断言，改为已结束且不显示进行中内容。
- 实际运行的检查与结果：`npm run type-check` 通过；`npm run test -- src/features/chat/model/researchProgress.test.ts` 5 项通过；`JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1` 10 项通过（含 320/390/1440 研究面板、2000/1440/390 生成工作区、完成需求整理后失败、取消、停止请求中、390px 失败卡片）；`JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --workers=1` 17 项通过。
- 实屏证据：`output/polish/20261029-1252-generation-layout/generation-2000-failed-r3.png`（2000×880，需求整理完成随后失败，卡片仅名称与已结束）；`generation-2000-research-r3.png`（2000×880，正常并行研究，查询结果与来源保留）；`generation-2000-research-r3-details.png`（展开火车查询后可见返回摘要、结果与来源）；`generation-390-failed-r3.png`（390×844，同类失败卡片）；`generation-2000-waiting.png`、`generation-1440-active.png` 继续覆盖等待态、过程区伸展与扫光回归。
- 遗留问题或需要指挥决定的事：实际规划失败根因不在本任务处理范围，按任务留给后端任务；本轮未改动计划审批、SSE/API 或后端。

### 第 4 轮 · 2026-10-29 16:15 · pi 编码代理

- 改动摘要：终态阶段卡按事件来源与生命周期清理运行中占位：dispatcher thinking（agent 显示名“安排查询”，没有 `progress_status`）只宣告并行调研开始，阶段进入已结束/已停止/未完成后不再作为折叠里程碑；planner 的制定调研计划、`progress_status=completed/failed` 的进度结果、工具查询/结果/来源继续保留。新增 `generation-sse` 离线夹具，从真实 `useSendMessage → streamChat → createStreamEvents → createStreamPresentation` 链注入真实 dispatcher thinking 形状，随后发送合成 `run_failed` / `run_cancelled`，验证卡头与展开记录均不再声称正在分派，同时完成说明、计划、目的地查询结果与来源仍可查看。
- 改动文件：`frontend/src/features/chat/components/ThinkingChain.tsx`、`frontend/e2e/research-progress.spec.ts`、`frontend/e2e/fixtures/generation-sse.tsx`（新增）、`frontend/e2e/fixtures/generation-sse.html`（新增）。
- 偏离方案及理由：没有改后端/API/SSE 合同，也没有按“正在分派并行调研任务”内容做字符串黑名单；用 dispatcher 的事件来源（agent 显示名）、缺失 `progress_status` 的生命周期信号以及阶段是否已进入终态区分瞬时宣告与完成里程碑。保留 planner thinking 的计划说明，避免把真实计划一并删掉。
- 实际运行的检查与结果：`npm run type-check` 通过；`npm run test -- src/features/chat/model/researchProgress.test.ts` 5 项通过（分组投影回归）；`JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1` 12 项通过（7.0s）。新增两项覆盖真实 thinking 形状后失败与取消；展开需求卡无 `正在分派并行调研任务`，计划仍可见；目的地查询“找到 1 个结果”、结果预览、来源链接与 390px 无横向溢出继续通过。测试内 `pageErrors=[]`，聊天流由页面内合成 ReadableStream 提供，其余 `/api/*` 由 Playwright 本地 JSON 拦截，未调用模型或真实业务接口。
- 实屏证据：`output/polish/20261029-1252-generation-layout/generation-2000-failed-r4-expanded.png`（2000×880，真实 thinking 形状后失败，展开需求卡仅保留计划，无运行中占位；目的地查询与来源可核对）、`generation-2000-failed-r4.png`（同场景折叠）、`generation-390-failed-r4.png`（390×844 同类失败卡片）、`generation-2000-research-r4.png`（2000×880 正常并行研究）与 `generation-2000-research-r4-details.png`（展开火车查询后的结果与来源）。反馈截图与 `commander-r3-terminal.*` 未改动。
- 遗留问题或需要指挥决定的事：过滤绑定后端公开显示名“安排查询”且以缺少 `progress_status` 作为瞬时宣告信号；若后续后端改动 dispatcher 显示名或为该事件补上完成状态，需要同步调整前端来源判断。实际规划失败根因仍不在本任务范围。

## 8 指挥验收（指挥填写）

### 第 1 轮 · 2026-10-29 · 指挥

- 结论：返工一处标题排版。已核对 2000 与 390 实屏：卡片、删重和过程区伸展符合目标。
- R1：2000px 截图旅行卡标题“杭州＋苏州 4 日”将“日”孤立到下一行；五站标题更容易撑高卡片。需让天数与单位保持整体，合理允许目的地换行，避免孤字和控件挤压；补多站长名称视觉证据。

### 第 2 轮 · 2026-10-29 · 指挥

- 结论：通过，转待真人验收。
- R1 通过：已查看新版 generation-2000-waiting.png 与 generation-2000-long-title.png，天数与单位保持整体，长目的地之间自然换行，停止按钮独立。指挥独立定向回归的生成工作区三项通过，覆盖宽屏占满、长标题、4.6s 扫光、停止/reduced-motion 关闭及手机无横向溢出；与 intake 合计 8 passed（22.8s）。
- 指挥命令：`cd frontend && JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/planner-intake.spec.ts e2e/research-progress.spec.ts --grep "需求工作区|确认开始失败|保存|未确认|生成工作区" --workers=1 --output=../output/polish/20261029-1252-inline-intake/commander-review`。

### 第 3 轮 · 2026-10-29 · 真人反馈后修订

- 结论：返工。新截图显示过程卡内部职责说明与动态摘要仍然近义重复；原来清理页面标题的验收没有覆盖这一层。
- R2：在 ThinkingChain 的公共阶段卡渲染消除信息重叠，覆盖 planning 与其他研究组，不只删除截图里的单句。
- R3：Run 已失败/停止时不再展示仍在准备查询的摘要，保留阶段真实完成状态与有用详情。第 2–6 节已修订，原布局/motion 成果作为回归边界。

### 第 4 轮 · 2026-10-29 · 本轮实现代码验收

- 结论：返工。截图中的固定说明与摘要已去重，但终态展开内容仍有运行中占位漏出，原空 content 夹具没有覆盖真实事件形状。
- R4：`ThinkingChain.tsx:92–96` 只排除 progressStatus 为 running 的里程碑；后端 `conversation/chat/progress_events.py:191–200` 真实 dispatcher thinking 事件没有 progress_status，content 为“正在分派并行调研任务”。用该事件形状随后发送合成 run_failed，展开“已结束”的需求整理卡，仍显示该运行中占位，面板同时已写“调研已停止”。指挥已核对后端事件责任方、过滤条件和实屏证据。
- 期望结果：终态卡头与展开记录都不继续声称任务正在分派/准备；清理应基于真实事件来源/生命周期与展示上下文，不能只增加针对这一句的字符串黑名单。保留实际完成里程碑、查询、结果、来源和真实阶段状态，不修改后端或公开事件契约。
- 补一项使用真实 thinking 事件形状（缺少 progress_status）经过前端 SSE 呈现链再失败/取消的离线检查，展开后验证没有运行中占位，同时有完成内容时仍可查看。按第 6.2 节定向复测，保留现有去重和正常研究证据。
- 证据：`output/polish/20261029-1252-generation-layout/commander-r3-terminal.json`、`commander-r3-terminal.png`；检查 pageErrors=[]、networkStreamRequests=[]，未调用真实模型或业务接口。

### 第 5 轮 · 2026-10-29 · 返工验收

- 结论：R4 通过，转待真人验收。
- 已核对真实 dispatcher thinking 的来源/缺少 progress_status 与终态展示上下文过滤；未使用目标文案字符串黑名单。固定职责说明、运行中兜底及终态瞬时占位均不再重复出现；真实计划、完成进度、查询结果与来源保留。
- 独立审查通过真实前端 SSE 呈现链的失败/取消检查，并补完成说明、查询结果和来源仍可见的序列；pageErrors=[]，后端文件相对返工基线无变化。声明截图均已查看。
- 指挥已查看 `generation-2000-failed-r4-expanded.png` 并核对责任代码及执行记录；额外运行 `cd frontend && JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/planner-intake.spec.ts e2e/research-progress.spec.ts --grep '恢复多段|旧首页保持|真实 thinking' --workers=1 --output=../output/polish/commander-final-checks-20261029`，合计 4 passed，其中真实 thinking 事件后失败、取消两项均通过。
- 验证使用合成事件，不代表真实 Provider 调研或完整交付已经验证。当前过滤依赖 dispatcher 公开显示名和生命周期形状，后端变更对应元数据时需同步检查；本轮合同与 Run/阶段真值未改变。

## 9 真人验收（指挥代录）

### 2026-10-29 · 不通过

> 我们又出现了这种信息冗余的情况

截图：`output/polish/20261029-1252-generation-layout/feedback-2.png`。圈出“理解偏好，准备相关查询”，其下为近义动态摘要。实际无法规划的问题另行调查，不由本前端删重任务掩盖。
