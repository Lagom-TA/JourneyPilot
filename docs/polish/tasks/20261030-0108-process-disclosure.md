# 已结束阶段自动折叠，过程只展示正常公开行动

- 编号：20261030-0108-process-disclosure
- 状态：待真人验收
- 创建：2026-10-30 01:08
- 执行前先读：[工作目录 README](../README.md)、AGENTS.md、docs/invariants.md（尤其 INV-UI-003、INV-NODE-001、INV-SSE-001）、frontend/README.md、frontend/e2e/README.md、[本轮事实/所有权/安全提交](../references/20261030-0108-feedback-workflow.md)

## 1 用户反馈

> 截图2右侧整理旅行需求标题与同名运行项重复且行距不合理。
>
> 截图3已结束调研阶段在右侧默认收起、不继续铺开工具明细（可主动展开查正常结果，完成后再次自动折叠，不跨 Run 串状态）；去掉阶段间和工具行过多横线，用字重字号行距建立层级；失败工具调用、未匹配工具/内部激活失败等不在前端过程正文、摘要或展开详情泄露，后台证据/日志保留，真正阻断整个 Run 的用户可操作错误/终态不能静默吞掉。

截图：`output/polish/20261030-0108-feedback-workflow/feedback/feedback-2.png`、`feedback-3.png`，指挥已 read 看图，不重复复制。

## 2 现象与发生条件

workspace 右侧仅 planning 组时，总标题与同名子项重复。进入调研后，目的地组已完成、交通/住宿仍运行，旧阶段仍铺全部工具明细；“整理规划/未匹配到工具”也被当成一次正常完成行动。阶段及工具间多重横线撑出无意义层级。

需覆盖：实时阶段完成、全部 Run 结束、用户主动查看完成结果、普通聊天与历史 restored thinking_steps、取消/失败/中断、后续 supplement 轮次和切换 Run。用户隐藏失败的是**产品展示**，不是删除后台事实或把失败改成成功。成功但空结果、参考能力/降级结果和未知工具的正常结果不能误作失败消失。

## 3 根因

- `frontend/src/features/chat/components/ThinkingChain.tsx:120–169` workspace 无条件 `showBody = workspace || open`，阶段头在 workspace 走 div 而非 disclosure。`:121` 的 open 只在初次读取状态，没有处理 running→completed；`:174–189` openToolIds 持久存在于组件，未按 Run/阶段完成收敛。`GenerationJourneyPanel.tsx:194–205` 只把 Run 放在 regionId 中，未保证组件状态按 Run 重置。
- `ThinkingChain.tsx:199–211` 顶层用 deriveActivityTitle；`researchProgress.ts:35–39` 又为 planning 组写“整理旅行需求”。`:147–153` 无条件显示组标题，即使它与顶层是同一条当前状态。不是只改一个标题文案就解决。
- `frontend/src/index.css:3732–3759、3793–3799` 保留阶段顶部与逐工具分隔；配合较大 margin/padding，形成截图的多重横线和稀疏留白。
- 上游 `backend/travel_agent/tools/react.py:361–400` 在 search_tools 未命中时仍发 success+“未匹配到工具”；普通失败 `conversation/chat/tool_events.py:102–178` 形成失败的实时/历史步骤。前端 `frontend/src/features/chat/model/streamPresentation.ts:56–104` 经 `toolDisplay.ts:13–20` 把 success→completed、blocked/失败→failed，历史 `frontend/src/features/chat/model/sessionHistory.ts:17–39` 则直接映射已保存状态，两者都进入 ThinkingChain。`frontend/src/features/chat/model/toolDisplay.ts:354–367、392–400` 显式保留未匹配文本（基线单测也期待保留）；`ThinkingChain.tsx:122、129、137–144、166–169` 不做统一行动可见性过滤，失败行会影响详情、摘要、milestones/计数。只隐藏 toolResult 一处仍会泄露。
- 当前中文别名、三段安全详情/计数、输入过滤和工具展开持久性来自 **既有未提交 2325 work-activity-feed**，不是本任务新实现。旧任务要求全部工具可点击、默认平铺，与本轮完成阶段折叠/失败不展示冲突，以本轮要求为准，其余正常结果能力继续保留。

## 4 方案

目标状态：右侧以清楚但克制的标题/阶段/行动层级呈现。当前阶段可看进度，已结束阶段只占一行可展开标题，正常资料可追溯；内部失败不会成为产品正文。整 Run 受阻仍明确告知可操作状态。

必须做：

- workspace 阶段头成为可键盘操作的 disclosure（正确 aria-expanded/controls/焦点）。当前阶段按真实状态展开，**阶段 running→completed 自动收起工具及阶段正文**；用户主动展开已完成阶段可查看正常结果，不因无关新 SSE 重绘反复收起。Run 到终态时再自动收拢已结束内容，之后仍可主动查看；不要以一个永远置 true 的用户开关阻止完成收口。
- 工具详情与阶段展开按本 Run（必要时本阶段轮次）作用域管理。完成时收敛该阶段的详情状态；新 Run/会话/后续阶段的新执行不能继承旧 Run 同工具 id 的展开。无关新事件仍保持当前运行阶段中用户已打开的正常详情，不能一收到任何 SSE 就全部关闭。
- 默认只显阶段标题/真实状态，正常结果必须主动展开可查；已完成阶段可再展开/收起。历史与重放初次加载为已结束阶段时默认折叠。取消/失败/中断不伪称仍在查询，阶段已完成与 Run 失败可同时准确表达。展示状态从原始事实投影，不先删步骤再计算生命周期。
- 顶层当前标题与同名唯一阶段不重复占两行；合并/省略重复层即可，保留阶段状态和展开入口。有多个阶段、并行/补充/退回准备时仍能清楚定位，不把全部名称改成泛称掩盖。
- 删除阶段间/工具间重复横线，主要通过字重/字号/行距区分标题、阶段、行动、详情。保留必要焦点和详情引用边界；维持合理阅读列宽、工具单行密度、手机点击区域，不回到卡片套卡片。
- 在共享展示投影统一排除失败/blocked 的工具行动，以及 search_tools 未匹配、内部激活失败等内部过程，不让其进入行标题、工具列表、阶段摘要、milestones、计数、输入/结果预览、title/aria 或详情。实时和历史/普通聊天复用同一策略，不能只给 workspace 隐藏 CSS。利用已有状态/工具语义及历史公开字段，不堆只匹配截图字符串的黑名单。
- 失败被排除后不能留下孤立空标题、空 disclosure、“N项需留意”或把最后失败摘要继续当阶段说明。全部工具失败且无正常结果可使用阶段真实状态/安全中性空态，不伪造结果。成功零结果不是失败，正常降级/参考能力、未知成功工具仍按现有中文别名与安全详情可查看。
- 后端工具执行、日志/审计、原始步骤/SSE不改不删，前端 reducer仍存真实事件以供生命周期判定。不隐藏整个 Run 的 failed/interrupted/cancelled、可操作全局错误/继续/重试/返回动作；技术异常原文不直出，有必要时沿现有安全错误投影给出行动。不能静默吞整个 Run 的终态来达成“无失败文字”。
- 保留 INV-UI-003：正常输入/结果/预览/来源仍过滤机器载荷、内部名/异常，明确总数不能取预览长度；正常长查询、键盘展开与安全来源可用。左摘要、审批、底部旧composer、恢复浮框及焦点/滚动不回归。

执行者自己决定：组头与顶层标题的职责分配、展开状态容器和Run key、可见性纯投影位置、字体间距；优先扩展 toolDisplay/researchProgress 和 ThinkingChain，不建立第二套工具别名/展示规则。

不许碰：后端、API/SSE/历史存储合同、Run/阶段真实状态、原始审计/失败证据、Provider、真实数据、审批/预算和正式Bundle。唯一 frontend 执行者在前序需求/首页/摘要任务后顺序拥有 ThinkingChain、toolDisplay/researchProgress/必要agentStages、相关组件/会话合成夹具与CSS增量；Generation只允许本任务所需Run作用域/安全错误呈现增量，不改左摘要/旧composer。只改本文状态与第7节，不自行提交/推送。

## 5 停下来报告的情况

- 某类工具只有普通文本、无法凭现有公开字段区分失败与正常空结果，先列最小合成案例与区分所需信息，不能一刀切隐藏空结果或请求原始敏感载荷。
- 需要改后端执行/日志/事件顺序或删持久化证据才能隐藏失败，说明超出展示任务并停止。
- 原始生命周期事实无法判定完成/轮次，先报告；不靠动画时间、过滤后的工具列表猜阶段结束。
- dirty详情/计数等前置功能导致本轮 delta 不能在拟提交HEAD树运行，按本轮安全策略报告提交受阻；不能把旧工具重做/续聊/恢复整块混入本轮提交。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 截图3等价状态下目的地已完成组默认折叠，交通/住宿继续真实显示；用户可展开正常结果；无关SSE保持手动查看，阶段完成/Run终态按既定边界再次收起，新Run不继承。
2. 截图2等价仅planning时同名标题不重复、状态和可操作入口仍在；阶段/工具间无重复横线，层级与行距清楚，手机无横溢。
3. 失败/blocked工具、无命中/激活失败的内部行动在正文、摘要、计数、title/aria、展开详情均不存在；历史同样处理。成功空结果、降级/参考、未知成功工具没有误删，正常输入/结果/来源可查。
4. 后端与原始步骤/审计保持真实失败证据；Run失败/中断/取消和真正阻断错误仍有安全提示与实际动作。普通聊天同享安全/可见性策略，但不强制改其视觉布局。
5. 前序需求计划、侧栏、旧恢复浮框/续聊输入不回归；没有为了截图强制成功或修改Run终态。

### 6.2 必须运行的检查

前提：确认8088为当前checkout的Vite；无服务时单独串行 `npm run dev -- --host 127.0.0.1 --port 8088 --strictPort`。所有外网/API未匹配即拒绝，不使用真实后端。

```bash
cd frontend
npm run type-check
npm run test -- src/features/chat/model/toolDisplay.test.ts src/features/chat/model/researchProgress.test.ts src/features/chat/model/agentStages.test.ts
JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1 --output=../output/polish/20261030-0108-process-disclosure/playwright-component
JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --workers=1 --output=../output/polish/20261030-0108-process-disclosure/playwright-session
```

扩展真实组件与合成SSE检查：running→完成（包含已展开详情）→手动查看→无关事件→Run终态再次收起→新Run复用id；历史默认折叠；同名planning去重；failed/blocked、status=success但search_tools无命中、激活失败、失败preview/milestone的所有出口；成功空结果/正常降级/未知成功工具仍可看；整个Run失败/中断有动作。测试必须看可见文本、属性/aria与可打开详情，不只断言结果容器 hidden。保留计数、JSON/内部名过滤、长文本/来源/键盘和完整离线session-state里的恢复/续聊/归属回归。旧“workspace组头无button/未匹配文本保留”的断言按新要求更新，不删除正常查询检查，不跑live/write套件。

### 6.3 实屏证据（执行者提供）

存 `output/polish/20261030-0108-process-disclosure/`：2000×880 仅planning去重、目的地完成且交通/住宿运行、主动展开正常来源、Run终态再次收起；390×844 完成折叠/正常详情；另含整个Run失败/可恢复中断可操作提示。附新Run复用id展开状态记录、失败DOM/属性/预览不泄露检查、可见行高/内容列宽测量。指挥read逐张查看，合成夹具要标“离线样例”。

### 6.4 真人验收（用户操作）

1. 在离线规划演示观察右侧 → “整理旅行需求”不重复堆两行，层级清楚、横线更少。
2. 让目的地调研完成、其余继续 → 已结束阶段自动收起；主动展开可查正常查询及来源，Run完成后再次折叠。
3. 查看含失败/未匹配内部调用的演示，再切另一Run → 不见内部失败行或详情，旧展开不串过去；若整个Run失败/中断，仍有明确安全提示与可用恢复/重新开始动作。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-30 02:10 · frontend

- 改动摘要：workspace 阶段头改为可键盘操作的 disclosure，按 Run key 重置展开状态；阶段 running→completed、Run 进入终态时自动收起该阶段正文和工具详情，用户主动展开后不被无关 SSE 重新收起，新 Run 不继承旧展开。仅一个同名 planning 阶段时不再重复标题，只保留状态行。删除阶段间/工具行重复横线，改用字号、字重和间距分层。新增统一公开行动投影：失败工具、失败进展、`search_tools` 未匹配/激活失败不进入标题、摘要、里程碑、计数、输入/结果预览、aria 或详情；成功空结果、参考能力、未知成功工具仍保留。Run 级失败/中断/取消仍由工作区状态、提示和恢复/返回动作表达。
- 改动文件：`frontend/src/features/chat/components/ThinkingChain.tsx`、`frontend/src/features/chat/model/toolDisplay.ts` / `toolDisplay.test.ts`、`frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx`、`frontend/src/index.css`、`frontend/e2e/fixtures/research-progress.tsx`、`generation-progress.tsx`、`frontend/e2e/research-progress.spec.ts`、`session-state.spec.ts`、本任务第 7 节。
- 实际运行的检查与结果：
  - `npm run type-check` → 通过；完整前端单测 `npm run test` → 107 passed。
  - `npm run test -- src/features/chat/model/toolDisplay.test.ts src/features/chat/model/researchProgress.test.ts src/features/chat/model/agentStages.test.ts` → 26 passed。
  - `JP_COMPONENT_E2E=1 ... npx playwright test e2e/research-progress.spec.ts --workers=1` → 18 passed，覆盖完成折叠、手动再展开、无关事件保持、Run 终态再次收起、新 Run 重置、同名标题去重、失败/未匹配/激活失败不泄露、成功空结果保留、320/390/1440/2000 布局。
  - `JP_SESSION_STATE_E2E=1 ... npx playwright test e2e/session-state.spec.ts --workers=1` → 40 passed，含历史恢复默认折叠、审批、只读、恢复浮框、续聊和地图回归。
- 实屏证据：`output/polish/20261030-0108-process-disclosure/` 下 `process-2000-planning-only.png`、`process-2000-destination-completed.png`、`process-2000-expanded-source.png`、`process-2000-terminal-collapsed.png`、`process-390-completed-expanded.png`、`process-2000-run-failed-actions.png`、`workspace-2000-internal-failures-hidden.png`、`workspace-2000-new-run-reset.png`；`measurements.json`、`failure-visibility.json`、`new-run-reset.json` 记录行高/列宽、失败 DOM/预览检查和新 Run 展开状态。
- 未运行/已知风险：失败过滤依据现有公开 `toolStatus`、`progressStatus` 和 `search_tools` 结果语义，没有改后端事件；如果某类内部失败只有普通成功文本且无可用语义，仍可能只能按正常行动展示。全部工具都被过滤的组会自然消失，Run 级失败仍由外层状态与动作保留。未运行 live/write 套件。
- 后端整合结论：未改后端、SSE/历史合同、原始步骤/审计或终态；后台失败证据仍保留，前端只做展示投影。

### 第 2 轮 · 2026-10-30 02:35 · 返工（frontend）

- 改动摘要：阶段生命周期改为从未过滤的原始进展事件计算，展示内容再排除失败/内部行动；“running → 正常工具结果 → failed”现在得到真实失败终态并自动折叠，失败正文仍不进入正文、摘要或详情。同一 Run 的补充轮次复用阶段 key 时，阶段从非运行回到运行时重新展开，并清空该阶段上一轮的工具详情展开状态；新 Run 的旧展开仍不继承。
- 改动文件：`frontend/src/features/chat/components/ThinkingChain.tsx`、`frontend/e2e/fixtures/research-progress.tsx`、`frontend/e2e/research-progress.spec.ts`、本任务第 7 节。
- 偏离方案及理由：无。未改后端事件、原始步骤或 Run 终态；只在现有公开字段上调整生命周期投影和展开状态。
- 实际运行的检查与结果：
  - `npm run type-check` → 通过；`npm run test` → 107 passed；定向单测 26 passed。
  - `JP_COMPONENT_E2E=1 ... npx playwright test e2e/research-progress.spec.ts --workers=1` → 21 passed；新增“结果后失败仍结束并折叠”“同 Run 补充轮次重新展开且旧详情不继承”回归，原完成折叠、失败过滤、新 Run 重置、长查询与移动布局断言继续通过。
  - `JP_SESSION_STATE_E2E=1 ... npx playwright test e2e/session-state.spec.ts --workers=1` → 40 passed。
- 实屏证据：`output/polish/20261030-0108-process-disclosure/process-2000-failed-after-result.png`、`process-2000-supplement-round.png`，以及同目录 `failed-after-result.json`、`supplement-round-reset.json`（记录真实状态、折叠/展开与旧详情可见性）。均为离线合成事件。
- 遗留问题或需要指挥决定的事：无。

## 8 指挥验收（指挥填写）

### 本轮独立复核 · 2026-10-30

- 结论：本项代码验收通过，待真人验收；不表示整批需求计划任务已通过或已提交。
- 本轮抽查：核对 ThinkingChain 从原始步骤计算生命周期、完成/终态折叠和 Run/补充轮次展开隔离，再经共享公开行动投影展示；正常工具详情/来源仍需主动打开，Run 错误动作未被删。read 查看原反馈及 `process-2000-destination-completed.png`，目的地完成收起而交通/住宿继续，重复横线减少；前轮失败过滤、结果后失败、补充轮次与跨Run独立浏览器记录仍有效。
- 检查范围：沿用需求计划任务第8节“第4轮后独立复验”已运行的前端34项单测/type-check、过程21项、首页5项、intake7项、session19项及关键实屏结论；本轮纯后端排除修复未触碰前端，不重复运行，也不冒称本轮新跑。此次后端相关组合重新运行289 passed、定向Ruff及diff检查通过，但发现需求计划任务有非研究住宿展示要求重新启用被排除研究的P2，已另记返工，不属于本项视觉/交互缺陷。
- 边界：baseline存档16个哈希一致，无关恢复浮框、InputArea、followupComposer与旧任务原样保留，索引为空；本次不改产品代码、不暂存或提交。隔离dirty后的候选提交树留下一阶段独立验证，未计为通过；无真人结果，未标“已验收”。

### 第 6 轮后复核补记 · 2026-10-30

- 结论：本项仍为代码验收通过、待真人验收；需求计划任务上一轮的非研究住宿要求覆盖研究排除P2现已修复，整批未发现新的阻断项。未将任何任务标为“已验收”。
- 本轮重新运行后端相关组合293 passed、排除语义定向9 passed、Ruff及diff检查通过；两个原审查探针均通过，真实补充/批准/分派链路无住宿工具执行意图。详见需求计划任务第8节“第6轮后独立复验”。
- 本轮抽查四项任务覆盖、相关组件/断言与既有实屏；没有重跑前端单测/type-check或浏览器，先前结果仍为历史记录。baseline存档16个哈希及无关既有改动保留情况已核对；产品代码只读、index为空，未暂存/提交/推送。候选提交树交下一阶段独立验证，真实Provider端到端及真人验收未运行。

## 9 真人验收（指挥代录）
