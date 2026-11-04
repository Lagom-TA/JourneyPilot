# F1 前端结构、状态与样式体系

`前端页面` · 采集与修复一侧完成 · 前置 [S0](S0-setup.md)、[B4](B4-runtime-streaming.md) · [返回总览](../../REVIEW-PLAN.md) · 开工前阅读：[工作规则](../rules.md)

## 范围

- `frontend/src/app/`：外壳、布局、导航、状态、会话
- `frontend/src/features/*/`：分层为 `api`、`model`、`types`、`components`、`pages`、`hooks`
- `frontend/src/components/ui/`、`frontend/src/lib/`、`frontend/src/hooks/`
- `frontend/src/index.css`、`frontend/src/assets/fonts/`
- `frontend/tailwind.config.ts`、`frontend/vite.config.ts`、`frontend/package.json`

## 审查项

- [ ] **模块边界**：`chat` 和 `travel` 的职责划分；跨 feature 引用的方向；各 feature 内部分层方式一致。
- [ ] **全局状态**：状态切片的划分；视图切换与地址栏同步（前进、后退、刷新、直接打开带参数的链接）。
- [ ] **会话与流式**：发送、流事件处理、停止、恢复、待发送队列在 `app/session/` 中的职责划分；与 [B4](B4-runtime-streaming.md) 的事件清单逐项对齐。
- [ ] **样式组织**：`index.css` 按区域分段还是拆成多个文件；语义类和 Tailwind 工具类的分工；硬编码的颜色、尺寸与 token 的使用。
- [ ] **设计 token**：颜色、圆角、阴影、时长、缓动全部经由 token；建立一张 z-index 层级表。
- [ ] **断点体系**：JS 断点、CSS 媒体查询、Tailwind 断点三处是不是同一套。
- [ ] **字体**：加载方式、子集字体覆盖的字符范围和回退字体、中英文混排时的基线。
- [ ] **主题与打印**：确定是否提供暗色模式和打印样式，按结论执行或记入[待决事项](../decisions.md)。
- [ ] **大组件与重复实现**：按行数找出最大的组件和样式块，判断是否需要拆分；找出重复实现的弹层、下拉、提示；确认 `components/ui/` 不含业务逻辑。
- [ ] **依赖**：有没有未使用的依赖、版本是否需要固定、构建分包是否合理、构建产物输出到哪里。

## 影响下游

- 改动 token、全局样式或共享组件 → [F2](F2-home-input.md)、[F3](F3-generation-workspace.md)、[F4](F4-delivery-workspace.md)、[F5](F5-trips-preferences.md)、[F6](F6-motion-a11y.md)
- 改动状态或会话逻辑 → [F3](F3-generation-workspace.md)、[F4](F4-delivery-workspace.md)

## 收到的提醒

- （暂无）

## 问题与修复

- （暂无）
