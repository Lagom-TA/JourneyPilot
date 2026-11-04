# B1 后端分层与依赖边界

`后端逻辑` · 前置 [S0](S0-setup.md) · [返回总览](../../REVIEW-PLAN.md) · 开工前阅读：[工作规则](../rules.md)

## 范围

- `backend/travel_agent/` 下全部子包
- `backend/main.py`、`backend/journeypilot.py`
- `docs/architecture/overview.md`

## 审查项

- [ ] **职责归属**：每个子包的职责与 `overview.md` 中的“后端职责归属”一一对应。重点看几组容易重叠的地方：`planning/delivery` 与 `api/presenters` 的投影、`conversation` 与 `memory` 的会话上下文、`integrations` 与 `tools` 的外部调用、`runtime` 与 `planning` 顶层的运行控制。
- [ ] **依赖方向**：先导出模块依赖图，再核对三件事：`api → 业务 → storage / integrations` 是否单向；`integrations` 和 `utils` 是否反向依赖业务层；有无循环依赖。
- [ ] **体量热点**：按目录和文件统计行数，找出过大的模块（重点看 `planning/`、`storage/`），判断是否需要按职责拆分；同时找出过碎、可以合并的小文件。
- [ ] **命名一致**：目录和文件的命名风格统一（如 `contracts` 后缀、`presentation` 和 `presenters`、`node` 和 `agent`），同一个概念全仓库只用一个名字。
- [ ] **死代码与孤岛**：没有任何引用的文件、只被测试引用的文件、与主流程脱节的 `backend/scripts/`。
- [ ] **API 层**：`api/routes/` 只负责参数处理、错误映射和对外投影，不承载业务流程；`routes/` 与 `schemas/` 按资源对齐。
- [ ] **启动与关闭**：`bootstrap/` 中组件装配、就绪检查和关闭的顺序，以及缺少可选依赖时的行为。

## 影响下游

- 移动或重命名模块 → [B2](B2-planning-intake.md)、[B3](B3-planning-delivery.md)、[B4](B4-runtime-streaming.md)、[B5](B5-tools-models-data.md)、[B6](B6-data-config-release.md)，以及 [T3](T3-docs-showcase.md)（`overview.md`）
- 改动 API 路由或 schema → [B4](B4-runtime-streaming.md)、[F1](F1-frontend-foundation.md)

## 收到的提醒

- （暂无）

## 问题与修复

- （暂无）
