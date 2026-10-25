# 架构总览

JourneyPilot 是一个**单机、单进程、单用户**的自托管旅行规划应用。这一句是全部架构决定
的前提：没有账户系统（[ADR-0001](../adr/ADR-0001-local-single-profile.md)）、没有外部
消息队列（[ADR-0004](../adr/ADR-0004-durable-local-jobs.md)）、没有多 API worker。

```text
浏览器 (React/Vite)
  │  SSE + REST
  ▼
FastAPI 进程
  ├─ LangGraph 工作流（研究 → 门 → 编排 → 交付）
  ├─ 进程内 asyncio worker（durable command / background job 的消费者）
  ├─ 受限线程与子进程（PDF 渲染、文档解析、本地推理）
  └─ MCP stdio 子进程（外部数据源）
       │
       ▼
PostgreSQL + pgvector（最终事实）        Redis（缓存与快照）
```

## 仓库目录

- `backend/travel_agent/`：后端源码，直接位于 backend 下，不再套一层 src。
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

- `planning/state.py`：快答与规划共用的唯一图状态，保留全部 checkpoint 字段和 reducer。
- `planning/requirements/`：受控旅行身份、请求与意图合同、归一化、规则编译及覆盖验收。
  归一化分别由 clauses、prompts、model、fallback、deterministic 模块负责；verification
  分开处理实体、规则、覆盖报告与工作区复验。
- `planning/research/`：调研计划、供应商责任与结果、候选准入、排序和选择政策。
  `admission/` 区分证据、身份、住宿、评分和准入汇总，地点检索政策位于 `place_search.py`。
- `planning/itinerary/`：日程容量、地点解析、住宿基点、开放时间和已选供应的物化。
  `mutations/` 分开定义变更合同、时间线校验、具体变更、结果构造、天气操作与撤销；
  `apply.py` 只按具体变更类型分派，不承担变更算法。
- `planning/delivery/`：事实、来源、引用、报告与地图投影，公共序列化、候选重新准入、
  天气刷新和工作区变更的原子服务。PDF 的报告排版属于交付，字体与渲染器就绪检查属于 integrations。
- `conversation/`：路由、输入安全、快答的来源绑定、信息标签、回答展示及会话标题和消息合同。
- `runtime/`：运行与命令合同、状态转换、租约、恢复、后台任务、并发和时间函数。
  恢复只读取持久化交付审计，不依赖 planning；后台任务处理器在 `builders.py` 装配。
- `integrations/`：地点、路线、航班、铁路、汇率和天气供应商访问，以及低层供应商合同与就绪检查。
  供应商适配器不导入规划状态或候选准入政策；地点原始响应缓存由 `storage/place_search_cache.py` 维护。
- `memory/`：偏好、生命周期合同和记忆提取任务；`storage/` 负责持久化与缓存。
- `config/capabilities.py`：配置所需依赖的可用性检查；`utils/` 仅保留通用坐标、距离、文本、JSON 和日志脱敏工具。

图、agent 节点、panel 和 API 用例编排尚保留原入口目录；它们直接消费上述领域模块，
不通过旧目录转发。目录迁移不改变公开 API、持久化版本、哈希、节点名称或业务判断。

## 三条边界

**一、最终事实在库里，内存只是缓存。** 关掉程序之后还应该发生的事，都有一行。
`trip_run_commands`、`background_jobs`、`run_execution` 是三个例子；进程内的 registry
只负责把延迟从「一个轮询周期」降到「立刻」。

**二、Schema 只由迁移改。** API 进程不执行 DDL，只做一次只读的结构合同校验
（[ADR-0002](../adr/ADR-0002-versioned-migrations.md)）。

**三、每条高成本通道都有显式上限，而且上限可以被看见。**
容量、并发、时间、费用四类边界各有配置项与读数
（[ADR-0006](../adr/ADR-0006-resource-budgets-and-isolation.md)），
运营者从 `GET /api/health/ready` 与 `journeypilot doctor` 读它们。

## 一次请求走过什么

1. **路由**：简单问题走快问快答；多日行程进研究工作流。
2. **合同化**：一次归一化同时产生 clause ledger、`IntentSpec` 与 Constraint Pack，
   并封装为唯一 `RequestContract`。
3. **编排**：从合同确定性投影 `ResearchBriefV2`、`ResearchQueryPlan`、
   `CapabilityPlan` 与 `MinimumDeliveryDraft`；每个 hard intent 都有所有者与验收标准。
4. **授权**：用户在计划门确认后封存 Draft，同时封存 `RunDeadlineSnapshot` 与
   `RunBudgetSnapshot` —— 时间与钱的上限从这一刻起对这个 Run 固定。
5. **研究**：并行 Worker 按 assignment 中的 Query ID 执行 Intent Primary 与 Structural
   查询；只有前序查询不足且政策允许时才执行 Generic Fallback。每个 Research Packet
   绑定当前 `PlanningGeneration`、Query Plan 和服务端生成的 Candidate Discovery Lineage。
6. **候选门**：Admission 验证事实与硬 Constraint；Candidate Intent Evaluation、Ranking
   和 Selection 分别判断意图匹配、分层顺序与本次候选集合。缺少高优先级意图候选时，
   Candidate Gate 生成 Targeted Repair Query。
7. **编排**：Itinerary Planner 只消费 `CandidateSelectionPlan` 允许的候选，按
   `CompositionRule` 填充合法槽位，并记录每次确定性后处理的 `CompositionMutation`。
8. **验收**：Intent Fidelity Gate 检查数量、频率、时段、顺序、硬排除和解释要求；缺口回到
   对应所有者，预算耗尽的义务变成公开偏差，禁止型硬规则不能降级。
9. **交付**：一次原子提交写出唯一的 v10 `DeliveryBundle`；Workspace 保存意图快照、选择计划、
   变更台账和覆盖报告，所有面向用户的界面都是公共安全投影。

默认选择是确定性的。只有明确的 Diversity/Alternatives Intent 才进入受控 Explore；seed 只在
已通过事实准入和硬合同的近分候选之间生效，因此同 seed 可回放，硬要求不会随探索变化。

计划门修改和运行中追加要求不直接改 prompt。它们先变成 `IntentAmendment`，
回到同一个 Request Contract 边界，再按影响范围失效旧产物。

## 从哪里继续读

- 决定与它们的替代方案：[`../adr/`](../adr/)
- 什么必须永远成立、谁保证、哪个测试钉住它：[`../invariants.md`](../invariants.md)
- 配置字段、默认值、环境变量：[`../configuration.md`](../configuration.md)（生成物）
