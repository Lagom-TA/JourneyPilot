# 不变量

本文记录当前仍然成立的架构约定，供设计与评审使用。每条约定说明什么必须成立、由哪段代码负责，以及覆盖它的测试。没有对应测试的条目不写 Tests 行。代码注释不引用本文编号，也不引用 ADR 编号。

设计理由见 [`adr/`](adr/)。

---

## 身份与持久化

### INV-ID-001：身份是常量，客户端不声明所有者
约定：所有用户数据归固定本地身份 `local`；接口从服务端上下文解析归属，不读请求体里的 user。
Owner: `backend/travel_agent/runtime/local_identity.py`（`LOCAL_USER_ID`）、迁移 `backend/migrations/versions/0003_local_identity.py`
Storage: 所有带 `user_id` 的表。
Enforced by: 迁移把历史行归一到 `local`；API 从服务端解析归属。
ADR: [ADR-0001](adr/ADR-0001-local-single-profile.md)
Tests:
- `backend/tests/db/test_local_identity_migration.py`
- `backend/tests/api/test_local_identity_api.py`

### INV-DB-001：API 进程不执行 DDL
约定：API 进程不建表、不改列、不删数据；结构变更只由迁移命令执行。
Owner: `backend/travel_agent/storage/maintenance/migrate.py`（唯一 DDL 执行者）、`backend/travel_agent/storage/database.py`
Storage: `alembic_version` 与结构指纹存档 `backend/migrations/fingerprints/*.json`。
Enforced by: 启动只做只读合同校验；容器入口迁移失败即不启动 API。
ADR: [ADR-0002](adr/ADR-0002-versioned-migrations.md)
Tests:
- `backend/tests/db/test_api_has_no_ddl.py`
- `backend/tests/db/test_schema_report.py`
- `backend/tests/db/test_checkpoint_schema.py`

### INV-DB-002：结构指纹与 revision 必须同时匹配
约定：数据库的实际结构与已知 revision 的指纹必须同时匹配；不匹配时拒绝服务，不把数据库标记成最新版本。
Owner: `backend/travel_agent/storage/maintenance/fingerprint.py`、`backend/travel_agent/storage/maintenance/report.py`
Storage: `backend/migrations/fingerprints/<revision>.json`。
Enforced by: readiness 的 `database_schema` 一项负责阻断。
Tests:
- `backend/tests/db/test_fingerprint.py`
- `backend/tests/db/test_migration_gates.py`

### INV-BACKUP-001：备份必须能被校验出损坏
约定：备份以 manifest 记录大小与 SHA-256，校验时逐文件比对；`pg_dump` 的退出码不是通过依据。
Owner: `backend/travel_agent/storage/maintenance/backup.py`
Storage: 备份目录里的 `manifest.json`。
Tests:
- `backend/tests/db/test_backup.py::test_verify_catches_a_truncated_dump`
- `backend/tests/db/test_backup.py::test_verify_catches_a_tampered_dump_of_the_same_size`
- `backend/tests/db/test_restore.py::test_corrupted_backup_is_refused_and_current_database_untouched`

### INV-BACKUP-002：备份里的密钥只留「有没有」
约定：备份与 `config show` 共用一套脱敏规则；判据是字段名而不是值的样子，输出只有 `<set>` / `<unset>`。
Owner: `backend/travel_agent/config/redaction.py`
ADR: [ADR-0008](adr/ADR-0008-config-single-source.md)
Tests:
- `backend/tests/db/test_backup.py::test_redaction_keeps_structure_and_drops_secrets`
- `backend/tests/config/test_config_contract.py::test_secrets_never_survive_the_effective_report`

---

## 长任务与控制

### INV-RUN-001：每个 running Run 都有有效租约
约定：运行中的 Run 必须有未过期的执行租约；心跳周期显著小于租约长度；连续写失败达到阈值后停止发起新的外部调用。
Owner: `backend/travel_agent/runtime/run_lease.py`、`backend/travel_agent/storage/run_execution_store.py`
Storage: `trip_run_executions`（executor / lease / heartbeat）。
ADR: [ADR-0005](adr/ADR-0005-restart-does-not-resume-spending.md)
Tests:
- `backend/tests/db/test_run_execution_lease.py`
- `backend/tests/runtime/test_run_execution_contract.py`

### INV-RUN-004：同一个 Run 不会有两个执行器
约定：只能接管无主的执行行（租约已释放或已过期），不按 `executor_id` 匹配；租约在工作流真正停下之后才交还；失去租约时只停止自己那条流的 handle，registry 的注销按 handle 身份进行。
Owner: `backend/travel_agent/storage/run_execution_store.py` 的 `claim`、`backend/travel_agent/runtime/run_lease.py`、`backend/travel_agent/conversation/chat/lifecycle.py`
Storage: `trip_run_executions.lease_token` / `lease_expires_at`。
Tests:
- `backend/tests/db/test_run_execution_lease.py::test_the_same_executor_cannot_claim_its_own_live_lease`
- `backend/tests/db/test_run_execution_lease.py::test_a_released_lease_can_be_reclaimed_by_the_same_executor`
- `backend/tests/runtime/test_run_execution_contract.py::test_unregister_only_removes_its_own_handle`
- `backend/tests/runtime/test_run_execution_contract.py::test_a_superseded_lease_keeper_does_not_evict_the_active_one`

### INV-RUN-005：分窗表覆盖图上每一个 worker
约定：分窗表必须恰好覆盖 dispatcher 的扇出目标，每个 worker 恰好属于 research 或 composition 一个窗口；漏一个会让它落进默认 research 档。
Owner: `backend/travel_agent/planning/execution.py` 的 `_DEADLINE_BLOCKED_WORKER_NODES` / `_RESEARCH_WORKER_NODES` / `_COMPOSITION_WORKER_NODES`、`backend/travel_agent/planning/nodes.py` 的 `WORKER_NODES`
Tests:
- `backend/tests/runtime/test_run_execution_contract.py::test_the_node_window_table_covers_every_worker_the_graph_fans_out_to`

### INV-RUN-002：孤儿 Run 不会永久显示 running
约定：失去执行器的 Run 在启动扫描时收敛；之后周期复扫，避免租约剩余时间让第一轮扫描跳过它。
Owner: `backend/travel_agent/runtime/run_recovery.py`
Storage: `trip_runs.status` 与 `trip_run_executions`。
ADR: [ADR-0005](adr/ADR-0005-restart-does-not-resume-spending.md)
Tests:
- `backend/tests/db/test_run_recovery.py`

### INV-RUN-003：重启后不自动继续花费
约定：恢复只改状态，不自动发起模型调用；恢复的 Run 从 `run_llm_calls` 台账读回已花量，而不是拿满额预算。
Owner: `backend/travel_agent/runtime/run_recovery.py`、`backend/travel_agent/runtime/budget.py` 的 `seed_run_budget`
Storage: `trip_runs.status` = interrupted / resume_available；`run_llm_calls`。
ADR: [ADR-0005](adr/ADR-0005-restart-does-not-resume-spending.md)
Tests:
- `backend/tests/runtime/test_run_budget.py::test_a_resumed_run_reads_its_spend_back_from_the_ledger`
- `backend/tests/runtime/test_run_budget.py::test_an_unreadable_ledger_starts_at_zero_instead_of_blocking`

### INV-CMD-001：cancel/supplement 不依赖发请求命中的那个进程
约定：命令的最终事实在 `trip_run_commands`；先落库再通知；执行器在协作边界轮询并幂等消费。
Owner: `backend/travel_agent/runtime/run_commands.py`、`backend/travel_agent/runtime/cancellation.py` 的 `RunControlRegistry`
Storage: `trip_run_commands`（最终事实）；registry 只是唤醒通道。
ADR: [ADR-0004](adr/ADR-0004-durable-local-jobs.md)
Tests:
- `backend/tests/db/test_run_control_api.py::test_a_real_executor_picks_the_command_up_from_the_table`
- `backend/tests/db/test_run_control_api.py::test_cancel_is_accepted_with_a_live_executor_elsewhere`
- `backend/tests/runtime/test_run_command_contract.py`

### INV-CMD-002：点几次取消都是一条命令
约定：重复提交相同取消只产生一条命令；去重落在存储的唯一约束上。
Owner: `backend/travel_agent/runtime/run_commands.py`、`backend/travel_agent/storage/run_command_store.py`
Storage: `trip_run_commands` 的唯一约束。
Tests:
- `backend/tests/db/test_run_commands.py::test_cancel_is_one_command_however_many_times_it_is_clicked`
- `backend/tests/db/test_run_control_api.py::test_clicking_stop_again_returns_the_same_receipt`

### INV-CMD-003：终态不因取消而改变原因
约定：用户取消收敛为 CANCELLED；失去租约或响应流退出收敛为 INTERRUPTED，两者不混用。
Owner: `backend/travel_agent/runtime/run_commands.py`、`backend/travel_agent/runtime/cancellation.py` 的 `RunStopReason`
Tests:
- `backend/tests/runtime/test_run_command_contract.py::test_a_completed_run_does_not_pretend_the_cancel_was_carried_out`
- `backend/tests/db/test_run_recovery.py::test_cancel_requested_converges_to_cancelled`

### INV-CMD-004：没有命令停在 claimed 上出不来
约定：claimed 表示「取走了但还没落到效果上」，必须有可恢复路径；协调器停止时归还未生效的 claim，新进程也取走上一个进程留下的 claimed 行。
Owner: `backend/travel_agent/runtime/run_commands.py`、`backend/travel_agent/storage/run_command_store.py` 的 `claim_pending`
Storage: `trip_run_commands.status` / `claimed_by`。
Tests:
- `backend/tests/db/test_run_commands.py::test_an_unapplied_claim_goes_back_to_pending`
- `backend/tests/db/test_run_commands.py::test_release_does_not_reopen_a_settled_command`
- `backend/tests/db/test_run_commands.py::test_a_claim_left_by_a_dead_process_is_redelivered`

### INV-CMD-005：一条追加要求只进 state 一次
约定：追加要求先成为带 `command_id` 的 `IntentAmendment`，reducer 按 id 去重；只有在 Request Contract 归一化成功后才标记 consumed。
Owner: `backend/travel_agent/planning/state.py` 的 `_replace_amendments`、`backend/travel_agent/planning/requirements/amendments.py`
Tests:
- `backend/tests/runtime/test_run_command_contract.py::test_parallel_workers_do_not_store_the_same_amendment_twice`
- `backend/tests/runtime/test_run_command_contract.py::test_replacing_amendments_keeps_order_and_distinct_commands`
- `backend/tests/runtime/test_run_command_contract.py::test_supplement_is_consumed_only_after_contract_normalization`

### INV-JOB-002：丢失租约的 worker 不写结果
约定：续不上租约就取消处理器；写结果时按 `lease_owner` 过滤，丢失租约的那个写不进去。
Owner: `backend/travel_agent/runtime/background_jobs.py` 的 `_renew_lease`、`backend/travel_agent/storage/background_job_store.py` 的 `complete` / `fail`
Tests:
- `backend/tests/db/test_background_jobs.py`

### INV-JOB-001：后台任务可重试、去重、恢复
约定：claim 一次只给一个消费者；租约过期后重新可领；attempt 耗尽的进 dead。
Owner: `backend/travel_agent/runtime/background_jobs.py`、`backend/travel_agent/storage/background_job_store.py`
Storage: `background_jobs`（lease / attempt / backoff / dedupe key）。
ADR: [ADR-0004](adr/ADR-0004-durable-local-jobs.md)
Tests:
- `backend/tests/db/test_background_jobs.py::test_claim_takes_each_job_once`
- `backend/tests/db/test_background_jobs.py::test_a_claimed_job_is_not_claimable_until_its_lease_expires`
- `backend/tests/db/test_background_jobs.py::test_attempts_run_out_into_dead`
- `backend/tests/memory/test_memory_extraction_job.py`

---

## 意图与编排

### INV-INTENT-001：每条实质性输入都有明确去向
约定：每条 clause 只能映射到 Intent、Constraint、受控身份、background_context、non_actionable、unsupported 或 unresolved；实质性 clause 不得被静默丢弃；unsupported 与 unresolved 必须带 reason code。
Owner: `backend/travel_agent/planning/requirements/normalization/clauses.py`、`backend/travel_agent/planning/requirements/normalization/model.py`、`backend/travel_agent/planning/requirements/normalization/contracts.py`、`backend/travel_agent/planning/requirements/revision.py`
Tests:
- `backend/tests/planning/requirements/test_control_plane.py::test_provider_failure_keeps_safe_parts_and_flags_compound_clause`
- `backend/tests/planning/requirements/test_control_plane.py::test_provider_failure_maps_an_unnumbered_alternative_request`

### INV-INTENT-004：supplement 不得绕过 Request Contract Normalizer
约定：计划门修改与运行中 supplement 都先转为 `IntentAmendment`，经过同一个归一化边界；研究相关修改失效当前代产物并返回归一化节点。
Owner: `backend/travel_agent/planning/requirements/amendments.py`、`backend/travel_agent/planning/requirements/supplements.py`、`backend/travel_agent/planning/requirements/normalization/node.py`、`backend/travel_agent/planning/graph.py`
Tests:
- `backend/tests/planning/requirements/test_control_plane.py::test_runtime_supplement_routes_through_contract_normalization`
- `backend/tests/runtime/test_run_command_contract.py::test_supplement_is_consumed_only_after_contract_normalization`

### INV-PLAN-001：相同 Request Contract 必须得到相同执行图
约定：`ResearchBriefV2`、`ResearchQueryPlan`、`CapabilityPlan` 与 `execution_plan` 只由纯函数投影；planner 节点不调用模型。
Owner: `backend/travel_agent/planning/research/brief_builder.py`、`backend/travel_agent/planning/research/query_planner.py`、`backend/travel_agent/planning/research/capability_planning.py`、`backend/travel_agent/planning/research/plan.py`
Tests:
- `backend/tests/planning/requirements/test_control_plane.py::test_contract_and_capability_plan_are_deterministic_and_cover_hard_intents`

### INV-INTENT-005：Intent 与 Constraint 只归一化一次
约定：同一批 clause 的一次结构化调用同时产生 Intent 与 Constraint draft；显式数值预算由确定性规则补齐；Brief、Planner 与 Worker 只消费结构化合同，不再解释原始要求。
Owner: `backend/travel_agent/planning/requirements/normalization/`、`backend/travel_agent/planning/requirements/constraints/assembly.py`
Tests:
- `backend/tests/planning/requirements/test_control_plane.py::test_full_trip_sentence_does_not_treat_party_size_as_nightly_budget`
- `backend/tests/planning/requirements/test_control_plane.py::test_provider_failure_keeps_safe_parts_and_flags_compound_clause`

### INV-NODE-001：运行图节点都有用户可见元数据
约定：运行图的每个节点都出现在后端三张运行时表（trace phase、agent 显示名、step 显示名）中；前端阶段表覆盖同一组节点并接受 `_rN` 与「（第N轮补充）」后缀，进度摘要表为可展示的节点提供标签与说明。
Owner: `backend/travel_agent/planning/trace.py` 的 `NODE_PHASES`、`backend/travel_agent/planning/presentation.py` 的 `AGENT_DISPLAY_NAMES` 与 `STEP_DISPLAY_NAMES`、`frontend/src/features/chat/model/agentStages.ts` 的 `NODE_STAGES`、`frontend/src/features/travel/model/travelProgress.ts`
Tests:
- `backend/tests/planning/test_node_presentation.py::test_user_facing_node_metadata_matches_the_runtime_graph`
- `frontend/src/features/chat/model/agentStages.test.ts`

### INV-INTENT-006：意图变更能从每个节点续跑，除了明确不该的两个
约定：`intent_amendment_router` 的 conditional edge 必须覆盖除 `scope_clarifier` 与路由节点自身之外的每个运行节点；守卫从构造好的图上读回落点，不扫描源码。
Owner: `backend/travel_agent/planning/graph.py` 的 `amendment_continuations` 与 `route_after_intent_amendment`、`backend/travel_agent/planning/requirements/amendments.py`
Tests:
- `backend/tests/planning/test_node_presentation.py::test_intent_amendments_can_resume_at_every_runtime_node_that_accepts_them`

### INV-WEP-002：provider_empty: 前缀固定判 (incomplete, provider_empty_result)
约定：持久化的 `provider_empty:` 前缀映射为 incomplete / provider_empty_result，`is_provider_or_model_failure` 返回 True；Provider 完成调用但零命中属于空结果。前缀字符串是持久化格式，逐字符稳定。
Owner: `backend/travel_agent/planning/research/failure_protocol.py`、`backend/travel_agent/planning/research/provider_failure.py`、`backend/travel_agent/planning/research/errors.py`
Tests:
- `backend/tests/planning/research/test_worker_error_protocol_contract.py::test_persisted_failure_prefixes_have_stable_reader_verdict`

### INV-WEP-003：provider_transient: 前缀固定判 (transient, provider_transient_failure)
约定：持久化的 `provider_transient:` 前缀映射为 transient / provider_transient_failure，`is_provider_or_model_failure` 返回 True；暂态失败重试不会逐字复现，不能读成确定性失败。前缀字符串是持久化格式，逐字符稳定。
Owner: `backend/travel_agent/planning/research/failure_protocol.py`、`backend/travel_agent/planning/research/provider_failure.py`、`backend/travel_agent/planning/research/errors.py`
Tests:
- `backend/tests/planning/research/test_worker_error_protocol_contract.py::test_persisted_failure_prefixes_have_stable_reader_verdict`

### INV-WEP-004：provider_deterministic: 前缀固定判 (deterministic, provider_deterministic_failure)
约定：持久化的 `provider_deterministic:` 前缀映射为 deterministic / provider_deterministic_failure，`is_provider_or_model_failure` 返回 True；确定性失败重试会逐字复现。前缀字符串是持久化格式，逐字符稳定。
Owner: `backend/travel_agent/planning/research/failure_protocol.py`、`backend/travel_agent/planning/research/provider_failure.py`、`backend/travel_agent/planning/research/errors.py`
Tests:
- `backend/tests/planning/research/test_worker_error_protocol_contract.py::test_persisted_failure_prefixes_have_stable_reader_verdict`

### INV-WEP-005：provider_capability: 前缀固定判 (incomplete, provider_capability_declined)
约定：持久化的 `provider_capability:` 前缀映射为 incomplete / provider_capability_declined，`is_provider_or_model_failure` 返回 True；Gateway 在调用前判定 Provider 答不了所请求的日期。前缀字符串是持久化格式，逐字符稳定。
Owner: `backend/travel_agent/planning/research/failure_protocol.py`、`backend/travel_agent/planning/research/provider_failure.py`、`backend/travel_agent/planning/research/errors.py`
Tests:
- `backend/tests/planning/research/test_worker_error_protocol_contract.py::test_persisted_failure_prefixes_have_stable_reader_verdict`

---

## 流与会话

### INV-SSE-001：每个请求只做一次终态转移
约定：一个请求的 Run 状态只发生一次终态转移。正常完成路径以 `chat_complete` 或 `delivery_ready` → `run_terminal` 收口，取消路径以 `run_cancelled` 收口；`delivery_ready_emitted` / `run_terminal_emitted` 保证同一终态帧不重复发布。恢复路径按封存状态收口，不把已完成交付改写为失败。
Owner: `backend/travel_agent/conversation/chat/completion.py`、`backend/travel_agent/conversation/chat/failures.py`、`backend/travel_agent/conversation/chat/delivery.py`（`delivery_ready_emitted` / `run_terminal_emitted`）、`backend/travel_agent/conversation/chat/lifecycle.py`（`cleanup_stream_exit`）
ADR: [ADR-0003](adr/ADR-0003-sse-terminal-model.md)
Tests:
- `backend/tests/conversation/test_chat_execution.py::test_deep_asgi_body_is_backed_by_persisted_bundle_and_ordered_terminal`
- `backend/tests/api/test_chat_use_cases.py::test_deep_post_commit_failure_keeps_sealed_truth_and_projection_flag`

### INV-SSE-002：慢客户端不让内存无界增长，且不丢一个字符
约定：critical 队列有界且不丢；token 合并成更大 chunk 而不是丢弃；待发正文超上限即强制 flush；消费者卡住则结束传输交给 durable 恢复。
Owner: `backend/travel_agent/runtime/events.py`
Storage: 进程内，上限在 `Settings.streaming`。
ADR: [ADR-0006](adr/ADR-0006-resource-budgets-and-isolation.md)
Tests:
- `backend/tests/runtime/test_event_buffer.py::test_a_slow_client_keeps_every_character_and_every_critical_event`
- `backend/tests/runtime/test_event_buffer.py::test_adjacent_tokens_merge_without_losing_characters`
- `backend/tests/runtime/test_event_buffer.py::test_a_consumer_that_never_reads_is_reported_stalled`

### INV-SESSION-001：一个 turn 永远整块返回
约定：turn 分页以稳定的 first event order 为游标，不使用 offset。
Owner: `backend/travel_agent/api/routes/sessions.py` 的 turn 分页、`backend/travel_agent/memory/chat_session.py` 的 `list_turns`
Storage: `chat_session_events(session_id, turn_id, event_order)`。
Tests:
- `backend/tests/db/test_session_turns.py::test_a_turn_is_always_returned_whole`
- `backend/tests/db/test_session_turns.py::test_a_new_turn_does_not_shift_an_open_cursor`
- `backend/tests/db/test_session_turns.py::test_a_page_stops_at_the_event_budget`

### INV-SESSION-003：翻页代价不随会话长度增长
约定：先按 `(session_id, event_order)` 倒序取有界一窗再分组，不对整个会话做 GROUP BY；窗口边界可能被截断的 turn 单独处理，往回翻不漏 turn。
Owner: `backend/travel_agent/memory/chat_session.py` 的 `list_turns`
Tests:
- `backend/tests/db/test_session_turns.py::test_ten_thousand_events_still_page_in_one_screen`
- `backend/tests/db/test_session_turns.py::test_paging_backwards_walks_the_whole_session`

### INV-SESSION-004：「没什么可整理」与「正在整理」不是同一句话
约定：已有一次整理在跑或提交时被抢先返回 409；真的没有可压缩消息返回 400。
Owner: `backend/travel_agent/memory/compaction.py` 的 `CompactionBusy`、`backend/travel_agent/api/routes/sessions.py`
Tests:
- `backend/tests/db/test_session_turns.py::test_a_raced_commit_is_busy_not_nothing_to_compact`
- `backend/tests/db/test_session_turns.py::test_nothing_to_compact_returns_none`

### INV-SESSION-002：压缩只读预算范围，boundary 精确
约定：boundary 只推进到实际进入摘要的最后一条；失败不推进也不覆盖旧 anchor；`commit_compaction` 是唯一写入方。
Owner: `backend/travel_agent/memory/compaction.py`
Storage: session anchor + boundary + compaction event（同事务）。
Tests:
- `backend/tests/db/test_session_turns.py::test_compaction_only_reads_the_budget_and_moves_the_exact_boundary`
- `backend/tests/db/test_session_turns.py::test_a_second_compaction_is_incremental`
- `backend/tests/db/test_session_turns.py::test_a_failed_compaction_leaves_the_anchor_and_boundary_alone`

---

## 资源边界

### INV-TOOL-001：日期能力先于运行预算、重试和 Provider 网络调用
约定：12306 只把上海时区 today 至 today+14 当作目标日实时余票；更远日期只查询窗口末日并标记 reference-only，不可作为证据。正式天气只在目的地本地 16 日窗口内请求精确预报；更远日期跳过预报端点，改用十个完整年份的同月历史季节基线，不生成逐日天气、概率或小时级事实。
Owner: `backend/travel_agent/tools/temporal.py`、`backend/travel_agent/tools/gateway.py`、`backend/travel_agent/tools/execution.py` 的 `execute_tool`、`backend/travel_agent/integrations/weather.py`
Tests:
- `backend/tests/tools/test_temporal_tool_policy.py`

### INV-BLOCK-001：同步工作不阻塞 Event Loop，且并发有上限
约定：PDF 渲染、文档解析、本地 embedding 一律走受限线程或子进程；排队有上界，等不到位置抛 `BlockingWorkBusy` 而不是无限排队。
Owner: `backend/travel_agent/runtime/blocking_work.py`、`backend/travel_agent/runtime/concurrency.py`
Storage: 进程内通道，上限在 `Settings.blocking_work`。
ADR: [ADR-0006](adr/ADR-0006-resource-budgets-and-isolation.md)
Tests:
- `backend/tests/runtime/test_blocking_work.py::test_blocking_call_does_not_stall_the_event_loop`
- `backend/tests/runtime/test_blocking_work.py::test_channel_limit_caps_concurrent_thread_work`
- `backend/tests/runtime/test_blocking_work.py::test_queue_wait_has_an_upper_bound`

### INV-INGEST-001：不可信文档先过输入边界，再进受限解析单元
约定：类型（magic bytes + OOXML 必要条目）→ 规模（字节 / 展开量 / 压缩比 / 条目数）→ 解析（子进程 + RLIMIT + 超时杀进程组）；超时不是唯一保护。
Owner: `backend/travel_agent/knowledge/sources/document_parse.py`、`backend/travel_agent/knowledge/sources/document_parser_worker.py`
Storage: 上限在 `Settings.ingest`。
ADR: [ADR-0006](adr/ADR-0006-resource-budgets-and-isolation.md)
Tests:
- `backend/tests/knowledge/test_document_parse.py::test_zip_bomb_is_rejected_on_compression_ratio`
- `backend/tests/knowledge/test_document_parse.py::test_zip_bomb_is_rejected_on_expanded_size`
- `backend/tests/knowledge/test_document_parse.py::test_a_pdf_suffix_over_non_pdf_bytes_is_rejected`
- `backend/tests/knowledge/test_document_parse.py::test_a_pdf_over_the_page_cap_is_rejected`
- `backend/tests/knowledge/test_document_parse.py::test_parser_timeout_kills_the_subprocess`

### INV-BUDGET-001：预算在调用之前判，快照不受配置热更新影响
约定：按最坏开销在调用前判；快照在 Draft 授权时封存，与 Deadline 同进同出。
Owner: `backend/travel_agent/runtime/budget.py`
Storage: `RunBudgetSnapshot` 随 checkpoint；已花量的最终事实在 `run_llm_calls`。
ADR: [ADR-0006](adr/ADR-0006-resource-budgets-and-isolation.md)
Tests:
- `backend/tests/runtime/test_run_budget.py::test_worst_case_estimate_blocks_the_call_that_would_overspend`
- `backend/tests/runtime/test_run_budget.py::test_a_sealed_snapshot_ignores_later_config_changes`
- `backend/tests/runtime/test_run_budget_boundaries.py::test_budget_and_deadline_must_be_sealed_together`
- `backend/tests/runtime/test_run_budget_boundaries.py::test_a_replay_of_a_sealed_draft_never_refills_the_budget`

### INV-BUDGET-004：判和记是一步，重试不能超支
约定：每次工具调用尝试都先预留再执行；判与记分开会让上限失效。
Owner: `backend/travel_agent/runtime/budget.py` 的 `RunBudgetLedger.reserve_tool_call`
Tests:
- `backend/tests/runtime/test_run_budget_boundaries.py::test_the_retry_loop_cannot_outspend_the_tool_call_budget`

### INV-BUDGET-005：重试上限管的是重试轮数，不是调用次数
约定：首发不计入 `max_tool_retries_per_target`；重试计数只约束重试轮数。
Owner: `backend/travel_agent/runtime/budget.py` 的 `tool_retries` / `record_tool_retry`
Tests:
- `backend/tests/runtime/test_run_budget.py::test_per_tool_retries_are_bounded`
- `backend/tests/runtime/test_run_budget.py::test_a_tool_that_keeps_succeeding_never_runs_out_of_retries`

### INV-BUDGET-002：预算耗尽是可解释的降级，不是一次 Run 失败
约定：工具侧返回带 `run_budget_exhausted.<维度>` 的 failed envelope，调用方按可解释降级处理；不抛异常、不把 Run 记成 CANCELLED。
Owner: `backend/travel_agent/tools/execution.py`、`backend/travel_agent/runtime/budget.py` 的 `RunBudgetExhausted`
Tests:
- `backend/tests/runtime/test_run_budget_boundaries.py::test_tool_call_over_budget_returns_a_failed_envelope_not_an_exception`
- `backend/tests/runtime/test_run_budget_boundaries.py::test_a_tool_that_used_up_its_retries_is_not_called_again`

### INV-BUDGET-003：低报的费用不许当上限用
约定：价格表未命中时 `cost_complete=false`，费用维不参与判定；低报本身随成本摘要报出去。
Owner: `backend/travel_agent/runtime/budget.py` 的 `exhausted_dimension`
Tests:
- `backend/tests/runtime/test_run_budget.py::test_an_unpriced_call_never_lets_cost_reject_a_call`

### INV-BUDGET-006：预算维度只有一份清单，每一维都有对应字段
约定：`BudgetDimension` 是唯一来源，`BUDGET_DIMENSIONS` 由它派生；守卫比较 Literal 与 pydantic 字段集两个独立来源，每一维都有 `max_*` 上限字段和同名用量字段。`max_tool_retries_per_target` 不是预算维度，显式登记在测试守卫的 `_NON_DIMENSION_LIMIT_FIELDS`（定义于 `backend/tests/runtime/test_run_budget.py`）。
Owner: `backend/travel_agent/runtime/budget.py` 的 `BudgetDimension`、`BUDGET_DIMENSIONS`、`RunBudgetSnapshot.limit`、`RunBudgetUsage.spent`
Tests:
- `backend/tests/runtime/test_run_budget.py::test_every_budget_dimension_has_a_limit_field_to_reflect_onto`
- `backend/tests/runtime/test_run_budget.py::test_remaining_budget_reports_every_dimension_and_nothing_else`

### INV-CHAN-001：入库不许把在线请求排到队尾
约定：contextual 分块走 `ingest_contextual_llm`，与 `online_fast_llm` 分开计配额。
Owner: `backend/travel_agent/runtime/concurrency.py`、`backend/travel_agent/llm/router.py` 的 `llm_channel`
Storage: 进程内通道，配额在 `Settings.provider_channels`。
ADR: [ADR-0006](adr/ADR-0006-resource-budgets-and-isolation.md)
Tests:
- `backend/tests/llm/test_provider_channels.py::test_ingest_and_online_calls_do_not_share_a_quota`
- `backend/tests/llm/test_provider_channels.py::test_changing_the_limit_replaces_the_gate`

---

## 配置与交付

### INV-CFG-001：未知配置字段与拼错的环境变量都是错误
约定：配置模型 `extra="forbid"`；校验失败带字段路径、当前值与合法范围；认不出的 `JOURNEYPILOT_*` 阻止启动。
Owner: `backend/travel_agent/config/models.py` 的 `StrictConfig`、`backend/travel_agent/config/env.py`
ADR: [ADR-0008](adr/ADR-0008-config-single-source.md)
Tests:
- `backend/tests/config/test_config_contract.py::test_an_unknown_field_is_rejected_with_its_path_and_value`
- `backend/tests/config/test_config_contract.py::test_a_misspelled_env_variable_is_an_error_not_a_no_op`
- `backend/tests/config/test_config_contract.py::test_a_wrong_typed_env_value_is_an_error_not_a_fallback`

### INV-CFG-005：环境变量覆盖之后配置仍然合法
约定：覆盖是 `setattr`，不触发 Field 约束与 `model_validator`；覆盖写完整体重校验一次。
Owner: `backend/travel_agent/config/env.py` 的 `_revalidate`
Tests:
- `backend/tests/config/test_config_contract.py`

### INV-CFG-002：每个生效值都能说出它从哪来
约定：来源分三档：config default / config.yaml / environment (VAR)。
Owner: `backend/travel_agent/config/loader.py` 的 `EffectiveConfig`
ADR: [ADR-0008](adr/ADR-0008-config-single-source.md)
Tests:
- `backend/tests/config/test_config_contract.py::test_effective_config_states_where_each_value_came_from`

### INV-CFG-003：配置文档与 schema 不许漂移
约定：生成物与当前 schema 必须一致；测试与 CLI 都比对。
Owner: `backend/travel_agent/config/schema_export.py`、`journeypilot config docs --check`
Storage: `docs/configuration.md`、`docs/config.schema.json`（生成物，提交进仓库）。
ADR: [ADR-0008](adr/ADR-0008-config-single-source.md)
Tests:
- `backend/tests/config/test_config_contract.py::test_generated_config_docs_are_committed`
- `backend/tests/config/test_config_contract.py::test_the_example_config_is_valid_and_current`

### INV-CFG-004：示例配置不带 API Key
约定：preset 只写连接段；Key 走环境变量或 `.env`。
Owner: `backend/config.example.yaml`、`backend/travel_agent/config/providers.py` 的 `preset_model_section`
ADR: [ADR-0008](adr/ADR-0008-config-single-source.md)
Tests:
- `backend/tests/config/test_config_contract.py::test_the_example_config_ships_no_api_key`
- `backend/tests/config/test_config_contract.py::test_a_preset_section_never_contains_an_api_key`

### INV-PROV-001：Provider 兼容性来自声明，不靠猜 base_url
约定：capability 按 base_url 的 host（带端口）解析；认不出的上游使用保守能力档。
Owner: `backend/travel_agent/config/providers.py`、`backend/travel_agent/resources/providers/*.yaml`
ADR: [ADR-0008](adr/ADR-0008-config-single-source.md)
Tests:
- `backend/tests/config/test_config_contract.py::test_direct_and_proxied_deepseek_get_different_capabilities`
- `backend/tests/config/test_config_contract.py::test_an_unknown_endpoint_gets_the_conservative_profile`
- `backend/tests/config/test_config_contract.py::test_a_local_service_on_another_port_is_not_ollama`
- `backend/tests/config/test_config_contract.py::test_reasoning_dialects_follow_the_declaration`

### INV-DEP-001：配置要求的增强能力没装就不启动
约定：启动前探测依赖（不 import 模型），缺失即拒绝并给出安装命令；readiness 的 `optional_capabilities` 一项阻断。
Owner: `backend/travel_agent/config/capabilities.py`
ADR: [ADR-0007](adr/ADR-0007-core-default-enhancements-optional.md)
Tests:
- `backend/tests/config/test_capabilities.py`

### INV-UI-002：翻回来的历史不被 setup 投影切掉
约定：翻页取回的消息带 `isEarlierHistory`，投影不切它；setup 边界只隐藏本次运行开始之前的往来。
Owner: `frontend/src/features/chat/model/conversationFlow.ts` 的 `projectVisibleMessages`
Tests:
- `frontend/src/features/chat/model/conversationFlow.test.ts`

### INV-UI-001：资料处理失败给出可执行且不泄露内部信息的提示
约定：已知文件、繁忙、寻址和空文本错误映射到换文件、重试、刷新或停止操作；未知错误使用通用安全文案，不直接显示后端原文。
Owner: `backend/travel_agent/api/routes/knowledge.py`、`frontend/src/features/knowledge/model/knowledgeIngestFailure.ts`
Tests:
- `frontend/src/features/knowledge/model/knowledgeIngestFailure.test.ts`

### INV-UI-003：产品面不输出工具原始载荷
约定：后端 `summarize_tool_result` 决定展示什么，前端 `toolResultText` 决定拦截什么；认不出的形状也绝不输出原始 JSON 载荷；历史会话里保存的 `tool_result` 同样在渲染时被拦截。
Owner: `backend/travel_agent/tools/governance.py` 的 `summarize_tool_result`、`frontend/src/features/chat/model/toolDisplay.ts` 的 `toolResultText`
Tests:
- `backend/tests/tools/test_tool_result_summary.py`
- `frontend/src/features/chat/model/toolDisplay.test.ts`
