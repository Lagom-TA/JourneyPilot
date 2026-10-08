# JourneyPilot Harness：Token 计量、缓存与框架审查

日期：2026-10-08。基线：`5e08d829a04048c6f6dba86b191813e22825c106`。

**续接状态**：原始批次记录保留在前半部分；本轮 A–E 已实施，最新结果与限制见续批 E。`study` 已固定并推送到上述基线，所有新修改在 `main` 分组提交。当前授权允许 commit/push 与付费测试，原交接中的相反限制已被用户后续指令覆盖。

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

## 续批 C：组合合同与压缩保真

组合的 system 只保留固定角色、阶段合同和规则；任务、允许撰写领域、required kinds、候选及 capabilities、天气/约束/anchor、repair context 和当前动态 schema 放入独立 `composition_runtime`。顺序是 system → history → 最新 runtime → 本轮任务。修复移动候选仍携带本轮 runtime。原动态 response schema 继续限定当前候选枚举和子任务形状，没有为了缓存把所有任务强行合成一个 schema；服务器 typed parse、mutation 和 fidelity gates 保留。

压缩保留旧 anchor 全部明确约束，并且更具体的用户原话不被子串去重丢弃；LLM 的约束只有能追溯到用户原话或旧 anchor 才被采纳。无有效 summary / 模型异常时抛失败，CompactionService 不推进 CAS 边界，删除原 800 字降级片段被当作成功摘要的路径。anchor 不再按字符截断；会话裁剪以完整 user→assistant/tool 回合为单位。

快速回答按下一次请求计算窗口：计入实际配置的输出预留，以及新追加的 RAG / 工具 / 最新问题。固定受控背景本身超窗口会给明确错误，不截断硬约束；这与累计 Run Token/费用限额无关。摘要自然语言仍是模型生成，确定性保护主要覆盖明确约束，未声称任意信息都已得到语义等价证明。

验证：10 项新的组合/压缩合同测试通过；prompt、intent control/composition/ranking、退化日志等相关回归共 107 项通过；Ruff 与 diff check 通过。任务与约束变化时同阶段 system 完全相同，动态 schema/runtime 不同；故障摘要不会被保存成成功。

## 续批 D：任务质量路由与协议分离

新增独立 `TaskKind / QualityFeedback / TaskRoute` 策略与 `TaskLLM` 适配，按配置的精确模型名判断协议。研究工具默认 fast/low；组合/全局仲裁默认 primary/medium；无工具 schema/semantic 修复在已有 typed schema 失败、截断或硬门失败信号下升级 primary。证据缺失的 unknown / closure gap 返回补研动作，不用升级伪造支持。恢复/补研标签不参与升级，Run 预算也不参与路由。

生产已接入三个研究 worker、组合、快速回答、摘要、请求/约束归一化及 Candidate Gate 的语义评价；请求归一化的 typed reject 后续尝试可升级，候选语义批次只有无有效 matches/schema 时升级一次，unknown 本身不会重试。Research Packet 的 schema-only repair 可升级，确定性 provider selection 收口仍保持 fast。决策日志含 task、精确 model、tier、reasoning、protocol、reason/action；ledger 继续逐 attempt 保留实际 model/tier/usage。

OpenAI Docs 本次已实际抓取 [GPT-6.1 Sol 官方页面](https://developers.openai.com/api/docs/models/gpt-6.1-sol)：明确 `low/medium` 支持且 `none/minimal` 不支持；Chat Completions 无工具调用，工具要用 Responses。本项目没有把 primary 直接替换成工具研究模型；路由与底层 client 均阻止 Sol 的 Chat 工具请求。Sol schema-only 修复把历史工具结果变成明确的数据观察，保留内容，移除 foreign opaque reasoning 与 active tool protocol。没有引入 Responses 传输、自动关 reasoning 或累计限額。

验证：新增 13 项路由/协议测试及相关回归 172 项通过；接入实际归一化和候选修复后相关回归 164 项通过；另新增真实 TaskLLM 的候选 schema failure→primary repair 断言。策略升级能否降低最终交付成本仍需端到端真实质量实验，不能从路由测试推断。

## 续批 E1：恢复、缓存与账单收尾

实际故障验证发现：只用语义输入哈希识别 worker invocation，会把图新调度的相同任务当作上一次恢复，重复返回旧失败。journal scope v2 增加 LangGraph 注入的 `__pregel_task_id`，它在同一 pending task 的 checkpoint resume 时稳定，在新 dispatch 时改变。typed 输入摘要继续区分合同变化。新增真实 LangGraph 回归证明相同任务的新调度会执行第二次，并能从 failed 转 completed；恢复仍使用原任务的已提交结果。

另外收紧五处提交边界：完成结果的缓存重放也检查活 lease；journal I/O 异常统一成 `JournalConflict` 传播；保存并恢复每轮成功/失败/能力判定计数；恢复迭代上限时初始化内容；禁止跨 invocation 复用旧 graph-state tool envelope。ProviderSnapshotCache 继续在 Gateway 白名单和 manifest 判定之后检查 TTL/provider validity，并为命中生成本 run 的审计记录。调用内缓存也排除 Gateway 标记的 side-effecting 结果；两次相同写请求会产生两个执行和审计，不被旧 envelope 合并。已执行但未提交的写操作仍只返回 outcome unknown 等待对账。

usage SQLite 同 ID 冲突检查与写入使用 `BEGIN IMMEDIATE`，避免两个进程同时读取空行后互相覆盖；表结构检查和升级也在该锁内，4 个并发 API 实例升级旧文件不再因重复 ALTER 退回 volatile recorder。started owner 加 hostname + Linux PID 启动时间，避免 PID 被复用后未完成调用永远停留在 started。ledger 幂等身份增加规范化时间戳、latency、TTFT，保留此前历史价格快照规则。空 ledger 若仍有待落库记录，其 Token 总量为 null，前端显示不完整；不再伪装成已完成零用量。

journal 保留到所属 TripRun 删除，由 FK `ON DELETE CASCADE` 清理；本次未给可恢复数据增加定时 TTL。它可能保留较大的完整 transcript/envelope，应随 run 的既有数据生命周期管理。usage outbox 是 ledger 成功提交后逐项 ack，没有隐式累计 Run 配额。embeddings 不属于此 LLM ledger；本地 Qwen embedding 不计成外部模型费用。

验证：全量后端 **477 passed / 116 skipped**；跳过项依赖项目 PostgreSQL/pgvector 条件。前端 **23 项通过**，TypeScript 与生产构建通过。Ruff 与 diff check 通过。独立 PostgreSQL 14 重验 journal 和 ledger 的升级/降级、fingerprint、CAS、活 lease、typed roundtrip、幂等/冲突、历史价格快照；并新增真实 `AsyncPostgresSaver + WorkerJournalStore + with_run_control` 的并行 worker 故障恢复，覆盖 journal→Pregel pending write 之间及两 worker 完成→合并节点之前。两种边界均不重复 worker 执行、消息或 typed 研究包，合并节点只成功执行一次。

上述图实验使用强类型 fixture 与替代合并节点，不代表生产 Candidate Gate admission 或 Trip Delivery 已完成端到端验证；独立数据库只建立所需 stub 与 checkpoint/journal/ledger 表，**业务数据库未迁移**。LangGraph 当前 typed serializer roundtrip 已通过，升级其依赖时仍需重验枚举和 Pydantic 合同。

## 续批 E2：可复现实验与最终范围

新增 `scripts/harness_experiments.py` 的离线矩阵、显式付费文本/工具协议校准及 JSONL 分析；`models/experiments.py` 对 call_id 去重、拒绝冲突，按 trial 聚合加权 cache read、p95、截断/修复和成功交付成本。没有完成 usage 或最终交付时保留 null，失败 run 的费用仍进入成功交付成本分子。live 验证失败或 usage 缺失会非零退出。故障矩阵在 `scripts/harness_recovery_experiment.py`；原独立 ledger 验证材料已复用并归档为 `scripts/verify_usage_postgres.py`，隔离 recorder，避免读取实际 outbox。

24 个离线请求 fixture 与 24 个 fake-model/真实-Gateway 恢复场景已完成；后者全部通过。六次已授权付费调用中，4 次无工具约束 JSON（Sol medium / Flash low）以及 2 次 Flash synthetic 工具协议均通过，usage 完整、无截断，按配置价格合计 **$0.0016389**；实际 cache read rate **0**。未重新运行已完成的付费 probes。此次精简 8 工具 fixture 的 deferred 初始估算反而比 full 多 108 Token，说明按需曝光有目录和额外轮次开销，初始定义变小的旧 fixture 不能代表普遍收益。

复现命令、依赖版本、已脱敏 API/fixture 结果和精确范围已进入版本控制：[实验记录](docs/review/harness-experiments-2026-10-08.md)、[验证数据](docs/review/harness-verification-2026-10-08.json)。固定 Codex/DSH SHA 未变化，study 保持基线。本轮可在现有环境完成的架构审查、修复和验证已收尾；项目数据库/pgvector 集成、真实 packet admission 和交付端到端、缓存/质量/成功交付成本收益仍需部署环境验证，不能由本次离线或协议结果推断。

## 续批 F1：正式部署入口审查（阶段记录）

本轮起点：main 与远端均为 `aa5a2da6d16589c27534bbf31fb566098b310ff8`；study 与远端均为 `5e08d829a04048c6f6dba86b191813e22825c106`，保持固定。工作区已有 Responses/Chat 配置与传输测试改动，完整保留。`config.md` 是已有的本地凭据说明，新增忽略规则，不提交其内容；Docker build context 同时排除真实配置、凭据、参考仓库和运行数据。

部署审查发现 Compose 没有挂载 `data/usage`，容器重建可能丢掉未确认账单。已声明 `usage_data:/app/data/usage`；镜像预建非 root 可写的目录。唯一 Python 虚拟环境改为 Docker 内 `/opt/journeypilot`，构建按 `uv.lock --frozen`，不再调用旧宿主机 test-venv。历史验证与固定参考继续复用。

环境实测：WSL 默认 Docker socket 不存在，Docker Desktop 的 Linux socket 只有 root 可以访问。通过 WSL root Docker 客户端连接已有 Desktop daemon；此前只有其他项目 PostgreSQL 容器及卷，没有 JourneyPilot 业务卷。通过现有 Compose 创建本项目 PostgreSQL/pgvector 与 Redis，保留其他容器。迁移前只读检查确认 PostgreSQL **18.6**、`travel_agent` 的 public schema 无业务表。API 镜像构建进行中，尚未执行迁移与正式应用验证。

Responses 审查发现缺少 terminal status 校验：SDK 可返回 `status=incomplete` 的部分正文，流提前 EOF 也可能被当成功。新增明确异常，拒绝不完整产物，已返回 usage 仍按错误尝试入账；`max_output_tokens` 映射成账本 `finish_reason=length`。这些改动尚待 Docker 中回归，不能列为验证通过。

当前本地部署配置是 Sol `gpt-6.1-sol` / Responses / medium 与代理别名 `deepseek-flash` / Chat / low；代理 `/models` 仅列出 `deepseek-flash`、`deepseek-v4-flash` 等，没有用户指定的 `deepseek-v4.1-flash`。已提出精确 ID/映射确认，未把别名宣称为 v4.1。模型身份不明影响正式模型验证结论，环境与代码审查继续推进。累计 Run 预算仍 observe、各上限 null。

## 续批 F2：真实迁移、协议与失败账单

通过 Docker 内既有 `api-entrypoint.sh → journeypilot.py config validate → migrate → main.py` 已正式启动。迁移前 CLI dry-run 为 `migrate_empty`、0 行，随后升级到 **0009_worker_journal**；PostgreSQL 18.6 的 vector/pgcrypto、受管表指纹、LangGraph checkpoint 合同校验通过。数据卷与唯一环境 `/opt/journeypilot` 已实测，usage SQLite 为 WAL、0600、UID 10001。复制已有验证材料曾使 usage 目录归 root，已校正卷权限并重启；没有把这段故障称为完整计量。

真实代理拒绝非流式 Sol Responses（400 `stream must be true`），新增 `responses_streaming` 配置，业务 `ainvoke` 聚合完整流后返回，并记录实际 transport stream 标志。Sol medium 修复后的真实短请求成功。精确 `deepseek-v4.1-flash` 被代理明确拒绝（422 model not supported），指定版本尚未验证。用户继续后，临时采用已有 `deepseek-flash` 别名开展运行链验证，版本保持未确认，不将其报告为 v4.1。

首轮完整后端/真实 pgvector 回归：**563 passed / 8 failed / 0 skipped**（配置来源 suite 单独执行，避免 Compose 数据库 env 覆盖测试 YAML）。8 个失败均因运行镜像缺少与 PostgreSQL 18 匹配的 pg_dump/pg_restore。已通过 PGDG HTTPS + signed-by 安装 client 18，备份/恢复 **11/11** 通过。新增 Responses/usage/数据库维护回归 **84 passed**，配置 **30 passed**，Ruff 通过；前端 **23 passed**、类型与构建通过。单套环境不再调用历史宿主机 venv。

真实失败 SSE：`trip_73e7ee37f5d94d2e`（精确 v4.1 422），产生 run_failed/error、业务状态 failed，3 个模型错误尝试完整落库，usage/费用保持未知，outbox pending=0。发现失败分支虽然结算账本却不发送汇总；已补齐 run_failed producer→public projection→前端 SET_RUN_COST_SUMMARY，并新增未知/待落库合同回归。真实后续失败 `trip_49e3ad1a066e4eb3` 已收到结算汇总：1 次 alias 调用、真实 4,271 输入/1,899 输出，capture_complete=true，费用未知。已有配置 `model_pricing=[]`，本轮不编造账单价格或替换用户价格表。

真实受控单日行程在 planner 失败：硬约束「不安排酒店住宿」只有 composition/projection 阶段，却被分配给未调度的 accommodation researcher，触发 ownership 校验。已把仅组合/投影的约束归属 itinerary planner，研究/admission/ranking 阶段仍归领域 worker，并保证活跃意图 owner 被调度。修复与计划门恢复验证进行中；此时尚未产生 Research Packet 或 Delivery Bundle，不能列为端到端通过。

## 续批 F3：真实审批恢复与同城证据范围

仅组合/投影意图 ownership 修复后，真实 Run `trip_5840a393a0e04c1c` 在 26.5 秒到达 plan_gate，业务状态 awaiting_input、checkpoint 恢复策略、公共审批 SSE 均已保存。重启 API 后通过正式 gate_decision approve 续跑；destination worker 调用真实 OSM/网页 Provider，模型选取修复后保存 3 个 Visit 候选及其来源、事实和 provenance。只读 checkpoint 审计确认该 typed packet 已持久化，累计 8 个模型调用 reported usage 完整，pending=0、capture_complete=true，金额仍 null。

续跑在 transport worker 输入校验失败：planner 遇到同城无长途 Leg 时给它分配空 Provider scopes，而 worker 要求非空责任范围。修复为公共交通/灵活市内交通的服务器 scope，跨城继续保留精确 outbound/return Leg。为复用已完成研究，旧 checkpoint 的已知「同城初始空列表」可从锁定身份重建范围；缺失范围、跨城空范围、定向补研空范围仍拒绝，不修改 checkpoint 或关闭 typed gate。新增 planner/恢复合同回归，Docker 唯一环境中的 agent_behavior **96 passed**，Ruff 通过。

修复后尝试续跑时，原 Run 授权于 09:29:58 UTC 的既有十分钟 deadline 已耗尽（观察 elapsed=829.94 秒），边界收口至 delivery_quality_gate；无 workspace 因 composition_window_exhausted 拒绝。没有新增模型调用，没有为了验证重置 deadline。该终态与 scope 缺陷分别归因；当前从正式 API 新建同输入 Run 验证完整交付，尚不能声称 Delivery Bundle 或端到端通过。

## 续批 F4：正式交付、进程崩溃与账单故障

`trip_9bcd381f336b41ef` 已通过真实 Provider → typed Research Packet → Candidate admission → composition/artifact/intent/delivery gates → 唯一 delivery_finalizer → Delivery Bundle/SSE。正式审批后使用 OSM、高德与 Open-Meteo，Sol medium / Responses 和 Flash alias low。Run 最终 completed，公共 `delivery_ready`、`run_terminal`、Bundle GET 与完成审计均指向 `bundle_52723103f64b4a95e6414e58`；行程含 2 次参观、1 次午餐和 2 条真实步行路线，无住宿/跨城交通。该结果证明运行和持久交付链路；历史建筑主题的证据仍为 unverifiable，不能当作全部需求事实核验通过。

研究执行期间对本项目 API 发 SIGKILL 并经既有入口重启。过期租约由 sweeper 收敛为 interrupted（09:49:47 UTC），随后显式 API resume（09:49:52）续跑，未重置 deadline、未自动产生付费续跑。崩溃后与完成后的 journal 比较：目的地 11 条、住宿 1 条已提交工具的哈希与 audit ID 全部相同，目的地完成结果保留；pending workers 继续完成。两次在途模型调用恢复为 interrupted/usage missing，保持未知，不伪装为 0；最终 outbox pending=0、capture_complete=true。

真实审计继续发现并修复三处问题：

- typed 排除意图单独创建不需要的住宿/跨城研究。brief v3 / capability plan v2 仅由正向需求和受控行程责任创建领域，负约束仍分配 owner 并进入组合/gate；确有过夜、跨城或正向领域需求时仍研究。agent_behavior **98 passed**。
- deadline/channel 在 provider 之前拒绝的请求也写入 usage admission，造成虚假的 missing 调用。admission 改到通道和窗口接受以后、实际 provider 协程内执行；invoke/stream 的过期回归均确认零 HTTP、零 outbox 条目。历史 Run 的原始账单未改写：25 条记录中除 2 次真实崩溃未知，还保留 1 条旧代码的研究窗口前置拒绝记录，应按此解释历史计量。
- 已审计的主题偏差只在浏览器需求落实摘要存在，正式报告/PDF 的 important_notes 丢失。现在相同中文解释进入报告与公共 fulfillment summary，保留“尚未核实”，不输出内部 intent/gap/status 词汇；跨 fidelity→report 回归通过。旧 Bundle 未重写，新 Bundle 使用修复后的投影。

独立真实账单故障 Run `trip_41c25fc35b564c75`（组件集成，非行程端到端）：停止仅本项目 PostgreSQL 后调用真实 Flash，返回 45 输入/72 输出 Token；落库失败，WAL outbox 留 1 条、capture_complete=false、未 ack。数据库与最终 API 镜像恢复后自动补记；同 call_id 两次显式幂等重放仍只有 1 行，pending=0、reported usage 完整、金额 null。测试 Run 已结束。

正式控制 API 在 1 次真实归一化调用在途时接受取消：`trip_9b66f2b6d2e74036` 收口为 cancelled，SSE run_cancelled、租约 released、无 Bundle，pending=0。现有取消合同为协作式，本轮等待在途模型完成后于 **32.35 秒**收口；返回的 4,271 输入/5,351 输出全部落库，没有取消后新增调用。不能将这个结果宣称为即时中止上游计费。

最终镜像已重新构建并经正式入口对非空业务库启动。新增报告测试的 fixture 修正后，最终完整后端 **585 passed / 0 skipped**，配置来源独立 **30 passed**，合计 **615 passed**；Ruff 通过。正常交付与持久化收尾见 F5。

## 续批 F5：最终镜像正常交付与持久性收尾

正式 Run `trip_2dba16b29d29498f` 审批后在 **342.57 秒**完成，Bundle 为 `bundle_a57fda02d314da54a24dffbc`。初始计划只有 destination → itinerary，验证排除意图不会凭空调度酒店/跨城研究；后续由 typed 定向补研取得精确相邻路线。最终包含 2 次参观、1 条真实步行段，无住宿/跨城交通。Research Packets 保存在真实 checkpoint，candidate、artifact、intent fidelity 与 delivery quality 的终态均通过，唯一 finalizer 持久提交；公共 delivery_ready、run_terminal、Bundle GET 身份一致，checkpoint next=[]。

该 Run 的 **14 次调用**全部为 reported usage：**212,362 输入 / 28,206 输出 / 13,881 reasoning / 106,752 cache-read Token**，missing=0、pending=0、capture_complete=true。供应商未报告 cache-write，价格表为空，cache-write 和金额仍为 null；不能把 Token 完整性写成费用完整性，也不能由本次 cache-read 推断优化收益。SSE 的工具曝光节省仍是 initial_assembly 本地估算，不是 API 或整次交付 A/B。

历史建筑主题仍缺证据，按既有有界 fidelity 修复策略披露后交付，未更改 typed gates 或放宽策略。公共需求摘要与报告 important_notes 均保留“尚未核实：以历史建筑为主题安排游览内容”。最终还有非阻断的 missing_dining_day；本例不证明所有事实质量或餐饮覆盖均满足。正式 PDF API 返回 200，3 页 / 54,600 bytes，使用 pypdf 抽取文字确认主题偏差说明存在；网页入口与 readiness 均为 200。

部署维护还发现 `/app/backups` 位于容器可写层，已有 CLI 的正式迁移备份可能随容器重建丢失。确认该目录为空后新增 `backups_data:/app/backups`，没有覆盖旧备份。通过既有 CLI 创建真实业务库备份：revision 0009、pg_dump/client 18、custom dump 2,133,620 bytes，manifest 文件 checksum、非空 dump 与 pg_restore list 检查通过。随后 force-recreate API，经正式入口再次启动；同一备份 checksum 校验、Bundle GET、14 条完整账单、WAL outbox pending=0 和 PDF 导出再次通过。usage 文件 0600，服务与备份卷由 UID 10001 使用。没有在业务库执行覆盖式 restore。

最终验证镜像唯一 venv 是 `/opt/journeypilot`；本批五个源码文件与运行镜像 SHA256 一致。依赖为 LangGraph 1.1.3、langchain-openai 1.1.11、OpenAI 2.29.0、asyncpg 0.31.0、psycopg 3.3.4、Pydantic 2.12.5、ReportLab 5.0.0、pypdf 6.14.2。前端本批未再改动，复用 **23 项**、类型与生产构建通过的结果；固定参考与旧矩阵没有重跑。

可评审的脱敏证据归档于 [正式验证数据](docs/review/harness-formal-verification-2026-10-08.json)，原始 SSE、checkpoint/source 快照、PDF 和备份本体只保留在忽略目录/本项目卷，不进入 Git。当前仍未验证：指定 `deepseek-v4.1-flash` 的真实版本（代理 422，运行使用版本未确认 alias）、实际费用金额、缓存/质量/成本 A/B、复杂跨城/过夜生产行程、其他供应商与真实业务备份完整 restore 演练。可选语料种子未提供，中文词法检索为 simple；readiness 明确报告，未用假语料填充。现有 10 分钟 deadline 与协作式取消合同保持原样，未增加累计 Run Token、费用或调用限额。
