# 标题：整理、确认和调研过程卡按真实状态平滑交接

- 编号：20261030-1012-gate-handoff-motion
- 状态：待代码验收
- 创建：2026-10-30 10:12
- 执行前先读：[工作目录 README](../README.md)、`AGENTS.md`、`docs/invariants.md`、`frontend/README.md`、`frontend/e2e/README.md`。

## 1 用户反馈

- 原话：「5 从“正在整理旅行需求”小块平滑展开为确认面板，确认后自然收缩为正在调研小块，兼容恢复、无动画偏好和实际异步状态。」；「截图其余没有标红内容不能随意删除。」
- 反馈图：`output/polish/20261030-1012-gate-handoff-motion/feedback-1.png`。这是展开后的确认状态；截图不包含前后动态，动画行为以文字要求为准。
- 只使用离线/模拟测试，不调用真实付费模型、不修改真实用户数据。本批文档完成后紧接着交付执行，不暂存、不提交。

## 2 现象与发生条件

正式生成工作区：整理中 → 等待确认 → 确认提交 → 实际调研开始。还存在请求延迟/失败、补充修改后再次确认、取消、恢复旧门、切换 Run 和减少动画偏好；均须用本地模拟 SSE/REST 复现。截图浏览器未知。

## 3 根因

- `GenerationJourneyPanel.tsx:41,184-202` 直接按 `gatePending` 替换 `ThinkingChain` 和 `TripBriefPlanGate`；后者 `TripBriefPlanGate.tsx:76` 只有独立入场动画，没有小块到面板及反向的连续尺寸交接。`ThinkingChain.tsx:203` 在 workspace 下默认展开，也不是确认后紧凑小块。
- `useSendMessage.ts:52-78` 发送 gate decision 时保留门；`streamEvents.ts:81-100,125-142` 以真实 SSE 更新门和运行状态。仅点击确认不表示服务端已接受，`chat_start` 也不等于调研实际开始。失败时必须保留可重试的门与编辑内容。
- `useSessionManager.ts:87-101` 和 `useDeliveryEventRecovery.ts:148-166` 从持久状态恢复门，当前实时与恢复门归一到相同状态，不能简单把每次挂载都当作首次展开。全局 `frontend/src/app/motion/MotionProviders.tsx:1-9` 声明尊重系统偏好，但新增布局动画仍需单独验证。

## 4 方案

目标状态：右侧活动区由紧凑的“正在整理旅行需求”自然展开为确认面板；真实确认生效后自然收为过程小块，真实调研阶段到达时显示“正在调研”。恢复和减少动画偏好下直接、准确呈现目标状态。

必须做：

- 在右侧稳定局部容器中完成视觉尺寸交接，不让左侧步骤跨栏飞行、不动画整个页面或已有滚动/composer；避免容器与 Gate 自身入场位移叠加。收起后过程可按现有操作查看，不移除未标红内容或查询详情。
- 实时 `approval_gate_raised` 到达后展开；提交期间保留面板、禁用相应动作；仅门实际被服务端状态清除后收缩。真实的调研/dispatcher 阶段事件到达前，不因点击或 `chat_start` 就宣称“正在调研”。服务端慢、提交失败、取消、终态都要如实显示，不得错演成成功。
- 区分实时新门和会话/事件恢复门：恢复直接落在门的最终样式，不伪造从小块展开或触发额外请求；补充后新 revision 能再次正确展开。跨 Run/会话快速切换和动画中状态再变更不能串状态、复活旧门或遗失输入。
- 系统减少动画偏好时直接达到终态，无残余尺寸/位移过渡；焦点在展开后能到确认标题，收起、失败、取消时不丢失焦点或落进不可见控件；保留键盘操作和正确的可访问状态。
- 普通会话、交付后调整的共享 Gate 不得因工作区动画改变数据或控制行为；保持已有进度、恢复提示、终态 follow-up composer、滚动和手机 sticky 布局。

执行者自己决定：局部状态来源标识、尺寸过渡方式、时长和焦点回落目标；不强制使用特定动画库。跨会话恢复的状态标识应避免改变服务端契约。

不许碰：服务端权威、API/SSE、审批规则、预算/持久化、真实用户数据或未标红内容；不改既有任务文档。工作区已有修改的基线 `/tmp/journeypilot-review-oCppsF/existing-tracked.patch`、`existing-status.txt` 与同目录 `frontend/` 的五个文件快照必须保留。先核对当前差异，在现有修改上窄改；禁止 reset、stash、覆盖、暂存或提交这些已有改动。与本批卡片/面板任务共享 `GenerationJourneyPanel.tsx`、`index.css`、`session-state.spec.ts`，须串行且不能用旧快照覆盖。

## 5 停下来报告的情况

若无法区分实时与恢复而不改变公开契约，或连续过渡会迫使删除过程内容、破坏失败重试/焦点/既有 composer，停止并报告。其余遵守 README 通用停止条件。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 正常动画偏好：模拟延迟的实时门事件前为紧凑整理卡，事件到达后连续展开；点击确认并延迟响应时门仍在，真实状态清除后连续收缩。先 `chat_start` 后 dispatcher：中间不谎称正在调研，真实调研事件后才显示调研标题。
2. 提交失败保留门、输入与错误并可重试；补充后再次展开新 revision；取消/失败落入正确终态，不冒称调研。刷新恢复及事件恢复门直接显示、无虚假初次动画或模型调用。
3. 正常和减少动画偏好、桌面与手机、快速跨 Run 切换均正确；减少动画下无尺寸/位移残留。展开、提交、失败、收起及取消的焦点可达，过程可展开查看；共享会话、滚动和既有 composer 不回归。
4. 动画证据包含转换中的几何/时间变化，而非只断言起止 DOM；测试不能用任意固定等待制造成功或把 skipped 算通过。

### 6.2 必须运行的检查

先在独立终端启动离线 Vite：`cd frontend && PORT=5173 npm run dev -- --host 127.0.0.1 --strictPort`；端口冲突时换空闲 loopback 并同步 URL。测试沿用/扩展 `session-state.spec.ts` 的本地 API 拦截、网络逃逸检查及可控 SSE：

- `cd frontend && npm run type-check`
- `cd frontend && npm run test -- src/features/travel/model/planApprovalGate.test.ts src/features/chat/model/agentStages.test.ts`
- `cd frontend && JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:5173 npx playwright test e2e/session-state.spec.ts --workers=1 --grep 'plan gate stays|cancel keeps|narrow plan gate|delivered trip refinement gate|handoff' --output=../output/polish/20261030-1012-gate-handoff-motion/playwright`
- 给新增过渡用例使用可匹配 `handoff` 的测试名，覆盖 6.1 的延迟事件、正常/减少动画、恢复、重试、补充、取消及焦点；如果置于其他文件，另记录并运行完整命令。

### 6.3 实屏证据（执行者提供）

在 `output/polish/20261030-1012-gate-handoff-motion/` 提供纯模拟 2000×880 桌面和 390×844 手机的整理卡、展开中、确认面板、收缩中、调研卡证据；正常偏好用可逐帧查看的短录屏或连续带时间截图，并提供减少动画与恢复门的最终状态截图。不得记录真实用户信息。

### 6.4 真人验收（用户操作）

1. 运行离线模拟：先延迟门事件，再延迟确认响应 → 整理卡平滑展开，确认未生效前不收起；状态真实推进后收缩，调研事件到达才显示正在调研。
2. 模拟失败重试、补充后再次确认、取消与刷新恢复 → 内容和操作正确；开启减少动画后无位移过渡，键盘焦点可用。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-30 11:23 · Workflow / pi

- 改动摘要：整理卡与确认门以局部尺寸过渡交接；按真实进度切换，恢复直达，减少动画、焦点、跨 Run 和重试均作处理。
- 改动文件：frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx、frontend/src/features/chat/components/ThinkingChain.tsx、frontend/src/features/travel/components/planning/TripBriefPlanGate.tsx、frontend/src/app/session/{streamEvents,useSendMessage,useSessionManager,useDeliveryEventRecovery}.ts、frontend/src/features/travel/model/planApprovalGate.ts、frontend/src/features/travel/types/planning.ts、frontend/src/index.css、frontend/e2e/session-state.spec.ts。
- 偏离方案及理由：无。此前实现代理两次连接中断，后续根据独立复审接手并继续修复。
- 实际运行的检查与结果：`cd frontend && npm run type-check` 通过；`npm run test -- src/app/session/sessionRuntime.test.ts src/features/travel/model/planApprovalGate.test.ts` 10 项通过；离线 Vite 及 API/外网拦截下，`JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:5173 npx playwright test e2e/session-state.spec.ts --workers=1` 51 项通过；修改证据采集后 `--grep 'handoff expands'` 1 项通过。
- 实屏证据：output/polish/20261030-1012-gate-handoff-motion/desktop-2000-handoff-{compact,expanding,gate,collapsed}.png；浏览器 trace 位于同目录 full-regression/、integrated-probes/。
- 遗留问题或需要指挥决定的事：研究计划的审批版本接口正在并行修复；整合后需再次验证，尚未进行真人验收。

## 8 指挥验收（指挥填写）

## 9 真人验收（指挥代录）
