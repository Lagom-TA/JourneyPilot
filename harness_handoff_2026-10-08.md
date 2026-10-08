# JourneyPilot Harness 架构审查与修复：新会话交接

交接日期：2026-10-08。工作目录：`/home/tang/projects/JourneyPilot`。

本文件记录交接时的实际状态。新会话应先核对工作区和审查报告，在已有改动上继续实施剩余审查与修复。此次交接只新增本文件，没有继续修改生产代码或重新运行测试。

## 1. 用户目标与执行方式

用户要求参考官方 OpenAI Codex 和 DeepSeek Harness（DSH），让 JourneyPilot 的 harness 责任边界更清晰，提升缓存与 Token 利用率，并以更低的成功交付成本获得更高效率。任务包含分析、代码审查、实际修复和验证，不能仅给建议或计划。

用户已确认使用官方 `deepseek-ai/deepseek-harness`。后续按**模型名称与任务类型**分析和优化，不按供应商做比较。主辅模型分工也属于本轮审查范围。

必须保留的用户偏好与当前执行约束：

- reasoning 使用 `medium` / `low`，不设置关闭推理。
- 累积 Run 预算默认只计量、不阻断；不重新引入隐式调用、Token 或费用上限。单次 API 输出参数与累计预算分别处理。
- 自主完成已授权的代码审查、可逆修改与离线验证；只有缺失信息会实质影响决策时才询问，不反复请求继续或确认。
- 不主动启动子 agent。当前任务没有用户授权的委派要求。
- 保留已有未提交改动，不执行 reset、清理或覆盖；不 commit/push。
- 不调用付费模型、不发送外部消息、不对业务数据库执行迁移；先完成本地修复及可复现离线验证。真实付费 A/B 需要后续明确授权。
- `config.yaml` 含密钥，禁止整份输出；仅按白名单读取必要的模型、推理、预算、价格字段，不输出凭据。
- 当前权限为 unrestricted、approval never；不要给工具传 `sandbox_permissions`。
- 交接时项目与祖先没有适用 `AGENTS.md`。参考仓库内有自己的 `AGENTS.md`；它们不管辖 JourneyPilot 生产源码。
- 以前用过 OpenAI docs skill：`/home/tang/.codex/skills/.system/openai-docs/SKILL.md`。新会话若需要使用该 skill，应按当时的 skill 规则读取；本文件不替代其指令。

## 2. 首先读取和核对

1. 本文件与 `harness_review_2026-10-08.md`（中文实现、结论、理论来源与限制）。
2. `git status --short`、`git diff --stat`；有必要时查看相关 diff，保护全部历史未提交工作。
3. `temp/harness-review-2026-10-05/manifest.json`（固定参考 SHA、验证范围）。
4. 按下文优先级读取真实调用链，再提出并实施下一批修复，不重新下载参考代码或重复已经完成的改造。

交接时 `HEAD` 与审查基线均为 `5e08d829a04048c6f6dba86b191813e22825c106`。所有 Token 与架构改动都未提交，包含 modified 和 untracked 文件；本地 `config.yaml` 的调整不在普通 diff 中，不能据此推断未配置。

参考仓库在 Git 忽略目录 `temp/harness-review-2026-10-05/`：

| 仓库 | 子目录 | 固定 SHA |
|---|---|---|
| `openai/codex` | `codex/` | `823ea830c0fd418b09ff02d36cad9a1fff66465b` |
| `deepseek-ai/deepseek-harness` | `deepseek-harness/` | `5badb15009ae1756c3afe0ae0cef1faafc290ccc` |

优先参考 DSH 的 `packages/core/agent-loop/src/runtime-context.ts`、`agent.ts` 与 token meter，以及 Codex 的 `codex-rs/core/src/context_manager/updates.rs`、`history.rs`、`session/retained_context.rs`。其设计是参考，不直接复制数据口径或替换框架。

## 3. 已完成：Token 计量与运行预算

- `models/usage.py` 同时读取标准/raw usage，支持 cache read/write、reasoning、Responses 形状、流式末尾累计 usage 与 SDK 长度错误。
- 统一口径：`input_tokens` **包含** cache read/write；这两项是互斥子桶；reasoning 已包含在 output，不再重复计费。DSH 的 input 是 exclusive input，不能照搬其加法。
- 缺失、估算、部分或矛盾数量明确标记；未知费用保持 `null`。成功响应缺少 usage 才用离线估算；错误/取消不编造 Token。
- 成本：`(input-read-write)*p_in + read*p_read + write*p_write + output*p_out`。
- Router 每次 retry 独立记录 `call_id`、`logical_call_id`、`attempt_number`，SDK retry=0；保留 `finish_reason` 和截断信号。
- 离线请求估算覆盖 wire 消息、工具、reasoning replay 与 response schema，统一 tokenizer，不在请求期间下载 tokenizer。API usage 才是账单权威值。
- SSE 带 call_id，前端去重；未知数量/费用不显示为 0，细分完整性保留。
- `run_budget.enforce_limits=false`、累计限额默认 `null`；旧 checkpoint 缺失该 flag 时也是观察模式。严格模式仅为显式配置选项，其并发预留和预测尚未改造。
- 移除 worker 固定输出 Token 顶；单次 API 默认输出参数为 65536，可配置更高正整数，要服从具体模型能力；它不是累计 Run 配额。
- 当前本地 primary=`openai/gpt-6.1-sol`、medium；fast=`deepseek/deepseek-v4.1-flash`、low。不要自行换模型或关推理。
- `maps_text_search` / `maps_search_detail` 绕开缺少 TTL 的本地 envelope cache，继续由 ProviderSnapshotCache 管理 TTL、快照和审计。

本地价格覆盖已经存在，不要误报缺价格或擅自换公共价。每百万 Token：primary input=2、read=0.1、write=2.5、output=10；fast input=0.3、read=0.006、output=1.2。价格配置不等于 API 一定返回全部计费字段；缺失关键桶时保持费用未知。

数据库迁移新增 `migrations/versions/0008_llm_usage_details.py` 与对应 fingerprint，保留历史费用快照。只在独立 PostgreSQL 14 临时集群验证 ledger 升降级、旧行、幂等/冲突及 fingerprint，**项目业务数据库未迁移**。项目连接不可用，独立验证只建 trip_runs stub 与 ledger，不能声称完整 pgvector schema 集成已验证。

## 4. 已完成：研究上下文与工具曝光架构批次

保留 LangGraph、typed workers/gates 和单一交付出口。没有切换 Responses，没有自动模型升级，没有删除 deadline。

### 稳定合同与动态 runtime

- 新 `memory/agent_context.py` 用 frozen `ContextSection` 统一 anchor、preset、constraints、weather 装配；领域 formatter 保留。
- `agents/utils.py::inject_agent_context` 变兼容 wrapper；itinerary 中无消费者的重复 `_agent_context_pieces` 已删除。
- `agents/research_packet_prompt.py` 的 frozen `ResearchPrompt(system,runtime)` 为研究 worker 提供生产入口 `build_research_packet_prompt()`。
- 固定 role/schema/domain/hard_contract 在 system；run/task/revision/time/limit/推荐工具/背景/投影在 runtime。schema 使用 lru_cache。
- 三个研究 worker 已接入，顺序为 `system → history → 最新 runtime → 本轮 task/preflight → assistant/tool`，动态背景只注入一次。
- 推荐工具在 runtime 表达，不再通过重排 schemas 表达偏好。legacy prompt builder 留给旧测试与离线 probe。
- itinerary 仍使用兼容入口把动态内容注入 system，**尚未完成同样的改造**。

### 工具曝光 owner

- 新 `tools/exposure.py`：`ToolExposurePlan`、`apply_tool_exposure()`、`ToolExposureSession`、`attach_tool_catalog()`。
- 由已经过滤的工具白名单创建计划，按 name 固定初始排序；full 曝光固定 schemas，deferred 初始仅 search_tools 与静态紧凑目录。
- 每次 invocation 的 session 私有，schema deepcopy；激活 append-only、排序、去重，不扩权、不跨调用泄漏。Gateway 仍持有原执行白名单。
- 三 worker 删除重复组装；`streaming_react_loop` 删除冗余 `tool_schemas` 参数，三个调用点已更新，唯一来源是 exposure session。
- 目录 copy 消息字典，重复附加幂等；不得破坏调用方 transcript 列表身份。

已经修复的关键边界，后续必须保留：

```python
messages[:] = attach_tool_catalog(messages, exposure_plan)
```

不能改成局部重新赋值后丢失 caller 的工作 transcript。Packet parser/repair 依赖完整 assistant/tool、reasoning replay 和 authoritative Gateway envelopes；当前回归覆盖搜索、执行、审计、SSE 和 transcript 保留。

### 任务范围 Research Packet 投影

- 新 `memory/research_context.py`，独立合同 `journeypilot.research_context.v1`、purpose=`coordination_and_repair`。这是模型输入视图，不是 packet admission。
- 只同 run、同 planning generation、相关目的地和候选类型；按 fact revision、UTC 时间、packet ID 选最新候选。
- 协调视图保留身份/地址/日期/route endpoints/segments、fact value/unit/currency/status/时序/links、source 引用/hash/时序/lifecycle，移除 snapshot/excerpt 与重复索引。
- destination 无普通上游候选；lodging 接收 visit/dining/transport；transport 接收 visit/dining/lodging。
- 补研目标来自 assignment.excluded_candidate_ids 或本任务 open/researching gap。普通 gap 受 query/destination/worker scope 限制；显式目标可跨目的地。
- own-worker 补研闭包保留全部目标事实（含 missing/conflict）、支持/冲突来源原 snapshots/hash、provenance、discovery；历史证据不冒充本轮 Gateway transcript。
- 投影通过 copy 不修改原 packet。新包遗漏旧候选不表示删除；当前按增量记录处理，未来撤销应有显式状态。
- 三 worker 已接入；旧完整 packet serializer 保留作诊断，无生产消费者。

## 5. 尚未完成：按优先级继续实际审查与修复

### A. 可恢复 ReAct 生命周期（下一批优先）

现状：ReAct 在 worker 调用期间运行，曝光 session/transcript 是 invocation 内存状态，未具备轮次级 checkpoint/event 恢复合同。

入口：

- `agents/utils.py::streaming_react_loop`（交接时约 1604 行）。
- 三个研究 worker 的调用、packet 编译/repair/admission。
- `workflows/run_control.py`、`workflows/travel_planning.py`、`workflows/run_deadline.py`。
- `infrastructure/checkpointer.py`、`run_execution_store.py`、`trip_run_store.py`。
- `api/routes/chat.py` 的 resume claim、safe checkpoint 和 lease。
- `tools/exposure.py`、Tool Gateway/审计/缓存的实际调用链。

先确定真实故障路径和现有持久状态 owner，再定义模型请求准入、assistant tool call、tool result、packet admission 的提交/重放边界。重点审查取消、deadline、异常、进程崩溃后是否出现未配对 tool calls、重复工具执行、丢失已完成结果或重复 packet 提交。恢复要兼容已有 run lease、checkpoint 合同与交付 finalizer；不能把 LangGraph checkpoint 误认为与业务事务原子提交。

通过 fake LLM、真实 Gateway/内存 store 和故障注入验证边界。按证据选择最小完整改造，不一口气换掉 LangGraph，不用自动重跑代替副作用幂等。

### B. UsageRecorder 持久缓冲与完整性

现状：`models/usage.py::UsageRecorder` 的 10,000 条 deque 可能挤掉记录；`dropped` 未进入汇总，没有 durable spool。崩溃、长时间 DB 故障与 drain 后尚未落库时不能保证还原全部账单。

入口：`models/router.py`、`builders.py`、`api/routes/chat.py`（约 571、627 行的 drain/requeue）、`infrastructure/cost_ledger_store.py`、SSE 与汇总。

设计可恢复、确认提交后移除、call_id 幂等的持久队列，覆盖 record/drain/commit/ack 崩溃边界、DB 不可用、部分提交、重复 replay 与内容冲突。明确写盘失败和遗漏的完整性状态，不能默默丢记录或把不完整账单显示成完整 0。不要通过设置新的 Run 限额规避记账问题。

### C. 行程组合上下文与压缩保真

入口：`agents/itinerary_planner/node.py`（约 2878、3196 行的动态 system；多个 response_format）、`memory/context_builder.py`、`memory/compressor.py`、composition repair/mutation 与 intent fidelity 测试。

将组合固定合同与动态任务输入分开，处理任务变化 schema 的稳定性与安全性，消除重复/无关上下文。不能把全部 schema 强行静态化或丢失证据/硬约束。压缩判断基于下一次请求窗口占用，不以累计账单 Token 判断；审查摘要、快速回答的保真度与无依据生成。

### D. 主辅模型任务路由与请求协议

现状：研究、意图归一化、候选评价、摘要/快速回答使用 fast/low；组合和全局约束仲裁使用 primary/medium。schema repair 沿用任务档位；未实现质量反馈升级。

按模型名称、任务类型、schema repair、gate failed/unknown、证据闭包丢弃、截断、修复轮与成功交付成本审查分工。恢复/补研标签本身不能触发升级。路由策略和 API 协议分别管理。

当前 primary 用于无工具 Chat Completions 组合调用；若让 `gpt-6.1-sol` 承担工具研究，先确认能力并适配 Responses 工具协议，不能只改模型名。reasoning 保持 medium/low，不自动关闭。先做可复现离线策略/契约测试，再谈付费质量 A/B。

### E. 全面收尾与实验框架

继续检查五层边界：Run control、Model router、Tool gateway/cache、Typed workers/gates、Cost ledger/API。检查缓存 TTL/权限/证据时效、工具激活造成的定义路径差异、输出截断/修复、SSE 重放和观测完整性。尚未纳入本 LLM ledger 的 embeddings 需要说明范围；本地 Qwen embedding 不应凭空计作外部 LLM 账单。

准备冷/暖缓存、新 run/补研/恢复、简单/复杂约束、full/deferred tools 的可复现实验，记录请求估算与真实 usage、cache read/write、成功交付成本、质量门禁、p95、截断与修复率。付费执行未授权时，完成离线框架并清楚报告仍待运行的实验，不能虚构收益。

每批实施更新 `harness_review_2026-10-08.md` 与验证记录，明确已完成/剩余和实际验证范围。没有必要决策缺口时直接推进下一批。

## 6. 验证基线与可复用材料

以下为**此前批次**通过的结果，不是交接时重新运行的结果：

- Token 批次：257 项选定后端测试，22 项前端测试，前端 typecheck/build，Ruff、diff check、独立 PostgreSQL ledger 验证。
- 架构批次：278 项选定后端测试（含新增 21 项上下文/工具边界测试）、Ruff、diff check、两份离线 probes。本批没改前端/数据库，未重复它们的验证。
- 未调用付费模型、未迁移业务数据库、未验证真实线上 cache hit/质量/p95/成本下降。

后端 venv：`temp/harness-review-2026-10-05/test-venv/`。最近通过的选定 suite：

```bash
temp/harness-review-2026-10-05/test-venv/bin/python -m pytest \
  tests/test_token_accounting.py tests/test_model_request_policy.py \
  tests/test_config_contract.py tests/test_prompt_contract.py \
  tests/test_run_budget.py tests/test_run_budget_boundaries.py \
  tests/test_provider_channels.py tests/test_tool_policy_contract.py \
  tests/test_tool_registry_contract.py tests/test_tool_result_summary.py \
  tests/test_tool_exposure.py tests/test_research_context.py \
  tests/agent_behavior/test_intent_composition_fidelity.py \
  tests/agent_behavior/test_intent_control_plane.py \
  tests/agent_behavior/test_intent_research_ranking_selection.py \
  tests/db/test_offline_sql.py -q -p no:langsmith
```

后续测试选择应覆盖新改动的故障边界，并做必要回归；278 项是选定 suite，不是整个仓库全量测试。

同目录材料：`probes.py` / `probe-results.json`、`architecture_probes.py` / `architecture-results.json`、`verify_postgres.py`、`manifest.json`。所有已知工具进程在交接前已结束，无待续接任务。

架构 fixture 包含 4 候选、2 城市、2 generations、人为填充来源页面：全量历史序列化估算 13,082 Token；相关协调视图 2,273；单实体完整补研闭包 3,098。合成 8 工具初始 full=1,352、deferred=432。它们只证明这个 fixture 的上下文/初始曝光变化，不能外推生产成本、cache hit 或质量。工具激活 append-only 也不能保证 API 缓存命中。

## 7. 新会话可直接使用的提示词

```text
请在 /home/tang/projects/JourneyPilot 继续剩余的全部 harness 架构审查、代码修复与验证。

先读取 harness_handoff_2026-10-08.md、harness_review_2026-10-08.md 和 temp/harness-review-2026-10-05/manifest.json，核对 git status/diff，保护已有未提交改动。参考仓库已经下载并固定 SHA，不要重复下载或重做已完成工作。

按交接优先级继续实际实施：可恢复 ReAct 生命周期 → UsageRecorder 持久化与完整性 → 行程组合上下文/压缩保真 → 按模型名称和任务质量反馈的主辅路由/协议 → 横向收尾与可复现实验框架。先查明真实调用链和故障边界，再修复并添加有意义的边界验证。保留 LangGraph、typed gates 和单一交付出口，每批更新审查报告。

按模型名称和任务类型优化；reasoning 使用 medium/low，不关闭；累计 Run 预算默认只计量、不限制，不重新加入隐式 Token/费用/调用限额。自主完成已授权工作，不要只给计划或反复请求继续。只有影响决策的缺失信息才向我提问。

不主动开子 agent，不 commit/push，不调用付费模型，不执行业务数据库迁移，不输出 config.yaml 或密钥。离线估算不代表真实缓存/成本/质量收益。将已完成修复、验证范围和仍需外部条件的事项分别说明。
```
