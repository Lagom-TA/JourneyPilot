# 标题：整理需求步骤不再显示重复的高亮状态说明

- 编号：20261030-1012-progress-focus
- 状态：待代码验收
- 创建：2026-10-30 10:12
- 执行前先读：[工作目录 README](../README.md)、`AGENTS.md`、`docs/invariants.md`、`frontend/README.md`、`frontend/e2e/README.md`。

## 1 用户反馈

- 原话：「2 左侧整理旅行需求步骤中移除高亮重复说明」；「截图其余没有标红内容不能随意删除。」
- 反馈图：`output/polish/20261030-1012-progress-focus/feedback-1.png`。左侧第一步静态描述之下，红框标出橙色的“正在根据旅行需求查询交通、住宿和沿途路线”。
- 只使用离线/模拟测试，不调用真实付费模型、不修改真实用户数据。本批文档完成后紧接着交付执行，不暂存、不提交。

## 2 现象与发生条件

生成工作区等待确认旅行需求时，第一步骤仍为活动态，出现高亮文字；截图为桌面宽屏，浏览器不详。该文案还可能在整理阶段流式运行时出现，需同时检查，而不能假定确认门是唯一入口。

## 3 根因

`frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx:62-70,154-167` 在活动步骤渲染静态描述后，又渲染 `tripSummaryCard.currentFocus`；确认门期间强制第一步为 active。`backend/travel_agent/planning/requirements/summary.py:55-125` 的 brief 阶段该 focus 是固定查询描述，等待确认时尚未开始调研，所以既重复又可能误导。源数据不只供此处消费，问题落在这一展示位置。

## 4 方案

目标状态：左侧“整理旅行需求”保留步骤名与“目的地、时间、同行人与旅行偏好”等原有说明，不再出现截图中额外高亮说明。

必须做：

- 对整理需求这一步定向移除额外的 `currentFocus` 高亮，覆盖进行中与待确认；保持其他步骤标题、描述、状态图标及整体状态语义。不要连同其他阶段可能有用的状态说明一并删除。
- 不通过修改服务端数据或伪造调研状态解决；验证待确认时不会提前说正在查询。除红框指定项外保留原信息。

执行者自己决定：渲染条件与无用样式清理方式。

不许碰：后端摘要合同、业务规则、其他页面及真实用户数据；不改既有任务文档。基线 `/tmp/journeypilot-review-oCppsF/existing-tracked.patch`、`existing-status.txt` 和同目录 `frontend/` 中五个修改文件快照必须保留。先核对差异，在现有修改上窄改，不 reset、stash、覆盖、暂存或提交这些已有改动；与本批其他任务共享前端文件时串行处理。

## 5 停下来报告的情况

如果核实发现第一步高亮存在独立且无法在其他位置保留的关键信息，或必须修改后端共享合同，停止并报告。其余遵守 README 通用停止条件。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 整理中和等待确认两种状态下，第一步无额外高亮；第一步既有描述和其他三步标题/说明仍在。
2. 其他阶段有有效 focus 时仍按实际状态呈现，确认前不冒称已查询；失败/取消状态不受影响。

### 6.2 必须运行的检查

使用本地 mock 会话，先运行 `cd frontend && PORT=5173 npm run dev -- --host 127.0.0.1 --strictPort`；端口占用时换空闲 loopback 端口并同步下方 URL。执行：

- `cd frontend && npm run type-check`
- `cd frontend && JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:5173 npx playwright test e2e/session-state.spec.ts --workers=1 --grep 'plan gate stays|cancel keeps' --output=../output/polish/20261030-1012-progress-focus/playwright`
- 在离线测试中补充整理中、待确认、其他阶段有效 focus 的对照断言，并记录实际命令；不得把 skipped 当作通过。fixture 必须拦截 API 和外网并检查网络逃逸。

### 6.3 实屏证据（执行者提供）

用合成数据截图 `output/polish/20261030-1012-progress-focus/`：桌面等待确认、整理中的左侧四步，至少一张能看清各步原有文字。

### 6.4 真人验收（用户操作）

1. 用离线夹具进入整理中及待确认状态 → 第一条的名称、普通描述仍在，红框高亮说明消失。
2. 模拟调研开始 → 其他进度步骤和真实状态仍可见。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-30 11:23 · Workflow / pi

- 改动摘要：只移除整理需求阶段的额外高亮，其他活动阶段的 currentFocus 仍保留。
- 改动文件：frontend/src/features/travel/components/workspace/GenerationJourneyPanel.tsx、frontend/src/index.css、frontend/e2e/session-state.spec.ts。
- 偏离方案及理由：无。此前实现代理两次连接中断，后续根据独立复审接手并继续修复。
- 实际运行的检查与结果：`cd frontend && npm run type-check` 通过；`npm run test -- src/app/session/sessionRuntime.test.ts src/features/travel/model/planApprovalGate.test.ts` 10 项通过；离线 Vite 及 API/外网拦截下，`JP_SESSION_STATE_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:5173 npx playwright test e2e/session-state.spec.ts --workers=1` 51 项通过；修改证据采集后 `--grep 'handoff expands'` 1 项通过。
- 实屏证据：output/polish/20261030-1012-progress-focus/desktop-2000-requirements-active.png、desktop-2000-gate-four-steps.png。
- 遗留问题或需要指挥决定的事：研究计划的审批版本接口正在并行修复；整合后需再次验证，尚未进行真人验收。

## 8 指挥验收（指挥填写）

## 9 真人验收（指挥代录）
