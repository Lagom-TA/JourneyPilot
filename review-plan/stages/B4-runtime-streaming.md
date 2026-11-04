# B4 运行控制、会话与流式

`后端逻辑` · 前置 [B1](B1-backend-layers.md) · [返回总览](../../REVIEW-PLAN.md) · 开工前阅读：[工作规则](../rules.md)

## 范围

- `backend/travel_agent/runtime/`
- `backend/travel_agent/conversation/`：`chat/`、快速回答图、压缩、历史、标题
- `backend/travel_agent/api/`：`sse*`、`routes/chat.py`、`routes/sessions.py`、`routes/trip_runs/`（运行、事件、控制）
- `backend/travel_agent/memory/chat_session.py`
- `docs/invariants.md` 中“长任务与控制”“流与会话”“资源边界”三章；`docs/adr/` 中与运行、流式、预算相关的 ADR

## 审查项

- [ ] **运行生命周期**：创建 → 取得租约 → 执行 → 终态；每个请求恰好产生一个终态事件。
- [ ] **控制与恢复**：停止、取消、中断、继续、服务重启后不自动继续花费、“正在停止”这个中间态、重复取消。
- [ ] **预算与时限**：调用前判断、判断和记账在同一步完成、超限后用户看到什么。
- [ ] **事件清单**：列出全部流式事件，每一类都有明确的生产者和前端消费者；找出没人消费或没人生产的事件。
- [ ] **断线与多端**：断线后按事件游标恢复；同一会话在多个标签页同时打开。
- [ ] **快速回答链路**：与完整规划共享哪些部分，以及它的错误处理。
- [ ] **会话管理**：压缩、会话标题、历史分页、一轮对话总是完整返回。
- [ ] **保证落地**：`invariants.md` 中相关的每条保证都有代码位置和测试与之对应。

## 影响下游

- 改动事件种类、字段或终态语义 → [F1](F1-frontend-foundation.md)、[F3](F3-generation-workspace.md)
- 改动停止、继续、只读的规则 → [F3](F3-generation-workspace.md)、[F4](F4-delivery-workspace.md)、[T1](T1-ui-copy.md)
- 改动保证或决策 → [T3](T3-docs-showcase.md)

## 收到的提醒

- [ ] 来自 B3-02、B3-06：研究重试沿用时限快照；含未安排事项的 Bundle 可提交，但 `is_completed` 为 false → 请复核重试、终态和恢复语义。
- [ ] 来自 B2-01：门控操作无需携带路由即可恢复原规划 → 请复核门控恢复、错误状态和流式事件。
- [ ] 来自 B2-03：交付后追问用会话历史的 `task_type` 标识并分页读取 → 请复核刷新、历史和连续提问的边界。
- [ ] 来自 B2-04：移除了四个无读取方的规划状态字段 → 请复核状态快照与压缩事件的消费者。
- [ ] 来自 B1-03：MCP 会话由创建任务关闭，后台任务先于用量刷写停止 → 请复核运行取消与关闭顺序。
- [ ] 来自 B1-09：对话执行侧生成 Run 状态摘要，仓储接收摘要而非规划状态 → 请复核流式状态和终态摘要。
- [x] 来自 S0：该用例原先调用 `router.guard_run_budget`，基线提交已让 router 改用台账 `reserve_model` 预留预算，S0 已把用例改为 `budget.guard_run_budget`。请复核：这条用例现在不再覆盖 router 的预算预留路径。

## 问题与修复

- （暂无）
