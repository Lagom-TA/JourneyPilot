# 架构总览

JourneyPilot 是一个**单机、单进程、单用户**的自托管旅行规划应用。这一句是全部架构决定的
前提：没有账户系统（[ADR-0001](../adr/ADR-0001-local-single-profile.md)）、没有外部消息队列
（[ADR-0004](../adr/ADR-0004-durable-local-jobs.md)）、没有多 API worker。

```text
浏览器 (React/Vite)
  │  SSE + REST
  ▼
FastAPI 进程
  ├─ LangGraph 工作流（确认需求 → 串行研究 → 组合行程 → 交付）
  ├─ 进程内 asyncio worker（durable command / background job 的消费者）
  ├─ 受限线程与子进程（PDF 渲染、文档解析、本地推理）
  └─ MCP stdio 子进程（外部数据源）
       │
       ▼
PostgreSQL + pgvector（最终事实）        Redis（缓存与快照）
```

## 仓库目录

- `backend/travel_agent/`：后端源码。
- `backend/tests/`、`backend/migrations/`、`backend/scripts/`：测试、迁移与维护脚本。
- `backend/mcp/`：仓内 MCP 服务及其独立 Node 依赖。
- `backend/travel_agent/resources/providers/`：模型连接模板（preset）。
- `frontend/`：前端源码；构建产物默认写入 `backend/static/`，由 API 服务。
- `infra/`：容器构建、Compose 与基础设施脚本。
- `docs/`：文档；根目录 `run.sh` 是本地开发启动器。

私有配置 `config.yaml`、`.env`、`.venv` 和运行时数据在仓库根目录；后端项目清单集中在
`backend/pyproject.toml`。

## 代码按职责归属

源码按实际职责归属组织，合同与实现放在各自领域内；调用方直接导入符号的定义模块，包的
`__init__.py` 不汇总这些符号。以下路径相对于 `backend/travel_agent/`。

- `planning/state.py`：快答与规划共用的图状态与 reducer；`planning/graph.py` 定义节点、边、
  条件路由与按 checkpointer 区分的编译缓存；`planning/workflow.py` 负责流式运行、checkpoint
  合同拒绝与运行上下文。节点名与展示名分别在 `planning/nodes.py`、`planning/presentation.py`。
  `planning/execution.py` 维护截止窗口分表，`planning/trace.py` 维护流式观测合同。
- `planning/requirements/`：受控旅行身份、入口守卫、当前需求文字、自然语言研究方案、批准与
  追加要求。`constraints/` 分开参数、记忆来源、抽取与展示；`understanding/` 承载需求理解与
  追问门；`approval.py` 提供计划门交互；`amendments.py` / `supplements.py` 维护变更。
- `planning/research/`：研究方案、任务分派、供应商责任与结果、packet 与候选目录组装。
  `dispatch.py` 按执行计划逐个派发 worker，收齐后由 `assembly.py` 的 `build_candidate_catalog`
  构建 `RecommendationCatalog`；`destination/`、`transport/`、`accommodation/` 各自拥有身份绑定
  与工作节点；`failure_protocol.py` 固定失败前缀语义。
- `planning/itinerary/`：行程草稿生成、地点解析、住宿基点、开放时间与已选供应的物化。
  `composition.py` 让模型基于 catalog 写出完整草稿，`materialize.py` 物化为 `TripWorkspace`；
  `connectors.py` / `adjacency.py` 补齐接驳，`day_design.py` / `day_capacity.py` 控制日程密度。
- `planning/delivery/`：事实、来源、引用、报告与地图投影，以及交付持久化。`assembly.py` 组装
  Bundle，`projection_builder.py` 生成报告/地图/来源索引，`persistence.py` 在同一事务里提交
  Bundle、读回确认、完成状态与终态事件，`finalizer.py` 负责重试与失败转换。PDF 排版属于交付，
  渲染器就绪检查属于 integrations。
- `conversation/`：路由、输入安全、回答展示与会话合同。`graph.py` 拥有快答图缓存，`workflow.py`
  负责流式更新与生命周期；`answer/` 分开汇率上下文、实时工具上下文和快答节点；`chat/` 负责
  请求准备、费用记录、消息保存、租约、断连清理与已持久化交付读取。
- `api/`：HTTP 参数、错误映射、公开投影与 SSE 编码。`api/schemas/` 与 `api/routes/trip_runs/`
  按资源划分，不承担工作流执行、运行取消或交付事务；聊天请求合同归 `conversation/chat/contracts.py`。
- `bootstrap/`：组件构建、唯一注册、启动/关闭、后台任务装配与诊断（`bootstrap/jobs.py`）。
- `runtime/`：运行与命令合同、状态转换、租约、恢复、后台任务、并发、预算、时限、事件缓冲与
  时间函数。恢复只读取持久化的 Run 记录、checkpoint 与交付 Bundle，不依赖 planning。
- `integrations/`：地点、路线、航班、铁路、汇率和天气供应商访问，以及供应商就绪检查；
  适配器不导入规划状态。`storage/` 负责持久化与缓存，`memory/` 负责偏好、生命周期合同与
  记忆提取任务。
- `config/`：`models.py`（唯一 schema）、`loader.py`（加载与来源）、`providers.py`（preset 能力）、
  `redaction.py`（脱敏）、`capabilities.py`（依赖检查）。`utils/` 只放通用坐标、文本、JSON 与
  日志脱敏工具；`cli/` 按命令拆分，`cli/main.py` 只负责启动顺序与分派。

## 三条边界

**一、最终事实在库里，内存只是缓存。** 关掉程序之后还应该发生的事，都有一行。
`trip_run_commands`、`background_jobs`、`trip_run_executions` 是三个例子；进程内的 registry
只负责把延迟从「一个轮询周期」降到「立刻」。

**二、Schema 只由迁移改。** API 进程不执行 DDL，只做一次只读的结构合同校验
（[ADR-0002](../adr/ADR-0002-versioned-migrations.md)）。

**三、每条高成本通道都有显式上限，而且上限可以被看见。** 容量、并发、时间、费用四类边界
各有配置项与读数（[ADR-0006](../adr/ADR-0006-resource-budgets-and-isolation.md)）；运营者从
`GET /api/health/ready` 与 `journeypilot doctor` 读它们。

## 一次请求走过什么

0. **入口与工作台**：表单表达正式规划；自然语言由模型判断普通提问还是正式规划。点击开始
   规划立即建 TripRun 并进入旅行工作台；普通问答走快问快答，展示在同一工作台。
1. **会话整理**：`scope_clarifier` 做入口的会话压缩，不在这里断言旅行身份是否齐全。
2. **需求理解**：`understanding_agent` 以 primary 档模型带真实工具协议理解原文、表单信息与
   历史问答：能查到的用工具查（联网资料、真实地点），只有值得用户决定的问题才通过
   `understanding_gate` 暂停提问；回答回到同一模型继续理解。信息充分后模型给出受控旅行身份
   （地点来自工具查到的真实记录）并写回 Run 行。
3. **需求文字**：`requirements_preparer` 把用户原话、理解问答和后续补充按顺序保存为当前需求
   文字并推进规划代际；用户原话不做逐条语义审批，也不展示单独的参数确认页。
4. **研究与安排方案**：`research_plan_generator` 让模型根据基础信息和当前需求写出简短方案，
   并为目的地、交通、住宿和行程组合写下任务；`minimum_delivery_draft_builder` 生成
   `MinimumDeliveryDraft`；`destination_geo_resolver` 准备目的地边界；`trip_summary_card_brief`
   生成摘要；`planner` 把任务交给各角色。
5. **方案确认**：`plan_gate` 暂停等待用户 approve / supplement / retry / cancel。关闭
   `run_control.plan_gate_enabled` 时，新的完整调研会在创建 Run 前被拒绝（409
   `plan_gate_disabled`），快问快答不受影响。确认时封存 Draft、`RunDeadlineSnapshot` 与
   `RunBudgetSnapshot`；修改转成 `IntentAmendment`，进入当前需求文字并失效旧方案与旧研究结果。
6. **研究**：批准并封存预算后，`weather_context_builder` 获取规划天气；研究按
   `destination_researcher` → `transport_researcher` → `accommodation_researcher` 串行推进，
   `dispatcher` 逐个派发，后一位角色通过上游研究视图读取前序成果。Worker 接收基础信息、当前
   需求和自己的任务，在自身工具范围内决定查询，并按运行租约、取消与预算控制调用工具，返回
   带字段和来源的 `ResearchPacket`。
7. **候选目录**：Worker 完成后，`dispatcher` 收齐 packet 并构建 `RecommendationCatalog`；
   catalog 保留 generation 一致性检查，拦截过期产物。
8. **组合**：`itinerary_planner` 读取 catalog，由模型直接写出完整行程草稿，再物化为
   `TripWorkspace`。服务端负责结构解析、身份绑定与时间线物化，不做内容质量裁决；接驳缺口
   由服务端按真实路线补齐。
9. **交付**：`delivery_projector` 从同一 Workspace 生成报告、地图与来源索引；`delivery_finalizer`
   原子提交唯一的 `DeliveryBundle`。工作台、报告、PDF 与来源列表都来自这份记录。

计划门修改和运行中追加要求先进入当前需求，由理解阶段结合已有基础信息与最新表达处理，随后
生成新的研究设想。已交付旅行的后续输入先结合当前安排判断：问答读取现有结果，局部调整复用
已保存的候选与组合能力，基础条件变化进入新的理解与方案确认。修改使用关联原旅行的新 Run；
成功交付后切换到新结果，旧结果保留，失败时仍可读取。

## 从哪里继续读

- 决定与它们的替代方案：[`../adr/`](../adr/)
- 什么必须成立、谁保证、哪个测试覆盖它：[`../invariants.md`](../invariants.md)
- 配置字段、默认值、环境变量：[`../configuration.md`](../configuration.md)（生成物）
