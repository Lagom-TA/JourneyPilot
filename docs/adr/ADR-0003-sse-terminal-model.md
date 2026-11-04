# ADR-0003：Run 状态只转移一次，终态帧不重复发布

状态：已采纳
影响：`runtime/events.py`、`conversation/chat/lifecycle.py`、`conversation/chat/completion.py`、
`conversation/chat/failures.py`、`trip_runs`、前端 `frontend/src/app/session/streamEvents.ts`

## 决定

一次聊天请求的 Run 状态只发生一次终态转移。终态 SSE 帧包括 `chat_complete`、
`run_terminal`、`run_cancelled`、`run_failed` 与 `error`；deep 路径先发 `delivery_ready`，
再发 `run_terminal`。同一终态帧不重复发布。失败收口时可以在 `run_failed` 或
`run_terminal` 之后追加 `error` 帧；`error` 携带失败详情，不构成第二次状态转移。

## 为什么

浏览器会断流或休眠；已经断开的连接无法保证收到终态帧。活跃连接按终态帧结束请求，
断线后依据持久状态、事件窗口和已保存内容恢复。运行段只做一次状态收口，避免客户端
先渲染成功再渲染失败。

## 替代方案与为什么没选

- **靠连接关闭表示结束**：区分不了「做完了」和「网断了」，而这两者的下一步动作相反。
- **允许补发终态**：那要求客户端做去重，而去重规则会散落到每一个消费点。

## 后果

- 生产者侧的退出收敛点是 `conversation/chat/lifecycle.py` 的 `cleanup_stream_exit`；
  `delivery_ready_emitted` 与 `run_terminal_emitted` 防止重复发布终态帧。
- `EventBuffer` 的 critical 队列满时生产者等待；消费者 stall 后结束传输，以持久状态恢复（见 [ADR-0006](ADR-0006-resource-budgets-and-isolation.md)）。
