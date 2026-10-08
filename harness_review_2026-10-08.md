# JourneyPilot Harness：Token 计量、缓存与框架审查

日期：2026-10-08。基线：`5e08d829a04048c6f6dba86b191813e22825c106`。

参考代码：`temp/harness-review-2026-10-05/`（目录被 Git 忽略，包含固定 SHA 的 OpenAI Codex 与 DeepSeek Harness）

这轮工作的第一目标是让 Token 账本能够解释每一次模型请求，第二目标是让缓存和上下文策略可以用真实账单验证。当前配置按模型名称和任务类型工作：primary 是 `openai/gpt-6.1-sol`，推理档为 `medium`；fast 是 `deepseek/deepseek-v4.1-flash`，推理档为 `low`。模型调用不再关闭推理。DeepSeek V4 的 `medium` 会被模型策略归一为 `low`，因为该系列把 `medium` 映射为更高档位。

## 已完成的实现

### Token 计量已经统一为一条语义链

`src/travel_agent/models/usage.py` 现在同时读取标准 `usage_metadata` 和原始 `response_metadata`。它支持 Chat Completions、Responses 形状、DeepSeek cache hit、cache creation/write、流式终结 usage、SDK 长度错误和带 usage 的 HTTP 错误响应。

账本采用以下固定口径：

- `input_tokens` 是包含缓存读和缓存写的输入总量。
- `cached_input_tokens` 与 `cache_write_input_tokens` 是输入总量下的互斥子桶。
- `output_tokens` 已包含 reasoning output，`reasoning_output_tokens` 只是细分，不能再次计费。
- 原始供应商把输入拆成 exclusive input 与缓存桶时，适配层只补一次缓存桶。
- 标准适配器用 0 作为缺失占位、但原始总量为正时，0 会被视为未知，不会当作免费。
- 负数、布尔值、非整数数量、非法字符串、无穷值均被视为未知。
- 成功响应缺少 usage 时才使用离线估算，并标记 `estimated=true`；错误和取消响应不编造 Token。
- 流式响应使用最后一个累计 usage 快照，避免把每个累计 chunk 相加。

请求侧也记录了真实 wire payload 的离线估算：消息、角色、工具调用、工具参数、assistant reasoning replay、工具 schema、`response_format` 都进入估算。估算只用于上下文和诊断，API 返回的 usage 才是账单权威值。

### 成本公式修正为缓存读写互斥桶

现在的成本公式为：

```text
(input - cache_read - cache_write) * input_price
+ cache_read * cache_read_price
+ cache_write * cache_write_price
+ output * output_price
```

缺少计费关键字段、缓存桶超过输入总量、价格未命中或数量非法时，`cost_usd` 为 `null`，不会假造 0。历史行的既有 `cost_usd` 保持快照，无法重建的旧 cache-write 数量保持 `null`。

在本地价格配置对应的示例下，旧公式把 100,000 个全写入 Token 算作 `$0.20`，修正后为 `$0.25`；100,000 输入（40,000 read、30,000 write）加 20,000 输出的混合费用是 `$0.339`。reasoning 不会被重复加价。

本地模型价格覆盖已存在，本轮没有用公共价格替换它。若价格表声明写入单价与普通输入不同、而 API 不返回写入数量，费用保持未知；不能把这种响应认作“0 个写入”，也不能凭模型名称改写账户价格。

每次 router 调用尝试都有独立 `call_id`、`logical_call_id` 和 `attempt_number`。SDK 内建重试关闭，由 router 显式重试，因此失败尝试也会入账，且同一请求的重复落库幂等、内容冲突会拒绝。`finish_reason=length` 被保留，用于区分模型质量问题和输出被截断。usage 总量与输入/输出之和矛盾时会标记为 partial；非法缓存桶不产生看似正常的命中率。

### 运行预算改为观察模式

`run_budget.enforce_limits` 默认是 `false`，各调用、工具、输入 Token、输出 Token、费用和累计工具重试上限默认 `null`。因此历史的隐式 100 次调用、100 万输入 Token、5 美元等限制不再阻断正常项目运行；预算仍会记录消耗和完整性状态。

严格模式保留为显式选项，只有设置 `enforce_limits: true` 并提供上限时才启用旧守卫。并发调用的额度预留和下一次调用的费用预测尚未改造；本轮没有将它当作精确预算控制的保证。Deadline、并发通道、单次模型超时和结构化输出修复轮属于运行机制，不是本轮被取消的 Run 预算。

模型请求仍需发送一个 API 输出参数。它现在默认是 `65536`，是请求默认值，不是 Run 配额，也不是所有模型都必须支持的不可突破硬顶；调用方可以按部署模型选择更高的正整数。所有任务固定的 4096、8192、12288、16384 输出限制已经移除，任务只在确实需要时传递显式覆盖值。

### 缓存与上下文改造

- Research Packet 的 JSON schema 提前成为系统提示词的稳定长前缀。Token 修复阶段仅改变 run_id 的对照中，共同字符前缀由 326 增至 29,568；后续架构阶段进一步拆分消息，见下文。这些是字符结构验证，不是实测 cache hit。
- ContextBuilder、请求估算和 ToolExposureLedger 统一使用同一套离线 Token 估算器，并且不会在请求期间下载 tokenizer。
- `maps_text_search` 与 `maps_search_detail` 不再走缺少 TTL 的工作流本地结果缓存，改由 ProviderSnapshotCache 的 TTL、快照和调用审计统一处理；它们仍然可能命中短期快照，而不是无条件禁用缓存。
- ToolExposureLedger 记录 deferred/full 工具 schema 的初始组装量，并明确 `measurement_scope=initial_assembly`、`estimated=true`。这是一项优化诊断，不等于供应商实际节省的计费 Token。
- SSE usage 事件带 `call_id`，前端按 call_id 去重；缺失 Token 和缺失费用显示为占位状态，而不是 0。

## 数据库迁移

新增迁移：[0008_llm_usage_details.py](migrations/versions/0008_llm_usage_details.py)。它增加：

`cache_write_input_tokens`、`total_tokens`、`usage_complete`、`usage_source`、`logical_call_id`、`attempt_number`、`request_input_tokens_estimate`、`tool_schema_tokens_estimate`、`finish_reason`。

旧行标记为 `usage_source=legacy`、`usage_complete=false`；两侧 Token 都已知时回填 `total_tokens`，历史成本不重算。迁移脚本支持降级并保留原有行。

独立 PostgreSQL 14 临时集群已针对变更的 `run_llm_calls` 表验证：表 fingerprint、升级、降级、旧账单快照、cache-write 成本、重复 replay 幂等和冲突拒绝均通过。验证脚本是 `temp/harness-review-2026-10-05/verify_postgres.py`，不会连接项目数据库。完整 baseline 的 4 项 PostgreSQL 测试因项目数据库不可连接而跳过；独立验证只创建 `trip_runs` stub 与 ledger 表，不代表整套 pgvector schema 已通过集成验证。项目业务数据库尚未执行迁移，部署时应通过项目既有入口运行：

```bash
uv run python journeypilot.py migrate
```

## Harness 分层审查结论

当前结构可以保留五个责任边界：

1. **Run control** 负责 deadline、checkpoint、取消和可恢复状态。
2. **Model router** 负责按模型名选择推理档、协议参数、请求估算、显式重试和逐次计量。
3. **Tool gateway/cache** 负责工具权限、Provider snapshot、TTL、审计和重放。
4. **Typed workers/gates** 负责研究包、候选闭包、约束评估和质量门禁。
5. **Cost ledger/API** 负责持久账单、SSE 投影、历史查询和完整性提示。

Codex 的 session/context manager 提供了“状态更新与保留上下文分离”的参考；DeepSeek Harness 的 agent loop、runtime context、session 和 token meter 提供了“每轮尝试计量、运行时上下文和恢复状态分离”的参考。本项目保留现有 LangGraph、typed packet 和单一交付出口。

DSH 的 `inputTokens` 是未缓存输入，`cacheReadTokens`、`cacheWriteTokens` 另外相加；本项目的 `input_tokens` 包含缓存桶。因此借鉴其 attempt 生命周期、重放幂等和缺失状态，不能直接照搬它的加法。累计账单与当前上下文占用也要分开：一次 run 的累计输入可以远超模型窗口，压缩判断应看下一次请求占用。

仍需优先审查的结构问题：

- ReAct 循环仍在 worker 调用期间运行，工具曝光状态是 invocation 私有的内存状态，尚未成为可从 checkpoint 恢复的事件生命周期。需要定义 request、tool result、packet admission 各阶段的提交和重放边界。
- 行程组合仍通过兼容接口把动态背景追加在系统消息内，而且生成阶段存在按任务变化的 schema；本轮只完成三个研究 worker 的稳定合同拆分，组合节点需要单独审查。
- 工具定义虽然已固定初始顺序、激活只追加，但激活仍改变 tools 数组，跨调用可能因路径不同而形成不同定义前缀。不能承诺 append-only 能保证模型 API 的缓存命中。
- `UsageRecorder` 仍有 10,000 条进程内缓冲上限。它会计数 `dropped`，但该计数尚未进入汇总，也没有持久 spool；进程崩溃或长期落库故障时不能宣称能还原全部账单。
- embeddings 的 usage 尚未进入本 LLM ledger；当前报告范围是主辅 LLM，不包括本地 Qwen embedding 的外部计费。

## 架构实施进展：上下文与工具曝光

本批完成三个研究 worker 的接入，完整状态与模型输入视图的责任边界如下：

| 模块 | 责任与边界 |
|---|---|
| `memory/agent_context.py` | 用命名片段统一装配 anchor、preset、约束与天气；领域格式器保留各自职责，不截断受控约束 |
| `agents/research_packet_prompt.py` | 产出固定 system 合同与独立 runtime；同一 worker 的 run/task/时间/上限/推荐工具/背景变化不会改写 system |
| `memory/research_context.py` | 从 durable Research Packet 投影任务视图；不写回 packet，不承担事实准入 |
| `tools/exposure.py` | 从已过滤的工具白名单形成曝光计划；初始排序固定，单次 ReAct 激活只追加定义，不执行工具 |
| `agents/utils.py` | 运行模型和工具轮次；保留完整工作 transcript 与 authoritative Tool Gateway envelopes，供后续 packet 编译和修复 |

消息按 `system → history → 最新 research_runtime → 本轮任务/预检 → assistant/tool 轮次` 装配。稳定 schema 和合同位于第一条消息；工具目录放在第一条 system 的静态后段；搜索结果是独立 tool 消息；anchor、preset、天气和动态约束只在 runtime 注入一次。推荐工具放在 runtime，模型按其适用性选择，调用方不再通过重排 schema 表达推荐倾向。

投影的两种用途有独立合同 `journeypilot.research_context.v1`，不能当作提交的 Research Packet：

- **协调视图**：只选同 run、同 planning generation、当前 research queries 目的地范围和所需候选类型。保留身份、地址、日期、交通 endpoints/segments、事实值、单位、币种、状态、有效期与支持/冲突来源引用；去掉 source snapshot、excerpt 和重复索引。三类 worker 的自身候选不会被普通协调视图回灌。
- **补研视图**：只对 assignment 显式指定的候选或本任务未闭合 gap 提供自身 worker 的历史实体闭包。保留全部目标 facts，包括 missing/conflict、全部 links 对应 sources、原 snapshot/hash、field provenance 和 discovery lineage；排除其它实体。历史证据不能冒充本轮 Tool Gateway 查询结果。

同一候选出现在多个当前 generation 的历史包时，优先最新 fact revision、时间和 packet ID。Research Packet 在这里按增量记录处理：新包未列出旧候选不等同于删除；未来若增加实体撤销语义，应通过显式状态表达，不能靠提示词投影推断。无关目的地的 open gap 不会自行扩大上下文，显式指定的补研实体可以跨目的地。

工具曝光 session 私有，不会因上一轮激活污染下一次调用。Gateway 仍以 worker 原始白名单为执行边界；曝光不扩权。新增回归还确认研究 worker 持有同一份工作消息列表，能够在搜索与工具执行后读取完整 assistant/tool transcript 和 reasoning replay，工具执行的 activation_source、审计 ID 和 SSE 一致。

### 离线结构对照

`temp/harness-review-2026-10-05/architecture_probes.py` 使用测试中的强类型 fixture，包含两座城市、两个 generation、4 个候选及带人为页面填充的来源。它不读取部署配置、不调用模型。结果保存在同目录 `architecture-results.json`：

| 同一输入状态的序列化视图 | 字符数 | 共享离线 Token 估算 |
|---|---:|---:|
| 全量历史研究包 | 52,328 | 13,082 |
| 当前任务协调视图（2 个相关候选） | 9,092 | 2,273 |
| 指定单个实体的完整补研闭包 | 12,392 | 3,098 |

三个 worker 在动态输入变化时 system 完全相同；同一工具白名单反转输入顺序时初始 schema/catalog 完全相同，后续激活保留已有定义前缀。合成的 8 个工具定义首次装配估算为 full 1,352、deferred 432（含目录）；后续激活成本仍由各次模型请求计量。

这组数字只证明 fixture 上消除了重复与无关上下文。人为填充、任务过滤和序列化格式都会影响比例，不能外推生产成本、API cache hit、质量或延迟收益。

## 当前主辅模型分工与调整原则

当前分工是：

| 任务类型 | 当前档位 | 审查建议 |
|---|---|---|
| Research workers、意图归一化、候选评价、摘要/快速回答 | fast，low reasoning | 默认保留；研究/归一化/评价有 typed schema 和 gate，摘要与快速回答还需单独验证保真度 |
| 行程组合、跨候选约束仲裁、组合方案的模型生成 | primary，medium reasoning | 默认保留；需要全局一致性时才使用 |
| JSON/schema repair | 当前沿用调用任务档位 | 后续实验先比较 fast 修复与 primary 升级；升级仍需任务 gate 证明收益 |
| 恢复、补研、定向 gap 修复 | 按任务类型选择 | 只发送 gap 所需上下文；不要因“恢复”标签自动升级模型 |

应按模型名称和任务质量信号路由：schema repair rate、hard-constraint unknown/failed rate、候选证据闭包丢弃率、输出截断率、人工/确定性修复轮数和成功交付率。只有当升级模型降低了这些失败成本，增加的 reasoning Token 才值得。

模型档位与请求协议分别管理。当前 primary 用于无工具的组合调用，仍走 Chat Completions；如果后续让 `gpt-6.1-sol` 接手工具型研究，需先适配该模型支持的 Responses 工具协议，不能只替换模型名。传输的 `previous_response_id`、WebSocket 或增量消息也不代表历史上下文免计费。

## 全面的 Token 与缓存策略

下一轮实验应同时记录四个层次：

- **请求层**：wire input estimate、工具 schema estimate、动态消息 Token、输出上限、reasoning output。
- **供应商层**：inclusive input、cache read、cache write、output、usage 完整性、finish reason。
- **控制层**：每次尝试、逻辑调用、工具调用、修复轮、等待时间和取消原因。
- **交付层**：成功交付成本、质量门禁通过率、p95 延迟、截断率、重试/修复率。

缓存不能只看命中率。建议使用以下指标：

```text
weighted_cache_hit = sum(cache_read_tokens) / sum(input_tokens)
read_write_cost = cache_read_tokens * read_price + cache_write_tokens * write_price
successful_delivery_cost = total_cost / successful_deliveries
```

实验至少覆盖冷缓存/暖缓存、新 run/补研/恢复、简单/复杂约束、full/deferred tools。每组同时比较请求 Token、真实 cache read/write、成功交付成本、质量门禁、p95、修复轮和截断率。字符数变少只能证明本地估算变少，不能证明供应商 cache hit 提高；必须以 API usage 和稳定前缀命中结果确认。

目前已完成研究 worker 的稳定 system/runtime、assignment/gap Research Packet 投影和工具曝光模块。后续依次推进可恢复 ReAct 生命周期、usage 持久 spool、组合节点上下文与按模型名称/任务质量反馈的路由，然后用真实运行验证。没有付费模型 benchmark 前，不应承诺固定百分比的 Token 节省或质量提升。

## 验证结果与范围

Token 修复批次已通过：257 项选定后端测试、22 项前端测试、前端 TypeScript 类型检查、前端生产构建，以及独立 PostgreSQL 迁移/账本验证。

架构批次已通过：278 项选定后端测试（包含上一批计量/预算和新增 21 项上下文/工具边界测试）、Ruff、`git diff --check`、两份离线 probes。新增断言覆盖 system 稳定性与消息边界、上下文单次装配、full/deferred 工具排序、append-only 激活、重复激活与调用隔离、真实 Gateway/内存审计集成、worker transcript 保留、投影作用域/最新候选、时序与单位、交通多段换乘、三类 worker 的补研证据闭包和原状态不变。本批未修改前端或数据库，没有重复运行它们的验证。

离线 probes 位于 `temp/harness-review-2026-10-05/probes.py` 与 `architecture_probes.py`，参考仓库和验证范围见同目录 `manifest.json`。

本轮没有调用付费模型，没有执行项目业务数据库迁移，也没有用真实线上流量测量 cache hit、质量、p95 或成本下降比例。这些是下一轮实验的待验证事实。

## 源码与理论依据

| 固定参考 | 对本项目的启示 |
|---|---|
| [Codex client](https://github.com/openai/codex/blob/823ea830c0fd418b09ff02d36cad9a1fff66465b/codex-rs/core/src/client.rs)、[history](https://github.com/openai/codex/blob/823ea830c0fd418b09ff02d36cad9a1fff66465b/codex-rs/core/src/context_manager/history.rs)、[retained context](https://github.com/openai/codex/blob/823ea830c0fd418b09ff02d36cad9a1fff66465b/codex-rs/core/src/session/retained_context.rs) | 固定 request 属性、缓存路由与上下文状态；不能把会话传输优化当作少计费 |
| [DSH architecture](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/docs/architecture.md)、[agent loop](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/core/agent-loop/src/agent.ts)、[runtime context](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/core/agent-loop/src/runtime-context.ts) | 将模型请求、工具执行、session 事实和上下文装配分层 |
| [Codex context updates](https://github.com/openai/codex/blob/823ea830c0fd418b09ff02d36cad9a1fff66465b/codex-rs/core/src/context_manager/updates.rs)、[DSH runtime projection](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/core/agent-loop/src/runtime-context.ts) | 命名片段不跨显式消息边界；稳定 system 与变化 runtime 分别投影，本项目本批落实在三个研究 worker |
| [DSH turn usage](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/llm/token-meter/src/turn-usage.ts)、[usage projection](https://github.com/deepseek-ai/deepseek-harness/blob/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/llm/token-meter/src/usage-projection.ts) | 每次 attempt 计量、累计快照覆盖、缺失或矛盾的用量不能标作精确总额 |
| [OpenAI Prompt Caching](https://developers.openai.com/api/docs/guides/prompt-caching)、[Prompt Caching 201](https://developers.openai.com/cookbook/examples/prompt_caching_201)、[DeepSeek KV cache](https://api-docs.deepseek.com/zh-cn/guides/kv_cache/) | 重用完整相同前缀；静态 schema 与工具顺序稳定后才衡量实际命中，不能靠冗长填充提升指标 |
| [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[DeepSeek request](https://api-docs.deepseek.com/api/create-chat-completion/) | reasoning 档位和输出长度由模型能力决定；推理 Token 也占输出额度 |
| [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)、[RouteLLM](https://arxiv.org/abs/2406.18665) | 最小充分上下文、按质量反馈做路由；以成功交付成本和质量衡量收益 |

建议把后续改动逐项做 A/B 对照：稳定工具顺序、上下文投影、压缩和模型升级分别改变一个变量。优化目标是在通过硬约束与事实门禁的前提下降低交付成本；缓存率、Token 数和单次请求价格是解释变量。

## 续批 A：可恢复 worker / ReAct 提交边界（2026-10-08）

已建立并推送只读基线分支 `study`，指向远端本轮修改前 `main` 的 `5e08d829a04048c6f6dba86b191813e22825c106`。后续修改与分组提交只在 `main`。当前用户已授权适时 commit/push 与付费验证，交接中的旧限制不再适用。

真实调用链是 `chat lease → LangGraph with_run_control → worker 确定性预检 → streaming_react_loop → execute_tool → ToolGateway / ProviderSnapshotCache / audit → packet repair → typed worker update → Candidate Gate → 单一 finalizer`。LangGraph checkpoint 与业务库事务仍不原子。

本批新增 `run_worker_journals`（迁移 0009）与 typed serializer、版本 CAS、活 lease fencing。在模型请求前提交准入状态；完整 assistant/tool calls 与 opaque reasoning replay 在执行工具前提交；Gateway 完整信封在取消检查和 transcript 提交之前保存；worker typed 输出在交回 Pregel 前保存。崩溃后同合同 invocation 重放结果，已完成模型轮次与工具不重跑。范围包括确定性预检，补研/意图变化进入不同 scope。AIMessage ID 在提交前固定，避免重放追加重复消息。

修复取消发生于工具完成之后导致结果丢失、`ask_user` 和 deadline 退出留下未配对 tool calls、worker 将 RunCancelled 吞为 schema failure 的路径。流没有 finish 时不把半段文本当完整模型输出。恢复工具仍受当前 allowlist 与 lease 限制；已开始但未提交结果的只读查询允许重新执行，副作用调用返回 outcome unknown 等待对账，不重试或降级。模型请求已开始但未得到完整回复也可能重新调用，此窗口需要 usage admission 持久化如实记录，下一批处理。

验证：新增 4 项恢复故障边界测试、相关工具测试共 19 项通过；原 278 项 suite 加新测试中 281 项通过，1 项离线 SQL 测试仅接受 `CREATE TABLE IF NOT EXISTS` 而拒绝普通版本化 `CREATE TABLE`，已修正其匹配合同并复验。独立 PostgreSQL 14 验证升级/降级、typed AIMessage roundtrip、CAS、stale lease 拒绝、事务回滚与新表 fingerprint 均通过。未迁移业务数据库。

部署需要经既有 `journeypilot migrate` 入口升级到 0009；journal 不能替代 Research Packet admission 或交付 store 的幂等提交。

## 续批 B：持久 usage outbox 与确认边界

移除 10,000 条 deque 挤出语义；批大小仅限制一次取批，不丢记录。生产 singleton 使用 `usage.spool_path`（默认 `data/usage/outbox.sqlite3`）的 SQLite WAL + synchronous FULL、0600 文件。记录不包含提示词、工具原文或凭据。每次 router attempt 在请求前先持久准入；进程死亡留下的 started 记录在存活 PID 检查后转为 interrupted / missing usage，不编造 Token。finish 更新同一 call_id。

`drain` 改为读取，只有 PostgreSQL 完整提交之后才 `ack` 精确 payload。DB 不可用、部分提交、commit→ack 崩溃和多进程重复 drain 均安全重放。独立后台 `UsageFlushService` 在无 SSE / run 时也补记；单条冲突隔离，其他 run 可继续落库。旧账单价格快照不随配置变化重算，同一 capture 的新价格不再让幂等重放产生冲突。未知用量和 pending / 写盘失败均通过 `capture_complete`、`record_failed` 等字段进入汇总与前端；读盘异常不终止 SSE。磁盘故障时保留 volatile 记录并明确不完整，不能承诺此后再崩溃的恢复。

新增配置和生成文档同步。部署需要把 `data/usage` 挂载为持久卷；销毁本地卷会丢失未落库记录，跨主机恢复不自动传输此卷。本 outbox 是持久补记机制，不是累计 Run 限額。

验证：7 项新 outbox 故障测试，相关计量、配置、worker 回归合计 105 项通过；前端 22 项通过，TypeScript 与生产构建通过；独立 PostgreSQL 14 ledger 迁移/回放/冲突与历史价格快照验证通过。累计 Run 预算仍默认仅计量，reasoning 保持 medium/low。
