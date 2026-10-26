# 架构总览

JourneyPilot 是一个**单机、单进程、单用户**的自托管旅行规划应用。这一句是全部架构决定
的前提：没有账户系统（[ADR-0001](../adr/ADR-0001-local-single-profile.md)）、没有外部
消息队列（[ADR-0004](../adr/ADR-0004-durable-local-jobs.md)）、没有多 API worker。

```text
浏览器 (React/Vite)
  │  SSE + REST
  ▼
FastAPI 进程
  ├─ LangGraph 工作流（确认需求 → 并行调研 → 组合行程 → 交付）
  ├─ 进程内 asyncio worker（durable command / background job 的消费者）
  ├─ 受限线程与子进程（PDF 渲染、文档解析、本地推理）
  └─ MCP stdio 子进程（外部数据源）
       │
       ▼
PostgreSQL + pgvector（最终事实）        Redis（缓存与快照）
```

## 仓库目录

- `backend/travel_agent/`：后端源码，直接位于 backend 下。
- `backend/tests/`、`backend/migrations/`、`backend/scripts/`：后端测试、迁移与维护脚本。
- `backend/mcp/`：仓内 MCP 服务及其独立 Node 依赖。
- `backend/travel_agent/resources/providers/`：公开的模型连接模板。
- `frontend/`：前端源码；构建产物默认写入 `backend/static/`，由 API 服务。
- `infra/`：容器构建、Compose 与基础设施脚本。
- `docs/`：文档与截图；根目录 `run.sh` 是唯一开发启动器。

私有配置 `config.yaml`、`.env`、`.venv` 和运行时数据仍在仓库根目录，
后端项目清单集中在 `backend/pyproject.toml`，两者不混放。

## 后端职责归属

源码按实际职责归属组织，合同与实现放在各自领域内，不使用统一的 entities、services
或 guardrails 导出层。调用方直接导入符号的定义模块，包的 `__init__.py` 不汇总这些符号。
以下路径相对于 `backend/travel_agent/`。

- `planning/state.py`：快答与规划共用的唯一图状态，保留全部 checkpoint 字段和 reducer。
- `planning/graph.py`：规划图的节点、边、条件路由与按 checkpointer 身份区分的编译缓存。
  `planning/workflow.py` 负责流式运行、checkpoint 合同拒绝和运行上下文，不重复构图。
- `planning/requirements/`：受控旅行身份、入口守卫、请求与意图合同、归一化、批准与追加要求。
  `planning/requirements/constraints/` 分开规范参数、条目、来源、语义抽取、冲突处理、装配、加载和展示；
  快答复用同一套约束。`planning/requirements/normalization/` 是唯一归一化边界，
  `planning/requirements/approval.py` 提供计划门交互。
- `planning/research/`：调研计划、分派、供应商责任与结果、查询计划、packet 与 catalog 组装。
  `planning/research/destination/`、`planning/research/accommodation/`、`planning/research/transport/`
  各自拥有范围、发现、身份绑定和工作节点；交通调研的 `planning/research/transport/rail/` 保留班次选择、
  工具授权和证据绑定，原始铁路访问仍属于 integrations。
  `planning/research/dispatch.py` 在 worker 收齐后构建 `RecommendationCatalog`，模型直接读取 catalog 组合行程。
  `planning/research/brief_builder.py` 计算简报，`planning/research/brief_node.py` 负责其图节点边界；
  `planning/research/prompts.py` 维护共享调研提示合同。
- `planning/itinerary/`：行程草稿生成、地点解析、住宿基点、开放时间和已选供应的物化。
  `planning/itinerary/composition.py` 让模型基于 catalog 写出完整草稿，`planning/itinerary/materialize.py`
  物化为 `TripWorkspaceV2`。`planning/itinerary/mutations/` 分开定义编辑合同、时间线校验、具体变更、
  结果构造、天气操作与撤销；`planning/itinerary/mutations/apply.py` 只按具体变更类型分派，不承担变更算法。
- `planning/delivery/`：事实、来源、引用、报告与地图投影，公共序列化、天气刷新和工作区变更的原子服务。
  `planning/delivery/projection_builder.py` 生成报告、地图与来源索引，`planning/delivery/assembly.py`
  组装 Bundle，`planning/delivery/persistence.py` 在同一事务中提交 Bundle、读回确认、完成状态与终态事件，
  `planning/delivery/finalizer.py` 负责重试及失败转换。checkpoint 是另一条持久化通道，不能替代已提交
  Bundle。PDF 排版属于交付，渲染器就绪检查属于 integrations。
- `conversation/`：路由、输入安全、回答展示及会话合同。
  `conversation/compaction.py` 只测量和整理会话；`conversation/answer/` 分开汇率上下文、实时工具上下文
  和快答节点。`conversation/graph.py` 拥有唯一快答图缓存，`conversation/workflow.py` 负责流式更新、
  完整状态和生命周期回调。
- `conversation/chat/`：请求准备、费用记录、消息保存、请求自身的租约、断连清理和已持久化交付读取。
  `conversation/chat/execution.py` 协调这些职责，展示状态与工具、文本、进度事件分开维护。
- `api/`：HTTP 参数、错误映射、公开投影和 SSE 编码；`api/schemas/`、`api/routes/trip_runs/` 按资源划分，
  不承担工作流执行、运行取消或交付事务。聊天请求合同归 `conversation/chat/contracts.py`。
- `bootstrap/`：组件构建、唯一组件注册、启动、关闭、后台任务装配与诊断。
  `bootstrap/startup.py` 在数据库合同通过后启动写入任务，`bootstrap/shutdown.py` 先停止任务并释放租约，
  再关闭连接池。
- `runtime/`：运行与命令合同、状态转换、租约、恢复、后台任务、并发、预算、时限、事件缓冲和时间函数。
  恢复只读取持久化的 Run 记录、checkpoint 与交付 Bundle，不依赖 planning；后台任务处理器在
  `bootstrap/jobs.py` 装配。
- `integrations/`：地点、路线、航班、铁路、汇率和天气供应商访问，以及低层供应商合同与就绪检查。
  供应商适配器不导入规划状态；地点原始响应缓存由 `storage/place_search_cache.py` 维护。
- `memory/`：偏好、生命周期合同和记忆提取任务；`storage/` 负责持久化与缓存。
- 预设的合同归 `planning/requirements/`，种子归 `config/seeds/`，持久化归 `storage/`，
  提示上下文归 `conversation/preset_context.py`，显式发布归 `config/publication.py`，没有聚合的 preset 包。
- `config/models.py`、`config/loader.py`、`config/providers.py`、`config/redaction.py` 分别定义配置模型、
  加载、供应商能力与脱敏，调用方直接导入定义模块；`config/loader.py` 保留唯一的延迟配置缓存。
  `config/capabilities.py` 检查配置所需依赖；`utils/` 仅保留通用坐标、文本、JSON 和日志脱敏工具。

图节点、约束和运行封装直接归属上述领域，不保留 agents、workflows 或 panels 转发目录。
`planning/weather/node.py` 负责天气图节点，`planning/presentation.py` 负责节点显示名；
`planning/costs/estimate.py` 保留预算节点，`planning/trace.py` 维护流式观测合同，
`storage/checkpoint_pruning.py` 负责 checkpoint 保留清理。CLI 的参数解析、输出与各维护命令分别归属
`cli/arguments.py`、`cli/output.py` 和对应命令模块，`cli/main.py` 只负责启动顺序与分派。
公开 API、持久化版本与节点名称独立于模块路径；模块路径不提供兼容导出层。

## 三条边界

**一、最终事实在库里，内存只是缓存。** 关掉程序之后还应该发生的事，都有一行。
`trip_run_commands`、`background_jobs`、`trip_run_executions` 是三个例子；进程内的 registry
只负责把延迟从「一个轮询周期」降到「立刻」。

**二、Schema 只由迁移改。** API 进程不执行 DDL，只做一次只读的结构合同校验
（[ADR-0002](../adr/ADR-0002-versioned-migrations.md)）。

**三、每条高成本通道都有显式上限，而且上限可以被看见。**
容量、并发、时间、费用四类边界各有配置项与读数
（[ADR-0006](../adr/ADR-0006-resource-budgets-and-isolation.md)），
运营者从 `GET /api/health/ready` 与 `journeypilot doctor` 读它们。

## 一次请求走过什么

1. **路由**：简单问题走快问快答；多日行程进入 planning 工作流。
2. **入口与合同化**：`scope_clarifier` 确认受控旅行身份；`request_contract_normalizer`
   把当前要求、会话上下文与个人约束归一为 clause ledger、`IntentSpec` 与 Constraint Pack，
   封装为唯一 `RequestContract`。
3. **编排**：`research_brief_builder` 从合同投影 `ResearchBriefV2`；
   `minimum_delivery_draft_builder` 生成 `MinimumDeliveryDraft`；`destination_geo_resolver` 与
   `weather_context_builder` 准备目的地坐标与规划天气；`trip_summary_card_brief` 生成摘要；
   `planner` 由纯函数生成 `ResearchQueryPlan`、`CapabilityPlan` 与 `execution_plan`。
4. **计划确认**：`plan_gate` 强制暂停，等待用户 approve / edit / supplement / cancel；
   `run_control.plan_gate_enabled` 必须开启，否则 Run 直接失败。确认时封存 Draft、
   `RunDeadlineSnapshot` 与 `RunBudgetSnapshot`，时间与费用上限从这一刻起固定。
   修改转成 `IntentAmendment`，回到同一个合同边界。
5. **研究**：`dispatcher` 按 `execution_plan` 扇出 `destination_researcher`、
   `transport_researcher` 与 `accommodation_researcher`。Worker 按 assignment 中的 Query ID
   执行 Provider 查询与 RAG 工具调用，返回带字段和来源的 `ResearchPacket`。
6. **候选目录**：Worker 完成后，`dispatcher` 收齐 packet，调用 `assembly.py` 的
   `build_candidate_catalog` 构建 `RecommendationCatalog`；
   catalog 保留 generation 与 revision 一致性检查，拦截过期产物。
7. **组合**：`itinerary_planner` 读取 catalog，由模型直接写出完整行程草稿，再物化为
   `TripWorkspaceV2`。服务端负责结构解析、身份绑定与时间线物化，不做内容质量裁决；
   接驳、用户编辑与撤销记录在 mutation history 中。
8. **交付**：`budget_estimate` 清理不受支持的总额字段，不调用模型或 Provider；
   `delivery_projector` 从同一 Workspace 生成报告、地图与来源索引；`delivery_finalizer`
   原子提交唯一的 `DeliveryBundle`。工作台、报告、PDF 与来源列表都来自这份记录。

计划门修改和运行中追加要求不直接改 prompt。它们先变成 `IntentAmendment`，
由控制节点 `intent_amendment_router` 路由，回到同一个 Request Contract 边界，
再按影响范围失效旧产物。

## 从哪里继续读

- 决定与它们的替代方案：[`../adr/`](../adr/)
- 什么必须成立、谁保证、哪个测试覆盖它：[`../invariants.md`](../invariants.md)
- 配置字段、默认值、环境变量：[`../configuration.md`](../configuration.md)（生成物）
