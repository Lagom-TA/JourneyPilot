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

- [x] 来自 S0：该用例原先调用 `router.guard_run_budget`，基线提交已让 router 改用台账 `reserve_model` 预留预算，S0 已把用例改为 `budget.guard_run_budget`。请复核：这条用例现在不再覆盖 router 的预算预留路径。

## 问题与修复

- （暂无）
