# 标题：精简生成工作区的旅行需求确认面板

- 编号：20261030-1012-gate-declutter
- 状态：待代码验收
- 创建：2026-10-30 10:12
- 执行前先读：[工作目录 README](../README.md)、`AGENTS.md`、`docs/invariants.md`、`frontend/README.md`、`frontend/e2e/README.md`。

## 1 用户反馈

- 原话：「3 右侧确认旅行需求移除截图红框标注的“开始规划前”、标题下说明、同行与风格重复区域、研究计划下解释、底部左侧说明，保留确认、取消、调整等功能」；「截图其余没有标红内容不能随意删除。」
- 反馈图：`output/polish/20261030-1012-gate-declutter/feedback-1.png`。红框分别指向右侧眉题、标题下的说明、单独的同行/风格摘要区、研究计划下说明和底部左侧说明。
- 只使用离线/模拟测试，不调用真实付费模型、不修改真实用户数据。本批文档完成后紧接着交付执行，不暂存、不提交。

## 2 现象与发生条件

正式生成工作区的计划待确认状态，截图为桌面宽屏；恢复、补充后的确认以及手机窄屏也使用确认组件。具体浏览器不详。确认组件还被普通会话及交付后的行程调整会话使用，后两者未必有截图左侧旅行卡。

## 3 根因

`frontend/src/features/travel/components/planning/TripBriefPlanGate.tsx:76-153` 将五类静态辅助文案/重复摘要与计划、已识别要求和操作同时渲染；`GenerationJourneyPanel.tsx:123-150` 已在同工作区展示同行与风格。右侧计划正文来自后端 `plan_text` 或 `steps`，不能把它与单独的重复摘要区混为一谈。共享组件还从 `frontend/src/features/chat/components/ConversationThread.tsx:175`、交付后工作区路径使用，直接全局移除摘要会丢掉别处可能唯一的身份信息。

## 4 方案

目标状态：生成工作区仅移除截图五处红框内容，确认面板更紧凑，原有功能和未标红内容完整。

必须做：

- 移除该场景中的“开始规划前”、标题下说明、单独的同行/风格重复块、研究计划下解释、底部左侧说明；不要对未标红内容做广泛删减。左侧旅行卡仍能读取同行人数、长辈、儿童、无障碍及风格。
- 保留“确认旅行需求”标题、研究计划标题和完整正文/步骤、已识别要求（存在时）、补充或调整入口及编辑内容、错误提示、取消和确认操作；这些操作仍使用真实的现有异步决策链。旧 `plan_text` 或步骤回退不得在本任务随意抹掉。
- 有意识处理共享使用场景：普通会话和交付后调整不能因这里去重而丢失必要的同行/风格上下文与动作。不要假设每个调用点都有左侧旅行卡。
- 替换现有对生成面板右侧摘要的旧断言时，同时断言左卡内容仍在、右侧指定重复块消失；交付后调整原覆盖继续通过。

执行者自己决定：共享组件的呈现参数/样式及操作区布局；允许不改变其他调用场景的视觉。

不许碰：研究计划的来源与执行规则、API/SSE、已有状态语义、真实用户数据及无关页面；不改既有任务文档。基线 `/tmp/journeypilot-review-oCppsF/existing-tracked.patch`、`existing-status.txt` 和其 `frontend/` 下五个快照需保护。先核对当前文件，在原有改动上窄改；禁止 reset、stash、覆盖、暂存或提交已有改动。与本批卡片、动画任务共享 CSS、面板和测试，按顺序串行合并。

## 5 停下来报告的情况

若移除指定区域会造成不在左卡的受控身份信息丢失，或保持共享场景需要改公开合同，停止并报告。其余遵守 README 通用停止条件。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 生成工作区恰好不再呈现五处指定内容；左卡信息、计划正文、已识别要求及截图未标红内容完整保留。
2. 离线验证确认、取消、补充重开、提交失败保留输入/可重试；刷新恢复与手机窄屏仍可用。
3. 普通会话及交付后的调整门仍有需要的身份上下文和同等可用的操作。

### 6.2 必须运行的检查

先在单独终端启动 `cd frontend && PORT=5173 npm run dev -- --host 127.0.0.1 --strictPort`；端口占用则使用空闲 loopback 端口并同步 URL。使用拦截 API/外网并检查逃逸的离线 fixture：

- `cd frontend && npm run type-check`
- `cd frontend && npm run test -- src/features/travel/model/planApprovalGate.test.ts`
- `cd frontend && JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:5173 npx playwright test e2e/session-state.spec.ts --workers=1 --grep 'plan gate stays|cancel keeps|narrow plan gate|delivered trip refinement gate' --output=../output/polish/20261030-1012-gate-declutter/playwright`
- 必要时补足普通会话与失败重试的离线测试并记录命令；不得将 skipped 算作通过。

### 6.3 实屏证据（执行者提供）

合成数据的 2000×880 生成工作区待确认和 390×844 窄屏待确认截图，以及交付后调整的窄屏截图，存入 `output/polish/20261030-1012-gate-declutter/`；展示实际可用操作，勿含真实数据。

### 6.4 真人验收（用户操作）

1. 离线打开待确认旅行 → 五处红框内容已去除，其余计划、要求和操作都在，同行与风格仍在左卡。
2. 模拟补充、取消、确认及刷新恢复 → 功能正常；打开交付后调整，检查同行上下文与操作未丢失。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-30 11:23 · Workflow / pi

- 改动摘要：仅在生成工作区去除截图指定的五处内容；共享会话保留身份摘要和操作，失败保留输入及焦点。
- 改动文件：frontend/src/features/travel/components/planning/TripBriefPlanGate.tsx、frontend/src/app/session/{streamEvents,useSendMessage}.ts、frontend/e2e/session-state.spec.ts。
- 偏离方案及理由：无。此前实现代理两次连接中断，后续根据独立复审接手并继续修复。
- 实际运行的检查与结果：`cd frontend && npm run type-check` 通过；`npm run test -- src/app/session/sessionRuntime.test.ts src/features/travel/model/planApprovalGate.test.ts` 10 项通过；离线 Vite 及 API/外网拦截下，`JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:5173 npx playwright test e2e/session-state.spec.ts --workers=1` 51 项通过；修改证据采集后 `--grep 'handoff expands'` 1 项通过。
- 实屏证据：output/polish/20261030-1012-gate-declutter/desktop-2000-gate.png、phone-390-gate.png、bundle-adjustment-gate-1280.png。
- 遗留问题或需要指挥决定的事：研究计划的审批版本接口正在并行修复；整合后需再次验证，尚未进行真人验收。

## 8 指挥验收（指挥填写）

## 9 真人验收（指挥代录）
