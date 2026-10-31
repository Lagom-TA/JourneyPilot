# 工作过程结束后提供续聊输入，统一正式规划工作台

- 编号：20261029-2325-workspace-followup-composer
- 状态：待真人验收
- 创建：2026-10-29 23:25
- 执行前先读：[工作目录 README](../README.md)、AGENTS.md、frontend/README.md、frontend/e2e/README.md、docs/architecture/overview.md、docs/invariants.md、[本轮调研](../references/20261029-ai-work-activity.md)

## 1 用户反馈

> 右侧的工具调用链展示结束之后，下方应该有一个输入框，让我可以继续补充信息。用这一新设计的工作台页面取代其他承担该作用的页面。

截图：`output/polish/20261029-2325-workspace-followup-composer/feedback-1.png`。右侧标题已经为“旅行规划已完成”，工具过程仍可见，但下方没有输入框；同时正式结果正在恢复，尚未进入交付后的行程视图。用户希望直接在当前上下文继续补充，而不是寻找另一聊天页。

相关历史：`20261029-1817-unified-planning-workspace` 已把审批留在正式工作台，仍待真人验收。本任务保留该方向，补齐过程终态的续聊，不重新引入独立确认页或聊天页。

## 2 现象与发生条件

`GenerationJourneyPanel` 在已有受控旅行身份和 Run、但尚无 Bundle 时显示左侧旅行信息／进度、右侧工作过程。完成、失败、取消或中断后，右侧只有 `ThinkingChain`，没有消息输入。截图中的 `completed + deliveryBundle=null + 恢复提示` 是必须覆盖的真实状态。

正式 Bundle 到达后，`DeliveryWorkspace` 展示行程；点击“调整”会打开嵌入 `ConversationThread`，后者已有 `InputArea`。因此不能另造第三套聊天页面或发送逻辑，需要让生成过程与交付调整在同一正式工作台中复用输入能力。历史 Run 为只读；计划门等待输入时已有专用补充编辑区。

## 3 根因

- `frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx:172–190` 的右侧只渲染错误或 `TripBriefPlanGate`／`ThinkingChain`，没有 `InputArea`；`.generation-activity` 与 `.generation-activity-body` 也只是滚动内容容器，没有“独立滚动过程 + 底部 composer”的结构。
- `frontend/src/features/chat/components/ConversationThread.tsx:211` 已经挂载 `InputArea`，但该组件只用于普通会话和交付后的嵌入调整，未进入 Generation 面板。于是同一 Run 在 Bundle 恢复前没有续聊入口，Bundle 到达后才换到另一种交互布局。
- `InputArea.tsx:48、58` 已走 `useSendMessage`；`useSendMessage.ts:15–155` 负责 session、stream ownership、route／resume 和消息状态。新入口必须复用这条链，不能在面板里直接 fetch 或写一套本地假消息。
- `GenerationJourneyPanel.tsx:38、81–100、164–168` 已有可恢复中断的“继续生成”和重新开始动作；新增补充输入不能破坏专用 `resumeRunId + trip_refinement` 路径，也不能让旧恢复流覆盖新会话。
- `InputArea` 的 `minimal` 当前会自动聚焦。终态出现输入框时若原样复用，可能抢焦点或滚动页面，需要把“可复用输入能力”和“是否自动聚焦”分开。

## 4 方案

目标状态：在生成过程仍可见的可写终态中，右侧底部有与内容列对齐的输入框，用户可直接补充要求并沿现有发送链继续。正式 Run 从准备、审批、过程、终态到交付调整始终由同一个 `TripWorkspaceShell` 工作台承载，不新增或保留另一个承担同一职责的页面。

必须做：

- **终态直接可续聊。** 当过程面板处于非 streaming 的可写终态（至少 completed、failed、cancelled、interrupted）时，在右侧过程下方显示输入框。特别覆盖截图的 `completed + Bundle 尚未恢复`；不能只验证交付后的“调整”入口。
- **输入区固定在面板底部，过程独立滚动。** 桌面长工具链不会把输入框推到需要滚完整条链才能找到的位置；输入区与动态内容列对齐。手机上可随布局自然到达或使用不遮挡内容的底部区域，输入框、发送按钮和键盘焦点均不被裁切。
- **复用现有输入与发送。** 优先复用 `InputArea`／`useSendMessage`，沿用当前 session、Run、route／resume、消息持久化和流归属；不得直接请求后端、伪造成功、只写本地气泡或悄悄清空当前旅行。根据当前状态保持与现有流程一致的请求语义，可恢复中断不得丢失专用恢复路径。
- **避免重复职责。** 运行中不新增第二个停止／发送入口；`awaiting_input` 的计划门继续使用现有补充编辑与批准动作，不再叠一个普通 composer；pending intake／route confirmation 不被绕过。历史只读 Run 不显示可写输入，并保留只读说明。
- **保持交付与调整连续。** 已确认 Bundle 仍按现有合同进入行程工作台，不为留住 composer 阻止交付。交付后的“调整”继续在同一工作台使用共享输入组件和新过程视觉，不跳去独立聊天页，也不自动打开调整视图遮挡行程。
- **焦点与内容稳定。** composer 在终态出现时不自动抢焦点、不强制滚到底；用户主动点击／打开交付调整时可按现有规则聚焦。发送后立即遵循现有 streaming 状态，防止重复提交；切换 session／Run 后旧流和旧恢复不能写入新上下文。
- **统一工作台而非新增页面。** 正式 Run 继续由 `TripWorkspaceShell` 的 journey workspace 承担；若发现仍有平行的正式规划整页会话，改为复用此工作台或删除无消费者分支。首页新旅行、必要澄清、我的行程、报告与地图不是“重复页面”，不得误删。
- 失败状态不再只用“回到新旅行重新尝试”暗示唯一出路；保留原有“继续生成／返回新旅行”等真实动作，同时让补充输入成为可用选择。

执行者自己决定：抽出一个小的共享 composer 容器还是给 Generation 直接组合 `InputArea`、终态判定纯函数、各状态辅助文案、桌面 sticky／flex 与手机布局的具体实现。实现选择必须服从上述状态边界，不做一套新的消息状态管理。

不许碰：后端、API/SSE 合同、Run 状态机、supplement／审批归一化、预算和取消规则、Bundle 确认、真实用户数据、首页 intake、行程／地图／报告及无关页面；不提交不推送。与 `20261029-2325-work-activity-feed` 共用右侧面板，应在其后顺序实施或明确同一文件所有权。

## 5 停下来报告的情况

- 若某一终态使用现有 `InputArea`／`useSendMessage` 无法保持正确 session／Run／route，或必须修改公开合同才能继续，给出实际请求与状态证据后停止；不得通过新建无关 Run 或绕过审批掩盖。
- 若已完成但 Bundle 恢复中的补充会与现有恢复所有权冲突，先记录可复现的覆盖／串流路径，不通过禁用恢复或伪造 Bundle 解决。
- 若需要删除首页澄清、计划门或交付视图才能称为“统一”，说明方案理解有误并停止；本任务只合并重复的正式工作区职责。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. completed（含 Bundle=null 的恢复中）、failed、cancelled、interrupted 的可写过程页均在右侧底部显示可用输入；长链下桌面无需滚完过程即可看到，390px 无裁切或横向溢出。
2. 输入复用现有发送链，请求只发一次且 session／Run／route／resume 与对应现有流程一致；发送后进入真实 streaming，旧流不污染新上下文，没有本地假结果。
3. running／cancel_requested 不出现重复操作入口；pending plan gate 只有专用审批编辑；pending intake 不被绕过；历史只读无 composer。原“继续生成”仍使用专用恢复路径。
4. Bundle 到达后的行程、地图、报告和“调整”不回归，调整仍留在同一正式工作台；没有新增正式规划路由／页面或第二套消息请求逻辑。
5. composer 出现不抢焦点、不强制滚动；键盘输入、Enter／发送、 multiline 与 reduced-motion 行为保持可用。

### 6.2 必须运行的检查

在 frontend 下：

- `npm run type-check`
- `npm run test -- src/features/travel/model/planApprovalGate.test.ts src/features/chat/model/conversationFlow.test.ts`
- `JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1`
- `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --workers=1`

扩展现有合成 SSE／离线会话夹具，至少覆盖 completed+Bundle=null、failed、cancelled、可恢复 interrupted、pending gate、历史只读和交付后调整；拦截并检查续聊请求次数与身份字段，再推送真实形状的新事件验证归属。全部离线，不调用模型或写真实数据。

### 6.3 实屏证据（执行者提供）

- 2000×880：与反馈相同的 completed+恢复中状态，过程下方直接有输入；长工具链时输入仍在面板底部。
- 2000×880：failed 或可恢复 interrupted 的补充状态，以及交付后同一工作台的调整输入。
- 390×844：终态输入与发送按钮可见、软件键盘等效焦点不造成横向溢出；pending gate 不出现重复 composer。
- 保存到 `output/polish/20261029-2325-workspace-followup-composer/`，附过程滚动区与 composer 的几何测量、续聊请求的身份字段脱敏摘要。

### 6.4 真人验收（用户操作）

1. 在一次规划过程完成或停止后，直接在右侧下方输入“第二天少安排一个景点，多留休息时间”并发送 → 不跳去另一聊天页，当前旅行上下文继续更新。
2. 滚动查看较长的过程记录 → 桌面输入仍位于面板下方；点击工具详情再返回输入，焦点和滚动不被突然重置。
3. 打开已交付旅行的“调整”与一份历史只读记录 → 前者在同一工作台可补充，后者没有可写输入；审批时仍只有明确的审批编辑和确认动作。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-30 00:36 · pi／Claude

- 改动摘要：生成工作台的可写终态（completed、failed、cancelled、interrupted）在右侧过程下方显示 composer，并覆盖截图中的 completed + Bundle=null 恢复中状态。过程区改为独立滚动，composer 固定在动态列底部；桌面与内容列对齐，手机使用底部 sticky 区域。composer 直接复用现有 `InputArea`／`useSendMessage`，不新增消息状态、请求或假成功；发送语义与交付后“调整”一致（沿用当前 session，不带 `run_id`／`route`），可恢复中断仍由原“继续生成”按钮走 `resumeRunId + trip_refinement` 专用路径。新增纯函数判定可写终态，排除了 streaming、`awaiting_input` 计划门、pending intake／route confirmation、历史只读和 `cancel_requested`，并补充历史只读说明。
- 改动文件：`frontend/src/features/travel/model/followupComposer.ts`、`frontend/src/features/travel/model/followupComposer.test.ts`、`frontend/src/features/chat/components/InputArea.tsx`、`frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx`、`frontend/src/index.css`、`frontend/e2e/session-state.spec.ts`。
- 偏离方案及理由：无。`InputArea` 增加可关自动聚焦与占位文案参数，避免终态出现时抢焦点；默认值保持原有交付调整行为。
- 实际运行的检查与结果：
  - `npm run type-check`：通过。
  - `npm run test -- src/features/travel/model/planApprovalGate.test.ts src/features/chat/model/conversationFlow.test.ts`：2 个文件、5 项测试全部通过。
  - `npm run test -- src/features/travel/model/followupComposer.test.ts`：1 个文件、5 项测试通过；另在扩展夹具前一并运行过这三个测试文件，10 项通过。
  - `JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1`：14 项通过。
  - `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --workers=1`：40 项中 38 项通过、2 项失败。新增的本任务用例（completed+Bundle=null 长链、failed、cancelled、可恢复 interrupted、pending gate、历史只读、交付后调整、390 终态）全部通过；续聊请求拦截为 1 次，身份为 `session_id=A`、`run_id=null`、`route=null`、无 `gate_decision`，随后推送新 `chat_start`／`thinking` 事件并确认新 Run 内容归属，恢复专用路径请求仍为 `run_id=run-A`、`route=trip_refinement`。失败项：① `浮动的恢复提示不改变工作区几何、滚动位置与键盘焦点` 在 560px 高视口下由绝对定位的恢复提示拦截过程标题点击，与 `20261029-2325-work-activity-feed` 记录的既有失败相同；② `desktop itinerary cards and map stay linked across hover, selection, days and layers` 在完整套件中偶发 `interactive-itinerary` 两个场景节点，单独用 `--grep` 重跑通过。两项都不是本任务新增的 composer 或发送链行为。
- 实屏证据：`output/polish/20261029-2325-workspace-followup-composer/`：`desktop-2000-completed-followup.png`、`desktop-2000-completed-followup-scrolled.png`、`desktop-2000-failed-followup.png`、`desktop-2000-interrupted-followup.png`、`desktop-2000-delivered-adjustment.png`、`phone-390-completed-followup.png`、`phone-390-completed-followup-keyboard.png`、`phone-390-pending-gate.png`、`desktop-composer-geometry.json`、`phone-composer-geometry.json`、`followup-request.json`。几何摘要：2000×880 下过程滚动区 `scrollHeight=1064`／`clientHeight=696`，composer `top=759.8`／`bottom=880`，输入列 `left=680` 与过程列 `left=680` 对齐，文档横向溢出 0；390×844 下 composer 宽 390、发送按钮右边 357，聚焦并压缩到 390×500 后 composer `bottom=500`，横向溢出 0。请求摘要：`POST /api/chat-stream` 共 1 次，`session_id=A`、`run_id=null`、`route=null`、`gate_decision=null`。
- 遗留问题或需要指挥决定的事：完整 `session-state.spec.ts` 的两项失败见上；恢复提示点击冲突建议交回 `20261029-2325-floating-recovery-notice`／`20261029-2325-work-activity-feed` 的既有验收，行程场景双节点偶发属于既有动画时序。本任务未修改后端、公开合同、Run 状态机或真实数据，也未调用付费模型。

### 第 2 轮 · 2026-10-30 00:53 · pi／Claude

- 改动摘要：只处理 R1 中行程场景的测试时序。用上一轮失败 trace 核对到两个 `interactive-itinerary` 分属退出的全程场景和进入的当天场景：退出节点带有 `aria-hidden="true"`、`inert` 且已不可交互，进入节点正在播放入场动画，确认是 `AnimatePresence` 过渡期的短暂共存，不是持续重复挂载。测试在切换单日后先等当前非隐藏场景唯一、全局 testid 唯一，再用该当前场景内的容器读取滚动位置；未使用 `.first()`、强制操作或放宽断言，也未修改行程、地图或动画产品行为。
- 改动文件：`frontend/e2e/session-state.spec.ts`。
- 偏离方案及理由：无。
- 实际运行的检查与结果：
  - `npm run type-check`：通过。
  - `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --workers=1 --grep "desktop itinerary cards and map stay linked" --repeat-each=3 --reporter=line`：3 项全部通过（15.9s）。
  - `JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/session-state.spec.ts --workers=1 --reporter=line`：40 项全部通过（1.3m），包含本任务 composer 用例与 R1 场景。
  - `npm run test -- src/features/travel/model/planApprovalGate.test.ts src/features/chat/model/conversationFlow.test.ts src/features/travel/model/followupComposer.test.ts`：3 个文件、10 项测试全部通过。
  - `JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8088 npx playwright test e2e/research-progress.spec.ts --workers=1 --reporter=line`：14 项全部通过（9.3s）。
- 实屏证据：不需要；本轮只修正测试对短暂退场内容的读取时序，未改变界面。
- 遗留问题或需要指挥决定的事：无。未提交、推送、切分支或修改其他任务。

## 8 指挥验收（指挥填写）

### 第 1 轮 · 2026-10-30 · 完整回归检查

- 结论：返工。composer、请求身份、只读／审批边界和实屏证据符合方案；恢复浮层与工具输入返工也已通过。指挥独立运行完整 session-state 时 39/40 通过，剩余一项阻断最终验收。
- R1：`desktop itinerary cards and map stay linked across hover, selection, days and layers` 在单日切换后读取 `interactive-itinerary` 时遇到两个节点，独立重跑同样失败。初步证据指向退出场景与进入场景的短暂共存，而非持续重复挂载。核实过渡生命周期：若确为短暂退出节点，测试必须等待当前场景稳定且唯一后再读取，不得用 `.first()`、强制操作或放宽断言掩盖；若节点持续存在，则修实际重复挂载责任方。该检查只用于恢复可靠回归，不改变行程／地图行为。完成后运行该用例和完整离线 session-state，记录真实结果。
- 指挥检查同时通过：type-check、21 项相关单测、research-progress 14/14。失败证据：`output/polish/20261029-2325-workspace-followup-composer/commander-final-checks/` 与 `commander-map-isolated/`。

### 第 2 轮 · 2026-10-30 · R1 返工验收

- 结论：通过，转待真人验收。trace 证明两个行程节点分别是带 `aria-hidden`／`inert` 的退出场景和进入场景，不是持续重复挂载。测试现等待当前非隐藏场景及全局 testid 唯一后再读取，未使用 `.first()` 或放宽断言，未改产品行为。
- 指挥独立将该行程用例连续运行 2 次均通过；执行者另连续运行 3 次并通过完整离线 session-state 40/40、research-progress 14/14 和相关单测。此前的恢复提示与工具输入返工在同一最终工作区中保留。
- 已查看 completed+Bundle=null、长链底部 composer、手机、审批及交付调整证据。输入复用现有发送链，请求只发一次且 session／Run 归属符合现有调整语义；继续生成专用恢复路径、只读和审批边界均成立。

## 9 真人验收（指挥代录）
