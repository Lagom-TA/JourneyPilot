# B4 流式事件清单

`chat-stream` 投影见 `backend/travel_agent/api/sse_projection.py`。下表的前端消费者分别是 `frontend/src/app/session/streamEvents.ts`（会话）和 `frontend/src/features/chat/model/streamPresentation.ts`（过程）。

| SSE 事件 | 后端生产位置 | 前端消费者 |
|---|---|---|
| `chat_start` | `chat/execution.py`、`chat/preparation.py` | 会话：绑定消息、会话与 Run |
| `route_confirmation` | `chat/preparation.py` | 会话：请求用户确认分流 |
| `thinking`、`agent_progress` | `chat/progress_events.py` | 过程：思考步骤与角色进度 |
| `work_explanation` | `chat/progress_events.py` | 过程：工作说明 |
| `tool_start`、`tool_result` | `chat/tool_events.py` | 过程：工具开始与结果 |
| `chat_chunk` | `chat/text_events.py`、`chat/progress_events.py`、`chat/preparation.py` | 过程：助手正文 |
| `context_report`、`context_compaction` | `chat/progress_events.py` | 过程：上下文报告和整理快照 |
| `usage_update` | `chat/accounting.py` | 过程：用量统计 |
| `trip_identity_updated`、`trip_summary_card` | `chat/progress_events.py` | 会话：基础信息与摘要卡 |
| `understanding_questions`、`approval_gate_raised` | `chat/execution.py`、`chat/preparation.py` | 会话：理解、研究及方案门 |
| `chat_complete` | `chat/completion.py`、`chat/preparation.py` | 会话：快速回答或等待输入的请求结束 |
| `delivery_ready`、`run_terminal` | `chat/completion.py`、`chat/failures.py` | 会话的 `deliveryProtocol`：按持久序号确认交付 |
| `run_cancelled`、`run_failed`、`error` | `chat/failures.py` | 会话：停止、失败和错误详情 |

`agent_thinking` 只存在于后端丢弃分支，没有当前生产者，前端也不声明该事件。`trace_event` 由 `chat/presentation.py` 产生并保存为 `trace.event`，SSE 投影不下发；`trace_summary` 没有当前生产者。工作流队列中的 `state_snapshot` 由执行层写入 Run 状态摘要，不直接发送给浏览器；`context_compaction` 的持久快照由整理服务写入，实时事件和历史均有消费者。

一次运行段的主要结束帧是 `chat_complete`、`run_terminal`、`run_cancelled`、`run_failed` 或中断时的 `error`。深度交付先发 `delivery_ready` 再发 `run_terminal`；失败可以在 `run_failed` 后附带 `error` 详情。`error` 帧携带经校验的 `run_status`，前端据此区分中断和普通失败。等待输入时的 `chat_complete` 只结束本次请求，Run 仍为 `awaiting_input`。断线时无法保证客户端收到结束帧，以持久状态为准。

## 断线和多标签页

浏览器断开会让服务端停止当前执行并收敛为中断；显式继续才会再次发起调用。`GET /api/trip-runs/{run_id}/events` 使用 `after_sequence` 提供有界持久事件窗口；`useDeliveryEventRecovery` 按游标轮询交付和状态，窗口过期时读取当前状态与 Bundle。另一标签页能恢复门、状态与已保存的交付，实时 token 和过程增量不会按 SSE 游标补播。快速回答完成后的重复请求从会话记录重放正文。
