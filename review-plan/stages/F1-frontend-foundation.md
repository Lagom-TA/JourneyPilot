# F1 前端结构、状态与样式体系

`前端页面` · 采集与修复一侧完成 · 前置 [S0](S0-setup.md)、[B4](B4-runtime-streaming.md) · [返回总览](../../REVIEW-PLAN.md) · 开工前阅读：[工作规则](../rules.md)

## 范围

- `frontend/src/app/`：外壳、布局、导航、状态、会话
- `frontend/src/features/*/`：分层为 `api`、`model`、`types`、`components`、`pages`、`hooks`
- `frontend/src/components/ui/`、`frontend/src/lib/`、`frontend/src/hooks/`
- `frontend/src/index.css`、`frontend/src/assets/fonts/`
- `frontend/tailwind.config.ts`、`frontend/vite.config.ts`、`frontend/package.json`

## 审查项

- [x] **模块边界**：业务组件在页面层组合；聊天成本标签归回 `chat`，类型跨 feature 引用契约，共享 UI 无 feature 依赖。
- [x] **全局状态**：应用 reducer 组合聊天与旅行切片；前进、后退、刷新和会话直接链接按地址同步。
- [x] **会话与流式**：发送、停止、恢复和队列由 `app/session/` 分担，不同会话各自维护流；事件与 [B4 清单](../b4-events.md)对齐。
- [x] **样式组织**：基础样式保留在 `index.css`，首页、外壳、行程列表和工作台按原顺序分文件；复杂布局用语义类，简单布局用 Tailwind。
- [x] **设计 token**：集中颜色、圆角、阴影、动效和全局层级；层级表见 [前端说明](../../frontend/README.md#样式与视口)。
- [x] **断点体系**：JS 与 Tailwind 读取同一配置；CSS 采用相同边界，局部细分断点单独记录。
- [x] **字体**：Inter 与 Noto Sans SC 覆盖正文；标题 14 字子集缺字时回退完整 Noto Serif SC；桌面与手机截图已检查混排。
- [x] **主题与打印**：只保留一套主题；保留已有 PDF 导出，不新增浏览器打印样式，见 D-03。
- [x] **大组件与重复实现**：目的地输入、旅行规划和交付工作台分别为最大组件；按场景交 F2、F4 判断，不按行数机械拆分；弹层共用 UI 与关闭逻辑。
- [x] **依赖**：运行时依赖均有引用，锁文件固定安装结果；React、Markdown、地图和动效按使用拆包，默认输出 `backend/static`。

## 影响下游

- 改动 token、全局样式或共享组件 → [F2](F2-home-input.md)、[F3](F3-generation-workspace.md)、[F4](F4-delivery-workspace.md)、[F5](F5-trips-preferences.md)、[F6](F6-motion-a11y.md)
- 改动状态或会话逻辑 → [F3](F3-generation-workspace.md)、[F4](F4-delivery-workspace.md)

## 收到的提醒

- [x] 来自 B4-08、B4-11、B4-13：已核对快速回答重放、中断状态及未使用事件类型。

## 问题与修复

- [x] F1-01 快速回答重放复用消息 ID 时会出现重复消息 → 重映射前移除旧消息。（提交 38bd919）
- [x] F1-02 中断帧按普通错误展示且遗漏费用汇总 → 按状态展示中断并保留汇总。（提交 38bd919）
- [x] F1-03 同视图内浏览器前进或后退后，下一次视图切换可能不更新地址 → 只在视图确实变化时跳过地址写入。（提交 38bd919）
- [x] F1-04 会话不在列表时直接链接被忽略 → 按链接读取会话并显示读取失败。（提交 38bd919）
- [x] F1-05 全局样式过大，颜色、圆角、阴影、动效和层级散落 → 分区拆分样式并统一具名 token。（提交 38bd919、286d9e8）
- [x] F1-06 JS 与 CSS 的断点边缘不一致 → JS、Tailwind 共用断点配置，CSS 使用相同边界。（提交 38bd919）
- [x] F1-07 不同会话并行生成时流归属互相覆盖，停止可能作用于另一会话 → 分会话追踪流、快照和停止操作。（提交 38bd919）
- [x] F1-08 主题与浏览器打印范围未确定 → 确认单一主题，保留 PDF 导出，不增加浏览器打印样式。（提交 38bd919）
- [x] F1-09 聊天成本标签反向依赖旅行模型，前端声明了无生产者事件 → 标签移入 `chat` 并移除无用事件类型。（提交 38bd919）
- [x] F1-10 快速切换会话时退出动画可能停留在旧对话 → 按会话世代重建对话组件。（提交 38bd919）
- [x] F1-11 流处理器与状态共享可变消息对象，快速事件可能覆盖用户消息 → 状态持有独立消息快照。（提交 38bd919）
- [x] F1-12 〔综合验收〕地图加载失败的离线夹具只引入 `index.css`，样式拆分后丢失布局与工作台样式 → 夹具补引 `layout.css`、`workspace.css`，两项离线地图用例恢复通过。（提交 3bd2b42）

验证：Node 22 隔离安装后类型检查、Lint、198 个单元测试和构建通过；离线浏览器验证直接链接、前进后退、宽窄屏、地图、并行生成和停止归属。运行时依赖安全告警为 0，开发工具告警已在 B6 跟进。
