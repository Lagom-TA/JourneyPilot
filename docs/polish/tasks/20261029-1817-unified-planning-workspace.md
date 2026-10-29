# 需求审批留在现有规划工作区，删除独立确认页布局

- 编号：20261029-1817-unified-planning-workspace
- 状态：待真人验收
- 创建：2026-10-29 18:17
- 执行前先读：[工作目录 README](../README.md)、frontend/README.md、frontend/e2e/README.md、docs/invariants.md、AGENTS.md

## 1 用户反馈

> 我们在确认旅行需求的时候，都是用之前的那个页面呀，你不要再跳到新的页面啊，我们不要再设计其他的页面。
> 我们就在这个里面去完成整个规划生命周期的全部操作都在这个界面里面，其他的这个另一个界面，如果要是没有用的话，你就可以直接把它删了。

截图：`output/polish/20261029-1817-unified-planning-workspace/feedback-1.png` 是不需要的整页“确认这趟旅行”；`feedback-2.png` 是需要保留的“左侧旅行信息和进度、右侧规划过程”工作区，均为 2000×880。

## 2 现象与发生条件

首页完成旅行信息后进入正式 Run；计划门 awaiting_input 时出现独立双栏确认页和页脚，批准后又恢复左摘要/进度、右过程的布局。用户要求正式规划开始后都使用第二张图的工作区，审批、修改、取消、调研、交付与调整在现有工作台内进行。不改变首页卡内 intake。浏览器类型未知，现象可由代码确认。

## 3 根因

- `frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx:112` 以 planApprovalGate 是否存在选择整页确认分支；这个分支替换整个 generation-planning-layout，导致审批前后侧栏和主区都被卸载。
- `frontend/src/features/travel/components/planning/TripBriefPlanGate.tsx:78` 把旅行信息、下一步宣传卡与固定页脚组合成独立页面，与已有侧栏重复；取消成功又 CLEAR_CHAT 返回首页。
- `frontend/src/features/travel/components/workspace/DeliveryWorkspace.tsx:599` 的 is-reviewing 样式进一步使审批成为独立布局。该组件已经承载正式 Bundle 的地图、日程、阅读、PDF 与调整，可继续沿用，不需要新路由或新页面。
- 计划门批准是后端必要业务边界（docs/architecture/overview.md 的“计划确认”）；需要删除的是独立页面呈现，不能删除真实审批行为。

## 4 方案

目标状态：从正式 Run 准备、等待审批、修改、执行到终态，旅行摘要/进度侧栏持续存在；右侧原位呈现当前操作。正式交付继续使用现有工作台结果能力。

必须做：

- 移除整个工作区切换为确认页的分支。审批在现有右侧主区原位完成，复用真实计划门动作及状态；左侧旅行摘要与进度在审批/开始/修改前后保持同一布局和挂载。
- 审批主区展示有意义的已识别要求、补充修改、确认开始及取消入口；侧栏已有信息不再大面积重复，不保留“接下来，我们会这样安排”整页说明卡或独立固定页脚。
- 保留服务端 approve/edit/supplement/cancel 合同、修订号、失败保留输入与重试、重复点击阻止、恢复 pending gate、切换会话的归属隔离。不能自动批准或删除计划门业务。
- 取消通过真实命令完成，保留当前工作区和准确取消状态；只有用户主动选择返回/新建旅行时再离开。取消后的 gate 不阻挡终态展示。
- 删除无消费者的独立确认页样式、标题或代码；聊天/快速问答仍使用的组件按实际消费者保留。若交付后调整触发新审批，同样在现有工作台操作区内完成，不出现旧整页确认布局。
- 保留首页卡内澄清与交接、交付后的日程/地图/阅读/PDF/调整、历史只读、手机可滚动和键盘焦点。

执行者自己决定：审批组件与右侧过程区的组合方式、简洁文案、布局尺寸及原位过渡。优先复用现有组件，不新建页面；可把旧 TripBriefPlanGate 重构成唯一的紧凑操作区。

不许碰：后端、公开 API/SSE、持久化、预算/批准规则、真实用户数据、无关页面；不提交不推送。工作区已有大量其他修改，必须按当前文件增量改动，不 reset/覆盖。

## 5 停下来报告的情况

若当前 API 形状无法在原工作台完成必要操作，先提供具体缺失合同证据，不自行改公开接口。保留必要审批不属于停止条件，调整前端呈现已授权。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. pending gate、补充后新修订、approve 后研究、cancel 后终态都留在现有工作台；侧栏不被独立确认页替换，不新增路由或页面。
2. approve/cancel/supplement 请求语义与 Run/revision 归属正确；失败保留输入，等待响应不重复提交，刷新能恢复审批。
3. 当前工作台的交付和调整能力保持可用；已有 Bundle 的调整审批不复活整页布局，手机无横向溢出，按钮和输入可访问。
4. 无消费者的独立页结构/样式清理；无关既有修改保留。

### 6.2 必须运行的检查

在 frontend 下：

- `npm run type-check`
- `npm run test -- src/features/travel/model/planApprovalGate.test.ts src/features/chat/model/conversationFlow.test.ts`
- `JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/planner-intake.spec.ts --workers=1`
- `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --workers=1`

扩展现有离线夹具检查审批前/后侧栏同一 DOM、补充修改/失败重试、取消保持工作区、恢复 pending gate；已有用例若绑定“确认这趟旅行”整页标题，改为验证新行为。API、SSE、地图使用离线拦截，不调用模型、不写真实数据。服务已监听 8088，优先复用。

### 6.3 实屏证据（执行者提供）

2000×880：同一工作区的待确认、展开修改、批准后研究、取消后状态；390×844：待确认可操作且无溢出。截图存本任务 output 目录。用 DOM 记录补充侧栏持续挂载的证据。

### 6.4 真人验收（用户操作）

1. 从首页完成旅行信息 → 进入左侧摘要和进度、右侧操作区的工作台，在里面确认需求，无独立确认页。
2. 点击补充调整、提交修改、确认开始 → 始终使用该工作台，侧栏保留，右侧转为当前进度。
3. 另一次规划选择取消 → 工作台显示已取消；完成规划后可在现有工作台查看日程、地图、报告并调整。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-29 · pi 执行代理

- 改动摘要：正式 Run 的规划工作区不再被计划门整页替换；左侧旅行摘要与进度始终挂载，右侧原位展示紧凑的“确认旅行需求”操作区。审批、补充修改、失败重试、批准后调研和取消都留在同一工作区。取消不再执行 `CLEAR_CHAT`，由真实 `run_cancelled`/Run 状态收口；只有 `pending` 计划门渲染操作区，已取消状态不阻挡终态展示。交付后调整若触发计划门，仍以同一紧凑组件出现在现有调整会话中，不恢复旧整页布局。
- 改动文件：`frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx`、`frontend/src/features/travel/components/planning/TripBriefPlanGate.tsx`、`frontend/src/features/travel/components/workspace/DeliveryWorkspace.tsx`、`frontend/src/features/chat/components/ConversationThread.tsx`、`frontend/src/features/chat/components/ThinkingChain.tsx`、`frontend/src/features/chat/model/agentStages.ts`（仅统一路线阶段识别）、`frontend/src/index.css`、`frontend/e2e/planner-intake.spec.ts`、`frontend/e2e/session-state.spec.ts`、`frontend/e2e/research-progress.spec.ts`、`frontend/e2e/fixtures/research-progress.tsx`；两份任务文档。
- 偏离方案及理由：计划门样式从旧 `plan-review-*` 独立页命名收拢为 `plan-gate-*` 紧凑操作区并删除无消费者的旧双栏/页脚/`is-reviewing` 样式；未改后端、API/SSE、预算或审批语义。为使顶部阶段标题可复用，在 `agentStages.ts` 增加中文节点名/轮次识别与当前阶段投影。
- 实际运行的检查与结果：
  - `npm run type-check`：通过。
  - `npm run test -- src/features/travel/model/planApprovalGate.test.ts src/features/chat/model/conversationFlow.test.ts src/features/chat/model/agentStages.test.ts src/features/chat/model/researchProgress.test.ts src/features/chat/model/toolDisplay.test.ts`：23/23 通过。
  - `JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/planner-intake.spec.ts --workers=1`：7/7 通过。
  - `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --workers=1`：19/19 通过；新增离线用例覆盖 pending gate 恢复、补充修改失败保留输入并重试、新修订、批准后调研、取消后仍留在当前 Run、390px 无横向溢出，并用 DOM 属性确认侧栏持续挂载。
- 实屏证据：`output/polish/20261029-1817-unified-planning-workspace/workspace-2000-pending-gate.png`、`workspace-2000-gate-editing.png`、`workspace-2000-approved-research.png`、`workspace-2000-cancelled.png`、`workspace-390-pending-gate.png`、`intake-2000-gate.png`、`intake-390-gate.png`。均为离线夹具/拦截验证，不含真实 Provider 调用。
- 遗留问题或需要指挥决定的事：未运行真实付费 Provider 验证；本轮只做离线拦截与组件夹具，真实模型下的计划门阶段文案与恢复行为需在授权后另验。

### 第 2 轮 · 2026-10-29 · pi 执行代理

- 改动摘要：配合紧凑工具活动返工，计划门说明文案从“左侧已整理这趟旅行”改为不依赖页面方向的“已整理这趟旅行的信息”，手机单列布局下不再引用不存在的左侧栏。
- 改动文件：`frontend/src/features/travel/components/planning/TripBriefPlanGate.tsx`、本任务文档。
- 偏离方案及理由：无。
- 实际运行的检查与结果：`npm run type-check` 通过；`research-progress` 定向 e2e 13/13 通过。本项只改文案，未重跑完整 session-state 套件。
- 实屏证据：沿用 `output/polish/20261029-1817-unified-planning-workspace/workspace-390-pending-gate.png` 的同类布局；本轮未更新该任务截图。
- 遗留问题或需要指挥决定的事：无。

### 第 3 轮 · 2026-10-29 · pi 执行代理

- 改动摘要：针对 R3/R4。计划门改为按组件自身可用宽度适配，`.plan-gate-card` 使用容器查询，在 560px 以下将操作组纵排、按钮拉满且取消/开始均保留；覆盖 640/660/768px 双栏窄右栏和交付后调整的窄会话栏，不使用 overflow 隐藏。Generation 旅行摘要的同行事实补齐长辈同行与无障碍需要；紧凑 gate 新增旅行摘要上下文，显示成人/儿童/长辈/无障碍与风格标签，因此交付后调整没有 Generation 侧栏时也能确认这些标志。两个特殊 party 标志为真、recognizedRequirements 不含它们的离线夹具已验证确认前、刷新后、批准后和已交付 Bundle 调整 gate 均可读。
- 改动文件：`frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx`、`frontend/src/features/travel/components/planning/TripBriefPlanGate.tsx`、`frontend/src/index.css`、`frontend/e2e/session-state.spec.ts`、本任务文档。
- 偏离方案及理由：用容器查询而不是新的视口断点，才能同时覆盖 640–768px 窄右栏与 420px 左右浮动调整会话；没有新增页面或改 party/API/SSE 语义。迁移摘要时保留既有成人/儿童与风格，只补长辈同行/无障碍并让紧凑 gate 复用同一 identity 事实。
- 实际运行的检查与结果：
  - `npm run type-check`：通过。
  - `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --workers=1`：21/21 通过。
  - 新增离线用例覆盖 640/660/768px：gate 容器与操作组无内部横向溢出，开始/取消/补充按钮均在 gate 边界和视口内可见可点；刷新后特殊同行条件仍在；批准后 Generation 摘要仍显示 1 位儿童、有长辈同行、需要无障碍安排。
  - 新增交付后 Bundle 调整 gate 用例：在窄浮动会话中确认 2 位成人、1 位儿童、长辈同行、无障碍需要与风格标签可读，按钮滚动可达且无内部横向溢出。
- 实屏证据：`output/polish/20261029-1817-unified-planning-workspace/workspace-640-pending-gate-special.png`（640px 双栏窄右栏、特殊同行条件、按钮纵排完整可见）、`bundle-adjustment-gate-1280.png`（交付后调整 gate 上下文）、`bundle-adjustment-gate-actions-1280.png`（窄会话中操作按钮可见）。均为离线夹具/拦截验证，不含真实 Provider 调用。
- 遗留问题或需要指挥决定的事：未运行真实付费 Provider 验证；真实 Provider 下的特殊同行条件文案需在授权后抽查。紧凑工具任务已验收，本轮未改其状态。

## 8 指挥验收（指挥填写）

### 第 1 轮 · 2026-10-29 · 指挥代码与实屏验收

- 结论：通过，转待真人验收。已对照起点 tracked diff，后端及公开合同没有本轮增量；旧 `plan-review-*` / `is-reviewing` 独立页结构及样式无消费者残留。正式规划的侧栏始终存在，右侧原位审批/修改，取消由真实事件收口而不清空旅行。长期交互规则已写入 frontend/README.md。
- 已查看 2000px 待确认/展开修改/批准后规划/已取消、390px 待确认，以及首页多目的地进入审批的桌面/手机证据。最终待确认截图由指挥重新生成，已确认手机不再出现“左侧”方向文案。
- 指挥独立检查：session-state 中 `plan gate stays|cancel keeps` 两项通过（最终复测 2 passed），验证失败保留输入、修订后再次确认、侧栏 DOM 保持、取消留在当前 Run 及手机恢复；planner-intake 中 `旧首页保持|条件规划直接开始` 两项通过，覆盖正常 motion 交接与 reduced-motion、旧流归属。
- 额外补查交付后调整：`output/polish/20261029-1817-unified-planning-workspace/commander-refinement.spec.ts` 的 `commander: delivered trip refinement keeps approval inside existing map workspace` 1 passed。已交付 Bundle 触发新审批时，紧凑操作区位于原调整会话，地图 DOM 保持同一实例，取消后仍保留结果工作台；证据为 `commander-refinement-cancelled.png`。脚本与配置保留在忽略的 output 目录。
- 执行记录中的 type-check、定向单测及三套前端离线回归通过；验证均使用离线 API/SSE/地图拦截，未证明真实 Provider 的端到端交付，未调用付费模型或写真实用户数据。真人操作按第 6.4 节进行。

### 第 2 轮 · 2026-10-29 · 补充审查返工

- 结论：返工。首轮桌面/手机及交付后调整抽查通过，但辅助审查发现两个验收盲区，需要补齐后再转真人验收。
- R3：`index.css` 的审批操作组不收缩，仅 ≤639px 视口时纵排；640–660px 下仍是双栏，右侧实际宽度小，按钮超出容器约 32px 并被裁切。审批布局必须按操作区实际可用空间适配，覆盖窄右栏与交付后调整的窄会话栏；不能只隐藏横向溢出来掩盖。增加 640/660/768px 视口及窄嵌入操作区的离线几何检查，确认开始、取消、补充按钮全部可见可点击。
- R4：移除旧整页旅行信息后，`party.elderly_companions` 和 `party.accessibility_required` 没有迁移到新摘要，若 recognizedRequirements 不重复这些条件，用户无法确认。把长辈同行及无障碍需要保留在现有旅行摘要；同时核对已交付后调整的紧凑审批上下文也能读到这些条件，避免仅修初次生成侧栏。使用两个标志为真但 recognizedRequirements 不含相关文案的夹具，验证确认前、刷新后和开始规划后信息持续可读。
- 修复限于现有摘要/紧凑操作区、相关布局及离线回归；不新增页面，不改 party/API/SSE 语义。更新 640px 与含特殊同行条件的实屏证据，定向运行 type-check 与新增回归。

### 第 3 轮 · 2026-10-29 · R3/R4 返工验收

- 结论：R3/R4 通过，转待真人验收。已查看 640px 特殊同行条件待确认、1280px 已交付调整 gate 及滚动到操作按钮的三张实屏；开始/取消均位于操作区内，长辈同行和无障碍需要可在现有摘要或紧凑审批上下文确认。未新增页面。
- 已核对布局使用 gate 自身 inline-size 容器查询，560px 以下纵向排列操作按钮，覆盖窄右栏与窄会话；不是通过隐藏 overflow 掩盖。同行信息直接消费受控 identity 的 party 字段，不依赖 recognizedRequirements 重复描述，成人/儿童/风格仍保留。
- 指挥独立运行 `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --grep 'narrow plan gate|delivered trip refinement gate' --workers=1 --output=../output/polish/20261029-1817-unified-planning-workspace/commander-r3r4-checks`：2 passed，覆盖特殊条件确认/刷新/批准后保留，以及已有 Bundle 的窄调整会话。
- 额外独立宽度探针 `commander-widths.spec.ts`：1 passed。按 390/640/660/768/1024/1440px 逐项测量 gate/操作组内部无横向溢出、按钮边界在 gate 内，并用 trial click 实测开始和取消可达；测量附在测试报告，截图 `commander-640-approval.png`。测试配置及原始输出均保留在忽略的 output 目录。
- 执行者 type-check、完整离线 session-state 21 项均通过；指挥 `git diff --check` 通过。compact 任务的已验收状态与单行工具列表不受本轮影响。全部验证仍为离线拦截，不涉及付费模型或真实数据写入。

## 9 真人验收（指挥代录）
