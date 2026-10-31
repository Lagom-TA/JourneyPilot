# 标题：旅行信息卡将同行和风格融入行程摘要

- 编号：20261030-1012-trip-card-layout
- 状态：待代码验收
- 创建：2026-10-30 10:12
- 执行前先读：[工作目录 README](../README.md)、`AGENTS.md`、`docs/invariants.md`、`frontend/README.md`、`frontend/e2e/README.md`。

## 1 用户反馈

- 原话：「1 左上旅行信息卡重排，同行人数/旅行风格与目的地日期布局融合」；「截图其余没有标红内容不能随意删除。」
- 反馈图：`output/polish/20261030-1012-trip-card-layout/feedback-1.png`。红框覆盖左上旅行卡，当前目的地、天数和日期在上，同行与风格另起一块。
- 用户要求仅离线/模拟测试，不调用真实付费模型、不修改真实用户数据。本批文档完成后紧接着交付执行，不提交或暂存。

## 2 现象与发生条件

正式旅行生成工作区、需求待确认时出现；截图桌面宽屏，浏览器及真实数据来源未知。旅行卡在其他生成状态也复用，需覆盖手机宽度与长目的地名。数据应使用本地合成旅行身份。

## 3 根因

`frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx:123-151` 依次输出站序/天数、出发地/日期，随后单独输出同行列表与风格标签；`frontend/src/index.css:3998-4127` 给同行块单独的边界和间距，视觉上与主体割裂。内容来自受控旅行身份，不是 API 或旅行规则问题。

## 4 方案

目标状态：同行、风格与目的地、日期在同一信息层级和节奏中自然融合；仍能一眼读出目的地顺序与旅行天数。

必须做：

- 仅重排该卡的结构和样式，保留出发地、全部目的地及顺序、日期、天数、成人/儿童、长辈同行、无障碍需求、主要与次要风格；没有的可选值不虚构。保留标题焦点交接和停止按钮功能。
- 桌面、窄屏、长地名、多目的地和长同行条件下不截断重要信息、不横向溢出；维持可读性、语义和键盘可达性。不能为精简删除未标红内容。
- 调整针对性测试时，保留对身份信息的正向断言，不以删断言代替验证。

执行者自己决定：布局、间距、图标及自动换行方式；不强制复制截图中的旧版排版。

不许碰：旅行身份含义、规划规则、API/SSE、真实用户数据及与此无关页面；不改既有任务文档。工作区已有未提交内容：基线在 `/tmp/journeypilot-review-oCppsF/existing-tracked.patch` 与 `existing-status.txt`，五个修改文件完整快照在 `/tmp/journeypilot-review-oCppsF/frontend/`。先核对当前差异，在其上窄改，保留其中终态 composer、恢复提示等；禁止 reset、stash、覆盖、暂存或提交这些已有改动。`GenerationJourneyPanel.tsx`、`index.css`、`session-state.spec.ts` 与本批其他任务重叠，串行协作，不用旧快照覆盖当前文件。

## 5 停下来报告的情况

需要改变受控身份字段或计划规则才能呈现，或发现截图卡片并非来自上述组件时，停止并报告。其余遵守 README 通用停止条件。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 旅行卡将同行和风格融入目的地/日期布局，所有实际身份信息和站序保留；停止与焦点交接仍有效。
2. 桌面、390px 窄屏及多站长名/儿童、长辈、无障碍/多风格夹具完整可读，无重叠或横溢；其他状态与既有 composer 不回退。

### 6.2 必须运行的检查

先在单独终端运行离线前端：`cd frontend && PORT=5173 npm run dev -- --host 127.0.0.1 --strictPort`。若端口被占用，先确认并换空闲 loopback 端口，不连接现有真实后端。以下命令从仓库根目录运行；Playwright fixture 拦截 API/外网并检查逃逸。

- `cd frontend && npm run type-check`
- `cd frontend && JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:5173 npx playwright test e2e/session-state.spec.ts --workers=1 --grep 'plan gate stays|narrow plan gate' --output=../output/polish/20261030-1012-trip-card-layout/playwright`
- 在上述离线用例中补充并运行多站长名及复杂同行/风格覆盖；如使用不同文件，将其实际命令记在第 7 节。不得将 skipped 计为通过。

### 6.3 实屏证据（执行者提供）

离线夹具截图存入 `output/polish/20261030-1012-trip-card-layout/`：桌面 2000×880 与 390×844，另提供多站长名及儿童/长辈/无障碍/多风格状态，能看清整张卡和相邻进度。不可含真实个人信息。

### 6.4 真人验收（用户操作）

1. 用离线夹具打开生成工作区确认面板 → 左卡同行、风格和目的地日期连贯，数据完整。
2. 缩窄到手机宽度并使用多站长名与复杂同行夹具 → 信息完整、无横向滚动或遮挡。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-30 11:23 · Workflow / pi

- 改动摘要：旅行卡将出发与日期、同行和风格归入统一信息层级，保留多站顺序与特殊同行条件。
- 改动文件：frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx、frontend/src/index.css、frontend/e2e/session-state.spec.ts。
- 偏离方案及理由：无。此前实现代理两次连接中断，后续根据独立复审接手并继续修复。
- 实际运行的检查与结果：`cd frontend && npm run type-check` 通过；`npm run test -- src/app/session/sessionRuntime.test.ts src/features/travel/model/planApprovalGate.test.ts` 10 项通过；离线 Vite 及 API/外网拦截下，`JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:5173 npx playwright test e2e/session-state.spec.ts --workers=1` 51 项通过；修改证据采集后 `--grep 'handoff expands'` 1 项通过。
- 实屏证据：output/polish/20261030-1012-trip-card-layout/desktop-2000-trip-card-long.png、phone-390-trip-card-long.png。
- 遗留问题或需要指挥决定的事：研究计划的审批版本接口正在并行修复；整合后需再次验证，尚未进行真人验收。

## 8 指挥验收（指挥填写）

## 9 真人验收（指挥代录）
