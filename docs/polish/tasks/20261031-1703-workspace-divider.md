# 行程工作台：去掉旅行卡与进度标题之间的分隔线

- 编号：20261031-1703-workspace-divider
- 状态：待代码验收
- 创建：2026-10-31 17:03
- 执行前先读：[工作目录 README](../README.md)、`AGENTS.md`、`frontend/README.md`、`frontend/e2e/README.md`

## 1 用户反馈

用户截图（2026-10-31）：行程工作台左侧，「你的旅行」卡片下方、标题「等待确认旅行需求」上方，有一条横贯侧栏的细线。用户在截图上用红框圈出该线并标注「不需要这个条」。

截图内容：左侧栏顶部是「你的旅行」卡片（北京市 / 上海市 / 5 日 / 深圳市出发 / 2026-11-10 — 2026-11-14 / 2 位成人 / 经典均衡），卡片下方约 24px 处有一条 1px 分隔线，再往下是「等待确认旅行需求」和四个阶段。

## 2 现象与发生条件

行程工作台（`GenerationJourneyPanel`）在桌面视口显示，行程处于 `awaiting_input`（等待确认旅行需求）。旅行卡与进度区之间出现分隔线；无论门是否打开都存在。

## 3 根因

`.generation-progress` 同时设置了 `margin-top: 28px`、`padding-top: 24px` 和 `border-top: 1px solid var(--color-stroke)`（`frontend/src/index.css:3971-3975`）。该元素在 `GenerationJourneyPanel.tsx:224` 紧跟在旅行卡之后，所以 `border-top` 就是用户圈出的那条线。

## 4 方案

目标状态：旅行卡与「等待确认旅行需求」之间只保留自然留白，不再有贯穿侧栏的分隔线；卡片本身的边框、阴影和进度区的其余样式不变。

必须做：

- 去掉 `.generation-progress` 的 `border-top`。
- 保持视觉节奏，不要因为去掉线导致标题贴住卡片；用 `margin-top` 提供留白，去掉只服务于分隔线的 `padding-top`。
- 检查同侧栏没有其他重复分隔线（`.generation-run-actions`、`.generation-readonly-note` 等不需要新增边框）。

执行者自己决定：

- 具体留白数值（建议 20–28px）。
- 是否需要在窄屏断点同步调整。

不许碰：

- 旅行卡布局、进度阶段的状态逻辑、门/过程交接、其他侧栏文字。
- 不改动交通卡片任务正在修改的 CSS 区块。

## 5 停下来报告的情况

如果该线不是 `.generation-progress` 的 `border-top`，或去掉后出现滚动/布局回归，停止并记录实际元素。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. `.generation-progress` 不再有 `border-top`，标题与旅行卡之间仍有清晰留白。
2. 桌面 1440px 与 390px 视口都没有新的重叠、贴边或横向溢出。

### 6.2 必须运行的检查

- `cd frontend && npm run type-check && npm run test`

### 6.3 实屏证据（执行者提供）

在 `output/polish/20261031-1703-workspace-divider/` 保存桌面 1440×900 与 390×844 的行程工作台截图，需包含旅行卡与「等待确认旅行需求」之间的区域；使用本地服务、虚构会话。

### 6.4 真人验收（用户操作）

1. 打开行程工作台，查看「你的旅行」卡片下方 → 不再出现横贯侧栏的细线，标题与卡片之间仍有留白。
2. 缩小到手机宽度 → 同样没有分隔线或布局挤压。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-10-31 17:10 · ZCode / deepseek-v4.1-flash-1017

- 改动摘要：去掉 `.generation-progress` 的 `border-top` 和只服务于分隔线的 `padding-top`，保留 `margin-top: 28px` 作为旅行卡与进度标题之间的留白；未新增其他侧栏分隔线。
- 改动文件：`frontend/src/index.css`
- 偏离方案及理由：无
- 实际运行的检查与结果：`cd frontend && npm run type-check` 通过；`npm run test` 通过（19 个测试文件、161 项测试）。另执行任务 2 要求的离线 E2E（`planner-intake`、`multi-round-intake`，网络拦截）9 项通过，覆盖工作区与表单布局回归。浏览器实测 1440×900 与 390×844：`.generation-progress` 为 `border-top-width: 0px`、`padding-top: 0px`、`margin-top: 28px`，旅行卡底部到进度区顶部间距 28px，无横向溢出、无页面错误、无外部请求逃逸。
- 实屏证据：`output/polish/20261031-1703-workspace-divider/workspace-1440x900.png`（1440×900）、`workspace-390x844.png`（390×844）、`divider-check.json`。截图使用本地 Vite 8080、虚构行程与离线拦截数据，行程处于 `awaiting_input`。
- 遗留问题或需要指挥决定的事：运行中的后端未重启（本任务只改前端 CSS，Vite 热更新已生效）。

## 8 指挥验收（指挥填写）

## 9 真人验收（指挥代录）
