# JourneyPilot 现状架构说明与代码审查报告

日期：2026-08-26。代码基线：`main @ 5fbb2b29`。
行号基准：除注明外，所有 `file:line` 相对 `src/travel_agent/`，为审查当日实际所见。

---

## 1. 这份报告是什么

这是一次对 JourneyPilot 全部 Agent 相关代码的现状审查。它回答三个问题：这个 Agent 架构有哪几个大环节；每个环节结束后路由到哪些下游；每个环节内部处理信息的流程是什么。在此之上，它给出一份经源码逐条验证的工程缺陷清单，和一份与 codex-rs、openpi 的代码工程层对照。本轮只记录，不改代码。

方法：三轮多代理静态阅读。第一、二轮由 17 个读代码代理分子系统产出笔记；第三轮由 4 个分析代理交叉复核——路由表逐条回源码核对、信息流以 `entities/state.py` 为底本重建、审查发现逐条验证（验证不成立的候选单列"已排除"）、工程对照锚定三个仓库的实际源码；最后一个批评代理找出材料缺口，其中可当场补上的已用源码补齐。全程零测试运行、零代码执行，所有结论基于静态阅读与 grep。这意味着第 8 节的严重度分级是推断而非复现，报告在相应位置注明了这一点。

与既有文档的关系：`docs/architecture/overview.md` 讲部署形态，`docs/adr/` 讲已做出的选择，`docs/invariants.md` 讲什么必须永远成立，`docs/design/agent-workflow.md` 是撰写中的规范，`docs/design/comparative-study.md` 是设计哲学层的对照（其 §4.4 已定案的四条 `last_error` 协议缺陷，本报告不重复，只在关联处引用）。根目录 `AGENT-ARCHITECTURE.html` 是上一轮产出的运行图谱页面。本报告与它们的差别：这里的路由表、信息流、发现清单全部经过第二遍独立核对，并且覆盖了此前没人写过的快答路径、交付后编辑、证据链端到端。

参考仓库版本锚定：codex 读取自 `/Users/lagom/Downloads/codex-main/codex-rs/`（审查期间该目录从 `~/Code/` 移至 `~/Downloads/`），openpi 读取自 `/Users/lagom/Code/openpi/`，读取日期均为 2026-08-26。

---

## 2. 软件总览

JourneyPilot 是单机、单进程、单用户的自托管旅行规划应用（ADR-0001、ADR-0004）。它的交付物不是一段对话，是一份可执行的行程：itinerary、地图、天气、来源、报告、PDF 互相一致，硬要求不被静默违反，不确定的结论保持可见的不确定。核心实现是一张 LangGraph 状态图加一圈确定性服务，模型只在少数可校验的位置说话。

### 2.1 入口是四路分流，不是两路

一条用户消息进来，先经过一次 fast 档模型调用做意图分流（`services/route_intent.py:161`）。路由枚举是四值（`entities/trip_input.py:133-137`）：`TRIP_PLANNING`、`TRIP_REFINEMENT`、`DESTINATION_DISCOVERY`、`FAST_ANSWER`。只有前两者进深度研究图（`api/routes/chat.py:185-188`）——目的地发现走的是快答图，这一点与直觉相反，值得记住。分流判不出意图时不给默认路线，直接 503（`chat.py:178-182`，注释原文："分流是回答的前提，不是它的装饰"）。

### 2.2 两张图

深度研究图：22 个节点、16 组条件边，定义在 `workflows/travel_planning.py:517-758`。全文只有一个 `interrupt()`（计划门）和两个正常终点。第 4 节全景展开。

快答图：单节点图（`workflows/fast_answer.py:30-35`），`START → fast_answer_agent → END`，两条无条件边，零条件边。节点体 771 行（`agents/fast_answer/node.py`），第 5.8 节展开。

两张图共用同一个 `TravelAgentState` 和同一层 `with_run_control` 包装；用户画像与记忆抵达模型的通道也只有一条（Constraint Pack），快慢共用（`panels/constraint.py:2153-2156` 逐字声明）。

---

## 3. 大环节：图内七段，图外一段

深度路径的骨架可以概括成一句话：**先把话变成合同，合同经人批准后封存时间与钱，然后在墙钟窗口内研究、组合、验收，最后一次原子提交交付**。按节点归属切成七段，加上 Bundle 落库之后的交付后编辑段，共八个环节：

| 环节 | 含节点 / 模块 | 一句话 |
|---|---|---|
| A. 入口分流 | 路由判定（图外）+ `scope_clarifier` | 四路分流；clarifier 只量会话大小并按需压缩，缺受控身份即抛错，不问用户 |
| B. 合同段 | `request_contract_normalizer` → `research_brief_builder` → `minimum_delivery_draft_builder` → `destination_geo_resolver` → `weather_context_builder` → `trip_summary_card_brief` → `planner` | 一次模型归一化产出合同三件套，其余全是确定性投影：简报、能力计划、最小交付草案、地理、天气、摘要卡 |
| C. 授权 | `plan_gate` | 唯一的人在环阻塞点：批准即封存 Draft + 时间窗 + 预算，修改额度一次 |
| D. 研究环 | `dispatcher` ↔ 3 个 researcher ↔ `candidate_gate`（`artifact_gate` 参与回边） | 唯一带循环的环节：dispatcher 扇出，candidate_gate 归并候选并决定补研 |
| E. 组合 | `itinerary_planner` | 三相组合（骨架 → 物化连接器 → 整体重组），全图唯一用 primary 模型的节点，五个上游都汇到它 |
| F. 验收与交付 | `artifact_gate` → `intent_fidelity_gate` → `delivery_quality_gate` → `budget_estimate` → `delivery_projector` → `delivery_finalizer` | 串行验收链，缺口沿回边退回；通过后确定性投影 + 原子提交 |
| G. 横切 | `intent_amendment_router` + `with_run_control` 包装层 | 运行时修订的插队边覆盖 21 个节点的出边；包装层做取消、窗口短路、交付后丢弃 |
| H. 交付后编辑（图外） | `workspace_v2_service` + `workspace_v2_mutations` + `candidate_readmission` + `weather_bundle_refresh` | Bundle 封版后的用户编辑、候选再准入、天气刷新，约 4000 行，不在图上 |

环节 H 此前不在任何架构叙述里，但它真实存在且体量不小：`entities/workspace_v2_mutations.py` 1820 行 + `services/candidate_readmission.py` 815 行 + `services/weather_bundle_refresh.py` 806 行 + `services/workspace_v2_service.py` 596 行。`travel_planning.py` 全文没有 `candidate_readmission` 的 import——它是 Bundle 已封版之后的独立入口。要点在 5.9 节：同一份 `TripWorkspaceV2`，图内组合与图外编辑是两套互不复用的校验实现，唯一挂钩点是每次编辑都追加一条 `CompositionMutation`（`created_by="user_edit"`）进同一个台账。

---

## 4. 运行图全景

本节的三张表全部经第二遍逐条回源码核对（核对基准 `travel_planning.py` 全文 + 每个 `route_after_*` 函数的实现文件）。图规模：22 个 `add_node`，3 条固定边（含 START），16 组条件边；唯一 `interrupt()` 在 `travel_planning.py:359`；图内没有任何节点用 `Command` 跳转（`Command(resume=…)` 只出现在 `astream` 的恢复入口 `:882`）。递归上限 250（`:140`，注释：让失控自转环在秒级失败，而不是耗到墙钟截止）。

### 4.1 节点全表（22 个）

类别口径：确定性投影 = 节点体内无模型调用；模型调用 = 节点体内经 `get_model_router()` 拿 LLM；门 = 职责是准入判定并写 `*_route` 字段；人在环 = 会把控制权交回图外。

| # | 节点 | 实现（file:line） | 类别 | 职责 |
|---|---|---|---|---|
| 1 | `scope_clarifier` | `agents/scope/node.py:133` | 确定性投影 | 量会话大小按需压缩；无受控身份抛 `ScopeIdentityError`（`:160-165`） |
| 2 | `request_contract_normalizer` | `agents/scope/request_contract_normalizer.py:63` | 模型调用（fast，`:84`） | 自然语言 → `RequestContract`/`IntentSpec`/`PlanningGeneration`，并清空修订队列（`:162`） |
| 3 | `research_brief_builder` | `agents/scope/research_brief_builder.py:14` | 确定性投影 | 合同 → `ResearchBrief` + `CapabilityPlan`（全文 27 行） |
| 4 | `intent_amendment_router` | `agents/orchestrator/intent_amendment_router.py:11` → `workflows/intent_amendments.py:79` | 门（策略路由） | 逐条受理运行时修订，决定回哪个节点续跑 |
| 5 | `minimum_delivery_draft_builder` | `workflows/minimum_delivery_draft.py:290` | 确定性投影 | 建未封存的最小交付种子（`planning_authorized=False`，`:272`） |
| 6 | `destination_geo_resolver` | `workflows/weather_context.py:20` | 确定性投影 | 从受控身份取坐标，"never re-geocode or guess"；全图唯一同步 def 节点 |
| 7 | `weather_context_builder` | `workflows/weather_context.py:50` | 确定性投影（外部 API） | 拉天气上下文；内部无模型调用（`services/weather_context_builder.py` 379 行 grep 零命中） |
| 8 | `trip_summary_card_brief` | `agents/summary_card/node.py:111` | 确定性投影 | brief → 摘要卡，纯字符串裁剪 |
| 9 | `planner` | `agents/orchestrator/planner.py:67` | 确定性投影 | 生成 `execution_plan`/`agent_assignments`；无模型调用 |
| 10 | `plan_gate` | `travel_planning.py:327`（图文件内唯一节点体） | 人在环（`interrupt()` `:359`） | 计划批准门：approve / edit / supplement / cancel，修改额度 1 次（`:129`） |
| 11 | `dispatcher` | `agents/orchestrator/dispatcher.py:58` | 确定性投影 | 推进计划步、判组内完成度、写 `next_agent`；唯一扇出边界 |
| 12 | `candidate_gate` | `agents/orchestrator/candidate_gate.py:1938` | 门 + 模型调用（fast，`:1968`） | 候选准入/排名/选择/缺口补研；四道门里唯一调模型的 |
| 13 | `artifact_gate` | `agents/orchestrator/artifact_gate.py:195` | 门（确定性） | packet 身份完整性与内容失败判定 |
| 14 | `intent_fidelity_gate` | `agents/orchestrator/intent_fidelity_gate.py:51` | 门（确定性） | 硬意图覆盖校验；`never_violate` 违规直接抛 `DeliveryContractViolation`（`:82-87`） |
| 15 | `delivery_quality_gate` | `agents/orchestrator/delivery_quality_gate.py:610` | 门（确定性） | 交付质量缺口；无 workspace 且窗口/预算尽则硬失败（`:625-636`） |
| 16 | `destination_researcher` | `agents/destination_researcher/node.py:1344` | 模型调用（fast）+ 人在环 | 目的地研究；唯一 `can_ask_user=True` 的 worker，触发即 HALT（`:1622-1643`） |
| 17 | `transport_researcher` | `agents/transport_researcher/node.py:1872` | 模型调用（fast） | 交通研究；也承载组合期的结构性连接器补研（`run_control.py:659-681`） |
| 18 | `accommodation_researcher` | `agents/accommodation_researcher/node.py:787` | 模型调用（fast） | 住宿研究 |
| 19 | `itinerary_planner` | `agents/itinerary_planner/node.py:2954` | 模型调用（primary） | 三相组合；全图唯一 primary 节点，所有 `composition_repair` 的落点 |
| 20 | `budget_estimate` | `workflows/budget_estimate.py:139` | 模型调用（fast） | 估总花费；查不到就不写，从不让交付失败（`travel_planning.py:620-621`） |
| 21 | `delivery_projector` | `workflows/delivery_projection.py:34` | 确定性投影 | 从通过门的 facts 投影报告/地图/来源 |
| 22 | `delivery_finalizer` | `workflows/delivery_finalizer.py:455` | 确定性投影 | 原子落库 Bundle |

模型分层实测：primary 只被 `itinerary_planner` 用；fast 被 normalizer、三个 researcher、`candidate_gate`、`budget_estimate`（以及图外的 `route_intent`）用；其余 15 个节点零模型调用。22 个节点无一例外都包 `with_run_control`（`travel_planning.py:532-597`）。

### 4.2 路由全表

固定边只有三条：`START → scope_clarifier`（`:600`）、`scope_clarifier → request_contract_normalizer`（`:655`，clarifier 已无 HALT 出口）、`request_contract_normalizer → research_brief_builder`（`:601`，不查修订，否则修订循环自锁）。

其余全部是条件边。第一优先级统一是修订插队：**除上述两条固定边外，每个节点的出边都先查 `pending_intent_amendments`，非空即转 `intent_amendment_router`**。下表省略这条公共分支，只列各自的业务分支。

| from | 条件（谓词） | to | 证据 |
|---|---|---|---|
| 合同段 6 处边界 + `budget_estimate` + `delivery_projector` | 无修订 | 各自的固定下游（brief→draft→geo→weather→card→planner→plan_gate；estimate→projector→finalizer） | `:602-619` 循环注册 |
| `delivery_finalizer` | 无修订 | **END**（正常终点之一） | `:622-629` |
| `plan_gate` | `plan_gate_decision.action ∈ {amendment, projection_amendment_pending}` | `request_contract_normalizer`（整条合同链重跑） | `:454-456` |
| `plan_gate` | 否则（approve） | `dispatcher` | `:457` |
| `dispatcher` | `next_agent` 非法值 | 收敛 `to_check` → `artifact_gate`（log error，不静默进模型路径） | `dispatcher.py:178-183` |
| `dispatcher` | `next_agent == "to_check"` | `artifact_gate` | `dispatcher.py:185-186`；映射 `:701` |
| `dispatcher` | `next_agent == "candidate_gate"` | `candidate_gate` | `dispatcher.py:188-189` |
| `dispatcher` | `dispatch_group` 且组内 pending > 1 | `[Send(node, state) …]` 并行扇出 | `dispatcher.py:209-213` |
| `dispatcher` | `dispatch_group` 且 pending 恰 1 | 该 worker | `dispatcher.py:214` |
| `dispatcher` | `dispatch_group` 但组空/计划无效 | fail-closed `to_check`（log） | `dispatcher.py:198-206, 216-226` |
| `destination_researcher` | `next_agent == "HALT"` | **END**（ask_user 中断，正常终点之二） | `travel_planning.py:464-465`；触发 `node.py:1622-1643` |
| `destination_researcher` | 否则 | `dispatcher` | `:466` |
| `transport / accommodation / itinerary_planner` | 无修订 | `dispatcher`（fan-in；组合完成后也不直达验收，必须绕经 dispatcher） | `:642-650` |
| `candidate_gate` | `research_closed` 且非结构性连接器轮 | 一切非 passed 强制折成 `passed` → `dispatcher` | `candidate_gate.py:2789-2791` |
| `candidate_gate` | route = worker 名（定向补研） | 对应 researcher | `:2377, 2741` |
| `candidate_gate` | route = `composition_repair` 或 `itinerary_planner` | `itinerary_planner` | `:2178-2273`；映射 `:719-720` |
| `candidate_gate` | route = `passed` | `dispatcher` | `:715` |
| `artifact_gate` | `research_closed` | 强制 `accepted` | `artifact_gate.py:303-307` |
| `artifact_gate` | worker 内容失败且补研预算未尽 | `candidate_gate` | `:174` |
| `artifact_gate` | itinerary provider 失败 | `composition_repair` → `itinerary_planner`（预算尽则改 accepted） | `:257, 266-270` |
| `artifact_gate` | 否则 | `accepted` → `intent_fidelity_gate` | `:292-295`；映射 `:729` |
| `intent_fidelity_gate` | route 非法 | `raise RuntimeError` | `intent_fidelity_gate.py:138-139` |
| `intent_fidelity_gate` | blocking candidate gap 且预算未尽 | `candidate_gate` | `:116` |
| `intent_fidelity_gate` | 其余 blocking gap 且修复预算未尽 | `composition_repair` → `itinerary_planner` | `:127-133` |
| `intent_fidelity_gate` | 无 blocking / 预算尽 | `passed` → `delivery_quality_gate` | `:106-108, 125` |
| `delivery_quality_gate` | route ≠ composition_repair，或 `composition_closed` | `passed` → `budget_estimate` | `delivery_quality_gate.py:683-694` |
| `delivery_quality_gate` | 有 blocking gap 且窗口预算未尽 | `composition_repair` → `itinerary_planner` | `:637-648, 657-672`；映射 `:754` |
| `intent_amendment_router` | `intent_amendment_route` 为空 | `raise RuntimeError("…no continuation")` | `travel_planning.py:511-513` |
| `intent_amendment_router` | 否则 | 20 项白名单内的任一节点（缺 `scope_clarifier` 与 router 自身——前者在合同建立之前，后者不能回自己） | `:668-694` |

节点体内不走边的出口：plan_gate 的 `RunCancelled`（`:369`）与三类合同校验 `RuntimeError`（`:341,344,347`）；两道门的四处 `DeliveryContractViolation`（`intent_fidelity_gate.py:52,82`；`delivery_quality_gate.py:626,632`）。**全图正常终点只有两个**：`delivery_finalizer → END` 与 destination 的 `HALT → END`；其余离图路径全是异常。

两套互不相通的人在环：`plan_gate` 用 LangGraph 原生 `interrupt()`，暂停点落在 checkpoint 里，靠 `Command(resume=…)` 续跑；destination 的 `ask_user` 是正常路由到 END 加一条 `pending_user_choice`，续接逻辑在图外（`api/routes/chat.py` 的恢复端点）。

### 4.3 包装层短路：等价于隐式路由的一层

`with_run_control`（`run_control.py:735`）在节点体之前和之后都可能改写结果，这些改写会改变下游路由函数读到的字段，必须计入路由认知：

| 条件 | 后果 | 证据 |
|---|---|---|
| 进程内取消标志命中 | `raise RunCancelled`，直接冒到 `ainvoke`/`astream` | `run_control.py:764, 416-428` |
| 节点属于四个受限 worker 且自身窗口已关 | 节点体不执行，写 `agent_status={node:"failed"}`+`last_error`（相位 expired）或 `{node:"partial"}`（其余相位） | `:772-783 → :705-732` |
| `delivery_ready_event` 已置位（进入前或返回时） | 不执行 / 丢弃结果，写 `agent_status={node:"ignored_after_delivery"}` | `:785-794, 848-860` |
| 有新鲜 supplement 且合同已建立且节点不是 normalizer/router | 节点体不执行，只写 `intent_amendment_resume_node=节点名` | `:821-831` |
| 有新鲜 supplement 但合同未建立 | 节点正常执行，结果追加 `pending_intent_amendments`（不写 resume_node） | `:861-871` |
| finalizer 返回 `delivery_persisted=True` | 置位 `delivery_ready_event` | `:872-878` |
| 节点抛 `GraphInterrupt`/`RunCancelled`/`CancelledError` | 原样重抛（plan_gate 的 interrupt 靠这条穿过包装层） | `:956-957` |

窗口归属：`itinerary_planner` 与 `budget_estimate` 记 composition 窗口，结构性连接器轮次的 `transport_researcher` 临时记 composition 窗口，其余记 research 窗口（`run_control.py:684-689`）。

注意 `partial`/`failed` 与 `ignored_after_delivery` 是两个独立分支写的不同值：前者会被 dispatcher 当作终态推进计划（`dispatcher.py:29`），语义与"迟到 worker 被丢弃"不同。

---

## 5. 逐环节信息流

先说一件贯穿全图的小事：`next_agent` 字段真正驱动路由的只有两处——`route_after_dispatcher`（`dispatcher.py:176`）和 `route_after_destination` 读 `"HALT"`（`travel_planning.py:464`）。`clarifier_node` 也返回 `next_agent`（`scope/node.py:168`），但它的下游是无条件固定边，该写入是历史遗留、无消费方。

### 5.1 合同段：把话变成合同

进入时 state 里只有会话层与受控身份：`messages`、`user_query`、`run_id`、`controlled_trip_identity(_revision)`、`session_anchor`/`session_compressed`、`preset_context`/`preset_pack_constraints` 等。合同层三件套全部为 None。

`scope_clarifier`（`scope/node.py:133-168`）不调模型。它测量"会话历史 + anchor + 基础 system"的 token 量，越阈值且有 stream_queue 时调 `memory.compaction` 做一次异步压缩；缺受控身份直接抛 `ScopeIdentityError`——图上没有"停下来问用户"这条分支。写 `session_anchor`、`session_compressed`、`session_compacted_this_turn`（单写入点，唯一读方是 normalizer，用于在上下文透镜里印"较早的对话已整理"，`state.py:504-507`）。

`request_contract_normalizer`（`request_contract_normalizer.py:63-172`）是本环节唯一的模型调用点。取数侧三个独立 try/except 分别拉用户画像、手写记忆、语义检索记忆（top_k=8），任一失败只记 `missing_layers` 不中断（`constraint_normalizer.py:78-139`）。模型调用 `normalize_clauses`（`services/intent_normalization.py:257-380`）注入的只有受控身份加本轮切好的 clause 文本——不注入记忆、偏好、天气；输出 schema 把 `clause_id` 枚举和 `minItems=maxItems` 绑死在本次调用上，3 次尝试逐 clause 打捞，仍失败则跌入纯正则 fallback（`:373, 496-506`）。模型结果同时作为 `precomputed_free_text_constraints` 传给 Constraint Pack 装配，装配内部不会再调一次模型（复用落点 `panels/constraint.py:1329`）。写合同三件套 + `constraint_pack(_revision)`，并清空整个修订队列（`plan_gate_amendment`、`pending_intent_amendments`、`intent_amendment_route`、`intent_amendment_resume_node`）。

`research_brief_builder`（27 行）纯投影：合同 → `ResearchBriefV2` + `CapabilityPlan`。

state 层有一道强制一致性：`request_contract` 一旦非空，`intent_spec`/`planning_generation` 必须同代同版本，checkpoint 恢复时任何一件不匹配都拒绝加载（`state.py:533-550`）。合同段是一次原子的三件套写入。

### 5.2 基础事实铺设：授权前必须存在的确定性底座

四步全部无模型调用，夹在 brief 与 planner 之间（`travel_planning.py:602-607`）。

`minimum_delivery_draft_builder` 建未封存的交付种子；`draft_id` 相同（重放）则不覆盖（`minimum_delivery_draft.py:296-300`），`draft_id` 变了顺带清空整个完工基础设施（`:304 → :278`）。`destination_geo_resolver` 只从受控身份取坐标。`weather_context_builder` 有幂等短路（起止日期 + destination 集合一致即 `return {}`，`weather_context.py:60-67`），写天气快照与三件证据（source records / fact assertions / field provenance）。`trip_summary_card_brief` 是纯字符串裁剪。

### 5.3 授权：planner 与 plan_gate

`planner_node`（`planner.py:67-97`）没有模型调用。它从合同确定性投影出 `research_query_plan`、`capability_plan`、`execution_plan`（三段硬编码顺序：destination → transport+accommodation 并行 → itinerary，`capability_planning.py:177-185`）与 `agent_assignments`。一处值得记住的跨轮记忆：`_attach_initial_provider_evidence_scopes` 读上一轮 worker 留下的 `provider_evidence_outcomes` 来收窄下一轮 provider 范围（`planner.py:53-55`）——重规划回环时这是唯一被带过去的东西。fail-closed：任何 hard intent 没有被 assignment 认领即抛 `ValueError`，无 try/except（`capability_planning.py:328-343`）。

`plan_gate_node` 是全图唯一 `interrupt()`。进门先过三层校验（约束合同完整、八项合同一致性、门必须启用，任一失败抛 `RuntimeError`），然后把计划 + 硬约束 + 意图冲突投影成决策载荷交给用户。四种决策：cancel 抛 `RunCancelled`；edit/supplement 只在第一轮接受（额度 1 次，`:129`），写修订载体并整条合同链重跑；approve 带 content 按关键词判定拆成"仅投影"与"实质修订"两路；approve 无 content 才是真正放行。

放行那一刻做三件事（`minimum_delivery_draft.py:321-370`）：封 Draft（`planning_authorized=True` + 授权锚点 + 重算内容哈希）、开时间窗（`run_deadline`）、开资源预算（`run_budget`）。重放保护：已授权的 draft 直接复用已有窗口，"never grants a new window and never refills"。state 校验器强制预算与窗口同进同出（`state.py:652-653`，注释：只封一半说明有条路径不受上限约束）。

### 5.4 研究环：dispatcher、worker、两道门

这是唯一带循环的环节。dispatcher 是扇出边界，candidate_gate 是重入调度器。

**dispatcher**（`dispatcher.py:58-159`）纯代码，只写 `next_agent`（外加 deadline 分支下的计划步推进），不碰任何业务字段。决策树的顺序就是优先级：先看墙钟（research 已关且还欠组合 → 直接把计划步跳到组合；不欠 → `to_check` 去验收），再看计划边界，再看"当前组含 itinerary 且候选门未 passed → 先去 candidate_gate"（组合前必过候选门是硬约束，`:121-123`），再看组内是否全部落入终态 `{completed, partial, failed}`，最后推进或收口。真正的并行扇出在路由函数里：组内 pending 多于一个就返回 `[Send(node, state), …]`（`:209-213`）。

**worker 的共同骨架**（三个 researcher 同构）：

1. `resolve_agent_assignment` 拿本轮任务合同（补研轮的 key 带 `_rN` 后缀，`agents/utils.py:352-416`）；
2. `build_assignment_context` 把本 agent 认领的那部分合同投成紧凑 JSON——`linked_constraints` 是按 intent 过滤后的子集，不是整份 pack；
3. `build_research_packet_system_prompt` 拼 system prompt，`ResearchPacket` 的完整 JSON Schema 逐字符印进去（`research_packet_prompt.py:59`）；
4. `inject_agent_context` 追加四段（6.5 节）；
5. 追加末 8 条会话历史；
6. **确定性 provider 预检优先于模型**：destination 走地点解析，transport 走 12306/路线发现，accommodation 走高德/Nominatim 酒店发现。预检就绪则完全跳过 ReAct；
7. 预检不足才进 `streaming_react_loop`（`agents/utils.py:1751-2094`）：单次调用内 messages 持续累积、不重建也不裁剪；四个停止条件——窗口关闭（`ModelWindowClosed`）、模型本轮无 tool_calls、`ask_user` 触发、轮数耗尽；
8. `parse_or_repair_research_packet_output` 定型成 typed `ResearchPacket`。定型校验分三层：严格 JSON 解析加服务端权威 metadata 覆盖 → Pydantic 内建校验器 → 业务规则断言；修复只有一次受限模型调用（对瞬时失败再宽限 1 次），修复的形状是"模型只做选择、服务端确定性重组"，不是自由再生成。失败上抛，由节点层转成带分类前缀的 `last_error`。

三个 researcher 的实测差异：

| | destination | transport | accommodation |
|---|---|---|---|
| ReAct 轮数上限 | 3（`node.py:126`） | 5（`:97`） | 4（`:85`） |
| `can_ask_user` | 是（唯一） | 否 | 否 |
| RAG | 有（唯一） | 无 | 无 |
| 特有产物 | `retrieved_docs` | `provider_reference_services` | — |

**provider 绑定的实际形状**（代表性实现，本轮补读核实）：铁路侧 `_bind_one_rail_leg`（`transport_researcher/node.py:945-1415`）经 `execute_tool("get-tickets")` 走 Tool Gateway 查 12306，`_select_best_train`（`:594-704`）按固定判据序择优——可订票价 → 请求站对 → 高铁 → 历时 → 发车时间 → 车次号；查不到票就纯布尔 `return False`，由外层决定转 ReAct，绑定函数内部没有小循环。住宿侧按国家路由：中国走高德、其余走 Nominatim，docstring 明写 "never a fallback chain"——是互斥路由，不是失败降级。确定性路径的查询结果经 `provider_snapshot_cache` 缓存（命中仍重新落审计行），`tool_cache` 只服务 ReAct 循环。`audit_id` 从工具信封原样透传进候选的 source 记录——这个字段是后面证据链判定"真实供给"的核心判据（6.7 节）。

**candidate_gate**（`candidate_gate.py:1938-2760`，单函数 822 行）在一个节点里顺序做七件事：归并候选目录（校验 packet 世代/约束版本、按域截断、价格归一化、约束证明绑定、天气影响评估、逐候选准入）；一次 fast 模型调用做候选-意图匹配（四道门加起来唯一的 LLM 调用，异常整体吞掉、缺行默认 unknown，永不阻断）；确定性排名与贪心集合覆盖选择；算四类缺口；读墙钟；骨架编排（无骨架 → 派 itinerary 生成；有骨架 → 抽取市内连接器缺口并对齐 provider 路线，抽取失败清骨架、写裁定、走修复）；组装定向补研请求——挑 primary_gap、扣补研预算、改写该 worker 的 `agent_assignments`（含推荐/排除工具清单）、路由过去。放行时把所有未解决缺口标 exhausted 并显式回写预算账本完整副本。

**artifact_gate**（`artifact_gate.py:195-295`）纯确定性，逐 planned agent 检查：research packet 的身份完整性失败只落 `artifact_status="integrity_failed"` 与归因（路由字段却写 `accepted`，见发现 F-01）；内容失败且补研预算未尽交还 candidate_gate；itinerary 的 provider 失败走组合修复预算。对 checkpoint 恢复出来的 workspace 用 `model_validate(model_dump())` 强制重跑一次 Pydantic 校验（`:47-62`）。

### 5.5 组合：三相与修复轮

`itinerary_planner_node`（`node.py:2954-3741`，单函数 787 行）的三相靠 state 自身判定，不靠消息（`_composition_phase`，`:2939-2951`）：有 workspace → recompose；无骨架 → placement_skeleton；否则 → materialize_connectors。docstring 原话："hand over through the state they produce, not through a message one gate has to remember to write"。

骨架相（Phase 1）：一次 primary 调用生成不含市内交通的日程骨架（`skeleton_only=True` 的 schema，temperature=0）→ 规则补齐 → 精确解析 → 撰写地点定位（可能触发换名调用）→ `validate_placement_skeleton`。失败分锚点搬移修复与通用 JSON 修复两支。出口把 `candidate_gate_status` 写回 `needs_research`、`agent_status="pending"`（非终态），控制权交还 dispatcher → candidate_gate 去找市内连接器候选。

物化相（Phase 2）：通常无模型；只有 unfilled gap 时让模型撰写连接器的 mode/duration/reason——端点由服务器填。随后 `materialize_skeleton_connectors` → `assert_never_violate_rules` → `materialize_trip_workspace`（`itinerary_composition_v2.py:2738-3333`，596 行纯函数，无模型）产出 `TripWorkspaceV2`。

重组相（Phase 3）：整份重新生成 + 确定性后处理链（丢弃跨日边界的撰写连接器 → 隔离不相容长途日 → 运输拓扑校验）→ 失败再一次修复调用。最外层兜底：任何未捕获异常 → `agent_status="failed"` + `composition_failure_context`（600 字上限，`state.py:232-237`）。

修复轮的唯一新增输入是 `_composition_repair_section`（`node.py:486-524`），它把四条独立通道重述在一起：planner 自己的失败（`composition_failure_context`，planner 单写）、candidate_gate 对骨架的裁定（`placement_skeleton_failure_context`，gate 单写）、交付质量与意图保真两类 blocking gap。两个 failure context 互不写对方，且只回看一轮，永不跨轮累积（`state.py:396-408`）。

### 5.6 验收：两道确定性门加一次估价

`intent_fidelity_gate`（140 行小文件，判定委托给 `services/intent_verification.evaluate_intent_fidelity`）：`intent_spec` 缺失直接抛 `DeliveryContractViolation`；workspace 缺失反而放行（注释：Artifact Gate 故意把缺失带过来，这里再报只会掩盖真正原因）；`never_violate` 违规抛硬异常，禁止降级；其余按 gap 自带的 `retry_target` 路由，门不重新分类。它是四道门里唯一不读墙钟的（发现 F-33）。

`delivery_quality_gate`：三段检查产出五个子门状态与缺口列表。无 workspace 时先判组合窗口再判修复预算，两者任一耗尽都是硬失败 `DeliveryContractViolation`（判断顺序有书面理由："先判墙钟因为它绑得更紧"，`:622-624`）。有 workspace 且无 blocking（或预算耗尽）时，五个子门被 `_RELEASED_SUBGATES` 一律改写成 passed——这是"降级但仍交付"的机制核心。

`budget_estimate`：一次 fast 调用估总花费，只写一个数进 workspace 的 cost_summary；三个跳过条件，失败一律 `return {}`（注释："an estimate is never worth failing delivery for"）。

### 5.7 交付：三道断言、一次 dry-run、一个事务

`delivery_projection_node`（整文件 79 行）进门三道断言：质量门必须 passed 且 workspace 存在；天气快照必须存在；五个子门必须全 passed（"cannot bypass deterministic quality gates"）。处理只有四步：把 Constraint Pack 里的饮食过敏提醒注入 dining stops（Pack 在交付段的唯一消费点）→ 构建事实快照 → 取最陈旧数据时间戳 → 投影出报告/地图/来源三视图。无模型调用。

`delivery_finalizer_node` 五步，每步有自己的失败分类：校验封存世代（失败归 CONTRACT_VIOLATION）→ 查交付窗口余量（超时归 PERSISTENCE_FAILURE）→ 组装 Bundle（六个快照缺一即抛；三个 revision 逐一对齐当前值；`bundle_id` 是 run_id 加排序哈希的 sha256 前缀）→ dry-run 一次公开投影但丢弃结果（只为确认能安全渲染——此刻 Run 还能合法转 FAILED，commit 之后就不行了，`:501-522`）→ 重试循环里调 `_commit_initial_delivery_atomically`（单个 Postgres 事务：咨询锁 + 双层乐观并发 + 幂等键）。成功写 `delivery_bundle`、`delivery_persisted=True`、`is_completed=True` 与终态归因；失败抛 `DeliveryFinalizationError`，抛前异步标记 FAILED。

### 5.8 快答路径

`fast_answer_node`（`agents/fast_answer/node.py:560-771`）是 13 步线性执行，没有 ReAct 循环。它不经过深度路径的 `inject_agent_context`，自己装配 system prompt（基础 prompt + preset 后缀 + Constraint Pack + ContextBuilder 的会话层），但 Constraint Pack 的装配函数与深度路径同一个（`build_run_constraint_pack`），压缩与 Anchor 机制也同源。工具只有两个只读事实源，都不走工具循环：汇率是 `execute_tool` 加白名单收窄到单一工具的确定性预检；RAG 是内部检索调用（非工具），无条件执行、在分级器上 fail-closed。生成阶段只有一次 fast 调用（无 tools 参数）。`OutputGuard.check`（`:734`，全仓唯一调用点）只做置信度打分与来源标注，不拦截不降级，失败透传原文。写回 state：`output_confidence`、`final_grounding`、`retrieval_summaries`、`synthesis_mode="fast"`（`:756-767`）。

### 5.9 交付后编辑（图外环节）

Bundle 落库之后，用户对行程的每次改动走 `WorkspaceV2Service`：`apply_workspace_v2_mutation`（`workspace_v2_mutations.py:1220-1691`）执行编辑，但完全不 import、不调用 `itinerary_composition_v2.py` 的任何结构性校验（运输链连续性、锚点顺序都不重查）；重新校验走的是 `_revalidate_intent_application`（`workspace_v2_service.py:296`），复用 `compile_composition_rules` 只重评"意图覆盖度"。两套体系唯一的挂钩点：每次编辑记一条 `CompositionMutation`（`created_by="user_edit"`）追加进与组合阶段同一个台账。候选再准入（`candidate_readmission.py`，815 行）与天气刷新（`weather_bundle_refresh.py`，806 行）是这个环节的另两个入口，服务于编辑与数据新鲜度，不在主图上。同一份 `TripWorkspaceV2` 因此有两套互不复用的校验实现——这是架构上需要知道的事实，也是后续优化讨论的候选议题。

---

## 6. 横切机制

### 6.1 运行时修订通道

用户在运行中追加的要求不改 prompt，先变成 `IntentAmendment`，由 `with_run_control` 注入 `pending_intent_amendments`，在下一条边被拦截转入 `intent_amendment_router`。影响分类五档（`entities/request_contract.py:30-31`）：`IDENTITY_CHANGE` / `UNSUPPORTED` / `PROJECTION_ONLY` / `COMPOSITION_AFFECTING` / `RESEARCH_AFFECTING`（另有两档 `ADMISSION_AFFECTING`/`RANKING_AFFECTING` 在生产路径上产生不出来，见发现 F-03）。受理逻辑在 `workflows/intent_amendments.py:79-202`：五条拒绝谓词按序判定（身份变更、不支持、已交付、研究窗已关、组合窗已关）；至少一条被接受时路由硬编码回 `request_contract_normalizer`，并按最强影响展开作废阶梯 `invalidation_update`（`services/state_invalidation.py:10-72`）——`PROJECTION_ONLY` 几乎不清、`COMPOSITION_AFFECTING` 清组合层、兜底分支等价 `RESEARCH_AFFECTING` 全清（含已封存的 draft/deadline/budget）。

一条横跨三个文件、没有任何单份材料完整记录过的因果链：运行时修订被接受时会无条件把 `plan_gate_revision_count` 加一（`intent_amendments.py:127`），链路必然重新流到 `plan_gate`，而那里的短路只认 `projection_amendment_pending`，于是再次 `interrupt()`；此时修改额度已满，决策选项被裁成仅 approve/cancel（`travel_planning.py:261, 366`）。也就是说：一次运行中补充要求 = 用户永久失去计划门的编辑权，且必须再批准一次。这是当前代码的真实行为，是否符合产品意图需要确认（发现 F-30）。授权之后到达的非研究类修订还有一条更硬的问题，见发现 F-29。

### 6.2 run 控制与终态

每次 run 以 `run_attribution(run_id)` 为归因边界（`travel_planning.py:930`；非流式入口已删，仅剩 `astream` 一处）。TripRun 状态机的合法迁移收在一张表里（`entities/trip_run.py` 的 `ALLOWED_STATUS_TRANSITIONS`），唯一写方是 `trip_run_store` 的三个带事务锁的方法（`transition_status`/`claim_checkpoint_resume`/`complete_delivery`）——但 `claim_checkpoint_resume` 的 CAS 用调用方传入的集合判定、绕开迁移矩阵，与实体层的可恢复集合已经分叉（发现 F-04）。执行租约与控制命令是两张独立表（`trip_run_executions`/`trip_run_commands`），都以数据库 `NOW()` 为唯一时钟。取消是进程内停止标志 + `RunCancelled` 异常冒泡；恢复时 checkpoint 要过双重合同校验（LangGraph 反序列化 + `TravelAgentState.model_validate`，`travel_planning.py:817-854`），失败收敛为 `CheckpointContractError`——旧 checkpoint 不允许带着无关 Draft 的新预算复活。

### 6.3 墙钟五相与预算五维（权威数表）

墙钟相位（`workflows/run_deadline.py:90`，以授权时刻为原点）：

| 相位 | 默认边界（`config/models.py:268-271`） | 语义（`run_deadline.py:98-101`） |
|---|---|---|
| `research` | 0 – 375s | 正常研究 |
| `target_missed` | 375 – 450s | 仍可发起研究调用 |
| `closeout` | 450 – 570s | 关研究，留组合 |
| `composition_closed` | 570 – 600s | 连组合也关，只剩投影与持久化 |
| `expired` | > 600s | 交付预算耗尽 |

`research_closed` = 相位进入 closeout 及以后（`:112-114`）；`composition_closed` = 相位进入 composition_closed 及以后（`:117-118`）。窗口不抛超时，而是改变图的形状：dispatcher 会直接把计划步跳到组合（`dispatcher.py:80-110`），三道门的路由函数把非放行值强制折成放行（4.2 节表），受限 worker 直接被包装层短路（4.3 节表）。

资源预算五维（`entities/run_budget.py:43-47`；默认值 `config/models.py:355-359`）：`max_llm_calls=100`、`max_tool_calls=150`、`max_input_tokens=1,000,000`、`max_output_tokens=100,000`、`max_cost_usd=5.0`。调用前按"这次最坏开销"预判（`guard_run_budget`），调用后按同一公式记账（`models/router.py:613-615` 注释：预算判断与台账记账必须同公式，否则上限失去意义）；失败调用也计入预算（`router.py:617`）。组合修复预算全局上限 3 次，四道门共享（`workflows/composition_repair.py:33`）；定向补研预算按 scope 记在 `candidate_gate_attempts`（非长途域统一回落 1 次，`candidate_gate.py:99`）。

### 6.4 协议载体字段：门间协议的实际形状

`TravelAgentState` 的字段里，真正承担"跨节点协议"职能的是下面这批。写方/读方全部经源码核对：

| 字段 | 写方 | 读方 | 载荷 |
|---|---|---|---|
| `next_agent` | dispatcher；destination（`"HALT"`） | 两个路由函数 | 扇出决策，三值枚举 + HALT |
| `agent_assignments[worker]` | planner（首轮）；candidate_gate（补研轮改写，`candidate_gate.py:2717-2745`） | 四个 worker | 任务合同：objective / must_cover_intent_ids / 工具推荐与排除 / provider evidence 指派 |
| `agent_status[key]` | 四个 worker；包装层短路分支 | dispatcher（`_DONE_STATUSES`）；artifact_gate | 调度完成态：completed / partial / failed / pending / ignored_after_delivery |
| `artifact_status[key]` | artifact_gate（唯一） | 图内无读方（审计/投影侧） | 当前合同下的接受态，与调度完成态刻意分开（`state.py:352-355`） |
| `research_packets[k@gen]` | 三个 researcher | candidate_gate；artifact_gate | 唯一业务产物；key 形如 `worker_key[_rN]@generation_id`（`state_invalidation.py:87-88`） |
| `candidate_gate_status` / `candidate_gate_route` | candidate_gate（status 另有 itinerary Phase1 写 route） | dispatcher；路由函数；itinerary 前置校验 | "目录是否可用于组合" / 下一跳 |
| `placement_skeleton` | itinerary Phase1 写；candidate_gate 对齐回写或清空 | `_composition_phase`；candidate_gate | 骨架—连接器两段式的交接物 |
| `composition_failure_context` | itinerary_planner 单写（失败写原因、成功写 None） | 修复轮 prompt 装配 | 上一轮组合为何失败，只回看一轮（`state.py:396-401`） |
| `placement_skeleton_failure_context` | candidate_gate 单写 | 修复轮 prompt 装配 | "骨架校验通过但抽不出 connector"的裁定（`state.py:402-408`） |
| `local_connector_gaps` | itinerary Phase1/2 | candidate_gate；itinerary Phase2 | 相邻两点之间的市内交通缺口 |
| `intent_fidelity_gaps[].retry_target` | intent_fidelity_gate（值来自 `intent_verification`） | 门自身路由；修复轮 prompt | "这个缺口退回哪个上游"，门直接消费不重新分类 |
| `*_gate_route` 三个 | 对应门 | 对应路由函数 | 门的裁决；三者都可被墙钟改写成放行值 |
| `recommendation_quality`（5 子门） | delivery_quality_gate | delivery_projector 的进门断言 | 投影准入凭证；预算耗尽时被整体改写为 passed（`delivery_quality_gate.py:593-599`） |
| `composition_repair_attempts` | 四道门经 `apply_composition_repair_budget` 统一写 | 三道门读 | 全局组合修复预算，写时扣减、路由只读 |
| `candidate_gate_attempts` / `_failure_signatures` | candidate_gate 单写（整字段替换） | candidate_gate；`worker_targeted_research_exhausted`（两道门 import） | 定向补研预算账本 |
| `gate_failure_attributions` | 四道门 | delivery_finalizer（覆盖披露归并） | 门失败审计，key 是稳定 attribution_id |
| `last_error` | 三个 worker（带分类前缀）；四道门 | `classify_provider_failure` 等 | 用字符串前缀承载失败分类（缺陷见 comparative-study §4.4） |
| `provider_evidence_outcomes` | 三个 worker | planner（跨轮收窄）；candidate_gate | provider 范围的跨轮记忆 |
| `pending_intent_amendments` | 包装层；plan_gate；router | 图上几乎每条边 | 运行时插队信号 |
| `minimum_delivery_draft.planning_authorized` | plan_gate 封版 | finalizer；state 校验器 | "这一代是否已被用户授权" |
| `run_deadline` / `run_budget` | plan_gate 封版；包装层非减性回写 | 全部门与 worker | 墙钟与资源上限，必须同进同出 |
| `delivery_persisted` | delivery_finalizer | 包装层（置 delivery_ready_event）；修订受理（一律拒绝） | 交付已落盘的不可逆边界 |

### 6.5 上下文注入边界：每个模型调用点能读到什么

深度路径的四个 worker 类节点共用一个注入函数 `inject_agent_context`（`agents/utils.py:80-122`，只有它们用），固定追加四段：历史对话摘要（session_anchor）、`<active_preset>` 信封、Constraint Pack、天气。Constraint Pack 的投影分两节且各有行数预算（hard=12 / preference=45 / reference=6，`panels/constraint.py:210-212`）：【本轮统一约束】只放 user_visible 的硬约束与偏好；【参考级背景——不是约束】放系统推理画像与低档记忆，prompt 里逐字写明不得当成硬性要求；超预算必须出声（"本类还有 N 条未列出"）。这是用户画像与记忆抵达模型的唯一通道。

全部模型调用点及其可见上下文（统一编号；R 在图外，A–F 在深度图内）：

| # | 调用点 | 位置 | 档位 | 能看到什么 | 输出约束 | 失败处理 |
|---|---|---|---|---|---|---|
| R | 意图分流 | `route_intent.py:161` | fast | 用户消息与会话线索 | 四值路由 JSON | 判不出 → 503，fail-closed |
| A | 条款归一化 | `intent_normalization.py:257-380` | fast | 受控身份 + 本轮 clause 文本（无记忆/天气） | strict schema，枚举绑本次调用 | 3 次打捞 → 正则 fallback |
| B | 候选-意图匹配 | `candidate_intent_evaluation.py:323-401`（调用点 `candidate_gate.py:1965-1970`） | fast | intents + 候选/facts/sources 摘要，按域分批 | strict schema，全部 id 枚举限定本批 | 整体吞异常，缺行默认 unknown，永不阻断 |
| C/C'/C'' | 三个 researcher | 节点各自装配 | fast | 认领的合同子集 + 四段注入 + 工具信封 + 末 8 条历史；RAG 仅 destination 有 | `ResearchPacket` 全 schema 印进 prompt | failure-only packet + 带前缀 `last_error` |
| D–D7 | 组合七处（骨架、锚点修复、通用修复、换名、撰写连接器、整份重组、重组修复） | `itinerary_planner/node.py` | primary | 合同投影 + 组合规则 + 选中候选 facts + Constraint Pack + 天气 + 末 4 条历史；换名与连接器两处只给最小输入，端点/坐标由服务器填（`_SERVER_OWNED_PLACE_FIELDS` 从 schema 剔除，`node.py:103-108, 263-271`） | strict schema，temperature=0 | 确定性校验失败 → 修复调用 → 仍失败抛到最外层兜底（`:3726-3741`） |
| E | 预算估算 | `budget_estimate.py:154-161` | fast | 只有行程标题/天数/人数/组件行与已知价格 | json_object，值域 [1, 5,000,000] | `return {}`，无重试，字段留空 |
| F | 会话压缩 | `scope/node.py:100-107` | 压缩服务自持 | 全量历史 | 服务内部 | 忙则跳过，失败沿用原上下文 |

三条边界事实：四道门加起来只有 B 这一次模型调用；全图只有 destination_researcher 一个节点注入 RAG（HybridRetriever 命中数 destination=7、其余全 0）；天气进模型只有两条路（四段注入的格式化文本，和组合 prompt 里候选的 weather_fit 数值）。

### 6.6 工具治理

三层收窄加单一执行入口，整体 fail-closed：会话层 `get_available_tools` 决定本次会话有哪些工具；Agent 层 `filter_tools_for_agent`（`agents/utils.py:419-487`）按硬编码的 `_AGENT_TOOL_POLICY`（`:275-323`，四个 agent 键）过滤，不在策略里的 agent 只剩本地工具，`deny_tools` 含 `"*"` 直接清空；轮次层 `apply_tool_exposure`（`:529-579`）在白名单之内决定曝光形式（超过阈值走压缩目录 + search_tools，搜索边界仍是白名单）。执行全部经 `ToolGateway` 信封（全仓唯一调用方是 `agents/utils.py` 的 `execute_tool`，`:582` 起约 456 行）：gateway 前置检查 → 时间窗/预算/重试额度三道短路 → 快照缓存 → 指数退避重试 → 降级。最硬的一条规则：降级目标也必须再过一次白名单，不在 `allowed_tool_names` 里就记录并抛 `PermissionError`（`:914-927`）——治理不因降级而放松。

### 6.7 证据链：从一次工具调用到报告脚注

链路七环，每环的类型、生产点与硬失败点（本轮端到端补读核实）：

1. `ToolManifest`（`entities/tool_gateway.py:65-80`）是策略层元数据（权限类别、`evidence_allowed`、不可信内容策略），供 Gateway 决策；同文件 `ToolAuditRecord`（`:91-112`）是每次工具调用的审计行，生产点在 `tool_audit_store.py:114,153`。这一环不参与后续校验闭环。
2. `SourceRecord`（`delivery_bundle.py:1505-1554`）把一次证据固化为不可变记录。硬失败点两处：自我背书的来源直接拒绝（`attestation=="self"` 即抛，`:1528-1554`）；缓存来源与记录的 provider/哈希/时间戳不一致逐项抛。`tool_audit_id` 是可选字段——成功的 provider 结果经两处 dict 字面量把它带上（`research_packet_output.py:2177, 4269`），失败来源普遍不带。
3. `FactAssertion` + `FactSourceLink`（`:1557-1587`）：`status=="verified"` 的事实必须至少有一条 `supports` 关系的来源链接，否则类型层直接抛（"verified fact requires a supporting source"）。
4. `EntityLineage`（`:125-182`）把行程实体绑回 (packet, candidate, facts, sources)，三种血统各自的必填/禁填字段逐支硬校验。
5. `ProviderEvidenceOutcome`（`provider_evidence.py:176-212`）按 scope 记录 provider 抓取结果三态，status 与计数字段的一致性由校验器强制。判定候选是否"真实供给落地"的判据就是 `source.tool_audit_id` 是否为真值（`research_packet_output.py:1765-1770`）。
6. `validate_manifest` 的闭包段（`delivery_bundle.py:3260-3520`）强制 citation↔entity↔fact↔source 的引用不悬空、不串位——但**不检查** `tool_audit_id`。也就是说"报告每句话能追到来源"是类型层闭环，"来源能追到一次真实工具调用"靠的是可选字段的约定俗成，两者强度不同。
7. `EvidenceBasisView`（`evidence_basis.py:108`）是对外公开投影。

packet 修复分支的真实形状：两个 `_repair_from_provider_*` 函数（214/332 行）都是"受限模型选择 + 服务端确定性重组"，不是自由再生成。发现 F-06 所指的异常消息子串匹配路径已核实属实：命中后清零 candidates/fact_assertions/field_provenance、保留 source_records（含失败源）供下一轮补研排除。

### 6.8 记忆与 RAG

记忆抵达模型只有 Constraint Pack 一条通道（装配 `build_run_constraint_pack`，快慢路径共用同一函数，差别只在是否传入预计算的自由文本抽取）。`ContextBuilder` 只装"基础 prompt + Anchor 摘要"两层，不装任何记忆——历史上它装过，后来两条路径的 user_id 都改成常量空串使那段成为死码，已删除（`context_builder.py:15-22` 记录了这段教训；`state.py:477-481` 记录了被删掉的 `user_profile_summary` 字段为什么必须删）。

会话压缩由 clarifier 测量触发、`memory/compaction.py` 编排、`compressor.py` 执行（一次 LLM + DB 落盘）。注意两把 token 尺子并存的问题（发现 F-05）：触发阈值用字符估算那把，压缩报告用 tiktoken 那把。

长期记忆的写入是后台任务：`services/memory_extraction_job.py` 触发 `memory_extractor.py` 的模型抽取，入库前过准入门禁（`_admit_extraction_result`，`memory_extractor.py:258-315`）；后台任务语义是 at-least-once + 下游幂等（`background_jobs` 表）。

RAG 的检索管线是 改写（fast 模型）→ 混合检索 → 重排 → CRAG 分级（`retrieval_pipeline.py`），模式由 `RAGModePolicy` 决定，快慢路径判据不同（`rag/policy.py`）。深度路径上只有 destination_researcher 消费它。索引侧：`KnowledgeIndexer` 在装配层接线（`builders.py:46,85,239`），语料从 wikipedia fetcher 与文档加载器进来（`rag/sources/wikipedia_fetcher.py:118-143`、`document_loader.py:39-76`）；索引器内部实现本轮未读（9.2 节）。

### 6.9 模型路由与计价

`ModelRouter`（`models/router.py:797`）暴露三个档位：`get_primary`（`:856`，全图只有组合用）、`get_fast`（`:859`，其余全部模型调用点）、`get_scope`（`:862`，零调用点，死代码，发现 F-22）。每个档位一个 `ChatOpenAI` 客户端，`stream_usage` 按 provider 能力显式声明。并发经按档位配置的 channel gate，排队等待也计入 Run 的模型时间窗（`:504-523`）。

每次调用前有四步固定管线（`:638-644, 672-677`）：输出 token 上限改写 → json_schema 降级判定（按 `configs/providers/*.yaml` 声明的能力，不按 base_url 猜）→ response_format 归一化 → 降级时把被丢弃的 schema 原样贴进 prompt（去重、补 DeepSeek 要求的 "json" 字样）。strict-subset 改写发生在业务层（`as_strict_schema` 的调用点在组合、packet、归一化三处），router 只判"该不该整体降级"。

记账与预算是同一把尺：调用前 `guard_run_budget` 按最坏开销预判，调用后 `_charge_budget` 用同一公式落账（`:613-615` 注释明言两者必须同公式）；拿不到真实 usage 用字符估算并标记 `estimated=True`，错误且无 usage 时 token 字段留空——"绝不编数"（`:585`）；失败调用同样占预算（`:617`）。计价细节（`config/pricing.py`）与预算异常在各节点的捕获点本轮未读，见 9.2 节。

---

## 7. 工程对照：同一个机制，三个仓库写成了什么形状

设计哲学层的对照在 `docs/design/comparative-study.md`，本节只看代码工程层。先声明边界：codex 约百余个 crate 只读了 core/protocol/agent-roles 三块，openpi 25 个扩展只展开了 6 个——下面每条"他们怎么写的"都只代表读到的部分（工作底稿逐条列了核实清单）。

**7.1 模块切分。** 我们是单包 18 个顶层目录，"谁能 import 谁"全靠约定，图定义文件里还住着一个完整节点体（`plan_gate_node` 在 `travel_planning.py:327-448`，而文件 docstring 自称只负责图结构）。codex 把协议、角色、图存储各拆成独立 crate，边界由 Cargo 强制；openpi 用统一扩展契约（25 个 `index.ts` 全部 `export default (pi) => void`），跨扩展只准 import `shared/`。两者解决的是同一个问题：让协议定义方不依赖任何使用方。我们缺的正是这层——`worker_errors.py` 想当协议定义方，却因为要复用 `provider_failure` 的词表而变成下游，前缀常量只能在读方重新敲成字面量。这是拓扑问题，不是纪律问题。可迁移，低成本：仓库已有样板（`entities/contract_base.py` 5 行、零业务依赖、被 19 个模块继承），把前缀与词表提到同层即可。

**7.2 协议类型化。** 我们同一仓库两种形态并存：门↔门一侧已经类型化（`GateDisposition` 三值枚举、`StrictModel` 的 `extra="forbid", frozen=True` 覆盖 19 个 entity 模块——未知字段硬错误、对象不可变）；Worker→门一侧仍是字符串前缀。另一条工程事实：贯穿全图的 `TravelAgentState` 自己没有 `extra="forbid"`（`state.py:668` 只有 `arbitrary_types_allowed`），是核心契约里唯一不适用严格性的（运行时后果未验证，不下结论）。codex 把一次失败拆成四层类型，判别式用 `strum` 机械派生，穷举 match 当编译期哨兵（实测 `is_retryable`/`affects_turn_status` 全部 variant 显式列出，无 `_` 分支）——新增分类不声明后果，编译不过。openpi 是动态语言，用测试做同一件事：正则扫描全部注册工具，断言每个都被分类为 child-safe 或 excluded，"未分类即失败"。穷举 match 不可迁移（Python 没有等价物）；openpi 的测试路线可迁移且零新概念，见 7.7。

**7.3 状态所有权。** 我们的 reducer 定义"并发写怎么合并"，不定义"谁可以写"；单一写方靠注释约定，同一句告诫在两个文件逐字重复（`composition_repair.py:21-24` 与 `delivery_quality_gate.py:676-681`）。codex 把上限写进类型（`Mutex<Option<ActiveTurn>>`——最多一个运行中任务；名额用"预定 + RAII 释放"，异常路径也归还）。openpi 把"不能写"实现成"拿不到那个工具"（子会话的 21 个排除工具里包含改目标、再编排的全部入口，构造策略时就滤掉）。codex 的做法不可迁移（并发模型不同）；openpi 的"能力缺席"手法我们在工具层已经有了（`filter_tools_for_agent`），state 字段层没有对应物，现实的替代是把"哪个模块允许写哪个字段"写成 import 面的测试断言。

**7.4 配置声明化。** 我们的执行图、工具策略、降级表全是 Python 字面量（`_AGENT_TOOL_POLICY`、`_FALLBACK_MAP`、capability_planning 三段硬编码顺序）；但同一仓库的 config 层做得完全不同而且做得好——YAML + env 覆盖 + 来源报告、未知字段硬错误并报路径与值、provider 能力按文件声明。最能说明问题的是 `config/mcp_defaults.py:1-5`：docstring 自己写清了"这是一份数据，不是结构声明"，落地却仍是返回 dict 的函数。判据想清楚了，没走到底。codex 的角色是 TOML（内置与用户角色同一条解析管线、覆盖只能收窄、`deny_unknown_fields`）；openpi 的 agent 类型是 markdown frontmatter（只认 6 个 key，未知 key 拒绝整份文件，理由写在报错原文里：拼错的限制性 key 会静默变成放开全部工具）。可迁移，管线已存在：把三张表迁进 config 的严格校验管线，白拿未知字段硬失败、来源报告、文档同步三件事。"模型选执行档"不可迁移（墙钟封存前提，comparative-study §2.5 已判定）。

**7.5 工具治理。** 我们三层收窄 + 单一 Gateway + 降级也过白名单，整体 fail-closed；新增 worker 忘记进策略表的后果是安静地只剩本地工具——方向安全，但没有信号。codex 的曝光度是六态枚举（矛盾组合在类型上不存在）、同名注册直接硬失败；openpi 的双名单是唯一真源、被别处 import 复用而不是重新定义。三者都 fail-closed，区别在失败是否可见。六态枚举不可迁移（我们没有 code-mode 维度）；"同名注册硬失败"可迁移且成本极低。

**7.6 prompt 管理。** 我们的 prompt 主体内联在 node.py（itinerary 93 个三引号定界符、candidate_gate 56 个），`prompts.py` 六个文件合计只有 190 行。先写我们做对的一点：输出契约不靠文字描述，`ResearchPacket.model_json_schema()` 逐字符注入 system prompt，且 `candidate_limit` 刻意设为必填参数（docstring 写明：默认值会让忘了传的调用方打印出与自己 schema 不一致的上限）——这与 codex 从类型派生 schema、openpi "工具定义是参数的 canonical 来源"是同一条原则。codex 多做了两件事：角色锁定说明从配置反射渲染（`format_role`），且生成出的 prompt 文本有快照测试钉住。可迁移的是后两件：配置反射渲染（数据源已存在，缺渲染函数）与 prompt 快照测试（`build_research_packet_system_prompt` 是纯函数，天然可快照）。prompt 整体外置为数据文件收益有限（运行时插值太多），不建议首轮做。openpi 的技能按需披露不可迁移（我们是单次 Run，稀缺的是墙钟，多一步"先去读文档"是净亏）。

**7.7 测试钉法——本节最重要的一条。** JourneyPilot 已经有与 openpi 完全同构的机械守卫，质量还更高，只是覆盖面小。已有资产三件：`docs/invariants.md` 62 条不变量被 `tests/test_invariants_doc.py` 当代码测（点名的测试必须能收集到、点名的文件必须存在、ADR 链接必须真实——还有一条两个参考仓库都没有的元测试：守卫自身收集到零条引用时必须失败）；分窗表与 `WORKER_NODES` 的双向集合相等守卫（`test_run_execution_contract.py:131-161`，docstring 把"依赖方向不允许 import、名单被重敲一遍"的根因写得很清楚）；生成文档必须逐字符等于当前 schema（`test_config_contract.py:341-356`，报错直接给修复命令）。codex 的 golden fixture diff、openpi 的正则扫描 drift test，手法与此同构。差的不是手法，是覆盖面——同类的表还有五张零守卫：

| 表 / 协议 | 位置 | 守卫 |
|---|---|---|
| 分窗表 ↔ `WORKER_NODES` | run_control ↔ travel_planning | 有 |
| config schema ↔ 生成文档 | config ↔ docs | 有 |
| invariants 文档 ↔ 测试/文件/ADR | docs/invariants.md | 有（含元测试） |
| `_AGENT_TOOL_POLICY` ↔ 图上 worker 集合 | `agents/utils.py:275-323` | 无 |
| `_FALLBACK_MAP` ↔ 已注册工具 | `tools/fallback.py:83-92` | 无 |
| `amendment_continuations`（20 项）↔ 已注册节点 | `travel_planning.py:668-689` | 无 |
| `_KNOWN_NEXT_AGENTS` ↔ dispatcher 产出值 | `dispatcher.py:32-36` | 无 |
| 五个 `last_error` 前缀 ↔ 读方分支 | worker_errors ↔ provider_failure | 无 |

把 `test_run_execution_contract.py:131` 的形状复制到这五张表上，并给每条新守卫补一个 INV 编号（invariants 门禁会顺带保证它不被删），不需要从任何参考仓库引入新概念。这是全部对照结论里优先级最高、成本最低的一条。

**7.8 工作流编排与台账。** openpi 的 workflows 扩展与我们的 run_control + 四道门是最接近的对照物，但两者是本质不同的两种写法：openpi 让模型自写 JS 脚本进子进程沙箱执行，"步骤/依赖/条件"就是普通控制流；我们的图形状在授权前完全确定，模型不编排图——这条差异是设计层前提（人的可用性、失败不可逆）决定的，不迁移。工程层值得看的是它的台账三层：`journal.ts` 按调用内容哈希缓存与重放（应对无 barrier 流水线的乱序，比按序号重放稳健）；`invocation-ledger.ts` 把一次调用拆成 intent/admission/execution 三平面状态机，运行时断言强制合法迁移，**中断时显式标记为 uncertain 而不是猜测成败**；`replay-safety.ts` 用重放白名单加文件指纹加跨调用并发守卫。对照我们：checkpoint 按 LangGraph 序号性快照，恢复靠双重合同校验（6.2 节），足够但没有"中断即 uncertain"这类显式三态。验收上 openpi 是把结构化验收合同注入 schema、但重试/跳过/终止下放给脚本自己判断；我们的四道门是引擎级回边机制——这一维我们更强，应当保持。可借鉴的具体两点：终态与中断状态的显式三态标记（与我们 `_terminal_bucket` 的静默 `None` 形成对照，发现 F-13）；台账按内容哈希而非序号做重放键的思路，若将来做补研轮重放会用到。

---

## 8. 代码审查发现清单

范围声明：`docs/design/comparative-study.md` §4.4 已定案的四条（`worker_failed:` 双读方矛盾、未识别前缀 fail-open、读方字面量副本的依赖方向根因、该协议零测试）不重复收录。每条发现都经回源码验证后才写入；验证不成立的候选在 8.4 节。全部结论基于静态阅读，未运行任何测试——严重度是推断不是复现；其中 F-05 与 F-29 属于"跑一次就能证实或证伪"的类型，建议优先补最小复现。

### 8.1 高（10 条）

**F-01｜两道门把失败写成"成功"路由值，失败只存在于旁路账本。** candidate_gate 的四条契约失败路径统一返回 `status/route = "passed"`（`candidate_gate.py:1858-1889`，调用点 `:1944-1964`）；artifact_gate 的身份完整性失败写 `route="accepted"`，失败只落 `artifact_status` 与归因（`artifact_gate.py:130-146`）；读方还带 `or "accepted"` 缺省（`:299`）——字段为 None（门没跑）也放行。三重 fail-open：失败写成功值、缺省也是成功值、真相在另一个字段。修复方向：路由值封闭枚举出 passed / contract_failed / integrity_failed，禁止 or 缺省。

**F-02｜"仅投影修订"的判定写了两遍，词表不同，已会给出相反结论。** `travel_planning.py:318-324` 与 `intent_amendments.py:18-51` 各有一份关键词表（前者有"简洁"无"摘要"，后者反之；"每天"只在前者的 material 表里）。可复现分叉："摘要再短一点"两处结论相反。同一条修订走 plan_gate 与走运行中注入，作废范围完全不同。修复方向：删 `travel_planning.py` 的本地实现，统一调 `classify_amendment`。

**F-03｜`AmendmentImpact` 两个枚举值不可达，三张表却为它们分支。** 唯一产出函数 `classify_intent_impact`（`state_invalidation.py:75-87`）零调用点；真正在跑的 `classify_amendment` 从不产出 `ADMISSION_AFFECTING`/`RANKING_AFFECTING`；而 `invalidation_update` 没有 `ADMISSION_AFFECTING` 分支——一旦有人接上那个死函数，它会静默按最强的 `RESEARCH_AFFECTING` 全清，比调用者预期破坏大得多，且无测试会发现。修复方向：删死码与死分支，或补齐分支并把两个分类器合一。

**F-04｜"能否恢复"有两张互不相识的表，UI 会亮出必然失败的按钮。** 实体层 `_RESUMABLE_STATUSES` 含 CREATED（`trip_run.py:279-284`），但 `claim_checkpoint_resume` 的 CAS 只按调用方传入的集合判定（`trip_run_store.py:1168-1232`），唯一调用方只传 `[AWAITING_INPUT]` 或 `[FAILED, INTERRUPTED]`（`chat.py:434-446`），且 CAS 完全绕开迁移矩阵 `assert_status_transition_allowed`。讽刺的是 `trip_run.py:287-289` 的注释正是在警告这种分叉（"一个亮着的『继续』按钮点下去拿 409"）——`is_cancellable` 做到了单表，resumable 没有。修复方向：allowed_statuses 从调用方参数收回实体层派生。

**F-05｜两把 token 尺子共存，压缩阈值与压缩报告不同口径。** `context_builder.py:47-62` 对默认模型直接字符估算（自称"全层一把尺"）；`compressor.py:141-148` 同名函数先走 tiktoken（依赖已锁定，两函数对同一文本必然给出不同数，中文上量级差约 2 倍）。触发判据与效果度量不可互相印证。修复方向：compressor 改 import 唯一实现。

**F-06｜跨文件靠异常消息全文匹配驱动修复分支。** 权威写方是 `delivery_bundle.py:1947` 的裸 `ValueError("research packet requires external identity-bound facts")`；读方在 `research_packet_output.py:344` 存字面量副本、`:4589-4594` 子串匹配进入专用修复路径（清零候选闭包、保留失败源供下轮排除——本轮已核实该行为属实）。改一个标点就静默关闭这条修复路径，无测试钉住。修复方向：定义专用异常类型，isinstance 判定。

**F-07｜"报告是否有内容"两份实现，一份修好另一份还在探测不存在的字段。** finalizer 侧已修并注释自陈那两个键从未存在（`delivery_finalizer.py:87-96`）；`run_completion_metrics.py:522-528` 仍在 `document.get("sections")/get("summary")`，走 Mapping.get 不抛错、静默失效。修复方向：提取共享判定函数。

**F-08｜没有 checkpointer 的执行路径走到 plan_gate 必抛 RuntimeError。**（本次清理已删掉非流式 `run()` 入口，它硬算开关、不可覆盖的那一半入口不对称已随之消失）`astream()` 允许显式覆盖（`:902-906`），门禁关闭即抛（`:346-347`），无降级分支。修复方向：构造期 fail-fast，统一覆盖语义。

**F-09｜修订影响分类与作废范围这条协议零测试。** `classify_amendment` 与 `invalidation_update` 在 `tests/` 下零引用（`_terminal_bucket`、`_document_has_content`、`claim_checkpoint_resume` 同样为零）。F-02/03/04/07/29 能长期共存的直接原因。修复方向：先补"每个枚举值 → 清空哪些字段"的参数化穷举测试。

**F-29｜授权之后到达的非研究类运行时修订，一经接受即触发 state 校验器抛错（源码推演，未运行验证）。** `intent_amendments.py:127` 无条件把 `plan_gate_revision_count` 加一；`invalidation_update` 只有 `RESEARCH_AFFECTING` 等价分支才清空已封存的 draft/deadline/budget（`state_invalidation.py:63-65`），`PROJECTION_ONLY`/`COMPOSITION_AFFECTING`/`RANKING_AFFECTING` 都保留；而 state 校验器要求 `draft.plan_revision == plan_gate_revision_count`（`state.py:620`），不匹配且 draft 已授权即抛 `ValueError`（`:629-635`）。追平点在 normalizer（`request_contract_normalizer.py:136`），但 router 的 update 一经合并、还没路由到 normalizer，state 已处于校验失败态。plan_gate 自身的 projection-only 分支不受影响（彼时 draft 未封存，命中豁免）。风险只在授权之后的运行时修订。与 F-09 同盲区，无任何测试触碰。

### 8.2 中（18 条）

**F-10｜candidate_gate：2792 行单文件、822 行单函数，七类职责顺序内联。** 对照 `intent_fidelity_gate` 全文件 140 行、判定下沉到 services 的既有范式。它是 F-01、F-12、F-27 的共同宿主：任何一段分支都无法单独构造输入去测。

**F-11｜另外几个超大文件同样单文件多子域。** `research_packet_output.py` 5156、`itinerary_planner/node.py` 3741（主函数 787 行）、`delivery_bundle.py` 3593、`itinerary_composition_v2.py` 3333（`materialize_trip_workspace` 596 行）、`transport_researcher/node.py` 2225、`agents/utils.py` 2094（`execute_tool` 约 456 行）、`chat.py` 1751。规模本身不是缺陷，但重复实现、死分支、零测试三类问题最密集的正是这些文件。建议以"新增子域必须新建模块"为增量规则止血，不做大重构。

**F-12｜`_RESEARCH_WORKERS` 在两道门各定义一份，连元素顺序都不同**（`artifact_gate.py:40-44` vs `candidate_gate.py:93-97`——顺序不同说明是各写而非复制）。新增第四个 researcher 漏改一处，会让一道门静默跳过它的校验。

**F-13｜终态 reason code 靠裸字符串拼接与前缀反解析，未识别值静默不进任何桶。** 写方 f-string（`delivery_finalizer.py:346,351`）；读方 `_terminal_bucket` 字面量比较 + startswith，兜底 `return None` 无日志（`run_completion_metrics.py:662-685`）。与 comparative-study §4.4 的前缀协议是不同载体、不同读写方。

**F-14｜预算维度名与字段名靠 `getattr(f"max_{dim}")` 反射绑定**（`run_budget.py:30-51`）。改一边不改另一边是运行期 AttributeError，且出错时机在预算耗尽收口路径上——最差的时机。

**F-15｜候选-意图评估：一个 try 罩住模型调用与 JSON 解析，任何异常整批降级 unknown，无重试无区分**（`candidate_intent_evaluation.py:371-411`）。unknown 在下游是安全方向，但一次网络抖动就让整批意图匹配全失且无可观测信号。

**F-16｜`_CHECKPOINT_GATE_NODES` 的第二份副本是死的，注释还在为它辩护**（`chat_stream_handlers.py:30`，全文件唯一命中就是定义行；`:22` 注释解释"为避免循环 import 保留本地副本"）。被注释背书的死副本会误导维护者以为两处必须同步。

**F-17｜platform 层约 4000 行治理/降级/证据代码零测试直接引用**（mcp_manager、gateway、fallback、output_guard、exposure_ledger 在 tests/ 下 grep 全空）。这些模块的失败模式是"静默不生效"。

**F-18｜排序键是 13 元素位置数组，位置含义无绑定，其中 4 个位置恒为常量**（构造 `candidate_ranking.py:118-141`；类型只约束 `min_length=1`，同一个类还把同批维度声明成具名字段——一份数据两套表示）。位置顺序变化会静默改变排序。

**F-19｜两个组合规则 kind 有枚举、有失败原因码映射，编译器却永不产出**（`REST_WINDOW`/`MAX_TRAVEL_TIME`：定义与映射齐全，`composition_rule_compiler.py` 无对应分支）。"每天要有休息窗口"这类意图不会被编译成规则，门也不会查，而代码外观让人以为已支持。

**F-20｜accommodation worker 文件头 docstring 与实现完全不符**（声明 Tavily/Brave/汇率白名单，grep 只命中 docstring 本身；实际走高德与 Nominatim）。第一屏内容直接误导排障。

**F-21｜`coverage_before/after` 是一对，三组调用点分别填 0/1/2 个**（itinerary 五处全不传；fidelity gate 只传 after；workspace 服务两个都传），无不变式保证成对。审计读者会把"变更前为空"读成"没差别"。

**F-30｜运行时修订吃掉计划门修改额度并强制二次批准。** 修订被接受即 `plan_gate_revision_count+1`（`intent_amendments.py:127`），链路必回 plan_gate 二次 `interrupt()`，此时额度已满、选项只剩 approve/cancel（`travel_planning.py:261,349,366`）。一次运行中补充 = 永久失去编辑权。行为跨三个文件，无单点文档，是否符合产品意图需要确认。

**F-31｜`NODE_PHASES` 漏了 `intent_fidelity_gate`**（`trace.py:20-50`，其余三道门都在 verification 组）。这道门的观测事件落到兜底 `postprocess`，与 workflow 信封混在同一阶段。同一节点名在 `amendment_continuations` 里有——两张手写表一个记一个漏。

**F-32｜节点名手写常量表有六处需要同步维护**：`amendment_continuations` 20 项、boundary 循环 8 组、worker 循环 3 项、`WORKER_NODES` 4 项、run_control 三张分窗集合、trace 阶段表。F-31 就是漏配实例；六处中只有分窗表有测试守卫（7.7 节）。

**F-33｜墙钟纵深防御在四道门上是四种强度。** candidate_gate 的路由带 try/except（`:2774-2777`）；artifact/quality 两道与 dispatcher 是裸调用；intent_fidelity_gate 的路由根本不读 `run_deadline`（全文件无 `observe_run_deadline`）。同一份"边上再挡一次墙钟"的意图写成了四种样子。

**F-36｜两条审计账本对"同 id 重复写"的策略相反。** cost_ledger 内容不一致即抛 `CostLedgerConflict` 并记错误（`cost_ledger_store.py:363-373`）；tool_audit 命中同 id 直接返回旧行、不比对不告警（`tool_audit_store.py:194-201`）。同层两个账本一个吵一个哑。

**F-38｜日志脱敏靠模块导入副作用开启。** `install_query_secret_redaction()` 在 `amap_route_search.py:44,50` 模块顶层被调用，全仓仅此一处；该模块不被 import，脱敏过滤器就不装。"安静不生效"型风险。

### 8.3 低（10 条）

**F-22** `ModelRouter.get_scope()` 零调用点（`router.py:862`；scope 子系统实际用 `get_fast`）。**F-23** `MCPManager.probe_tool` 全仓（含 scripts、tests）零调用（`mcp_manager.py:729`）。**F-24** `services/run_diff.py` 有测试无生产调用方——被测试的死码让覆盖率虚高。**F-25** `_AGENT_TOOL_POLICY` 与 `_FALLBACK_MAP` 是模块级字面量，改策略必须改代码；配合 F-17 意味着改错无从发现。**F-26** `FallbackQueryPolicy.fallback_penalty=0.2` 从未被读，同一个 0.2 在 `candidate_ranking.py:101-106` 又硬编码一遍。**F-27** `_MAX_TARGETED_RESEARCH_ATTEMPTS=1` 硬编码（`candidate_gate.py:99`），与组合修复预算分属两套无关的调参入口。**F-28** `output_guard.py` 456 行只有快答一个调用点——有文档背书的设计选择，记录投入产出事实，无需修复。**F-35** 四个语义相近的交付异常类分散四个文件、两种基类、无共同祖先（`DeliveryProjectionError(ValueError)`、`DeliveryPresentationError(ValueError)`、`PublicProjectionContractViolation(RuntimeError)`、`DeliveryContractViolation(RuntimeError)`）。**F-37** `safe_parse_json` 只支持 dict（`json_helpers.py:52-54`），两个需要数组的调用方各自绕开并留注释（reranker、query_rewriter）——有注释背书的已知限制，但 JSON 解析因此有两套实现。**F-39** destination worker 的 docstring 写 primary、实际是 fast（`destination_researcher/node.py:10` vs `:1349-1353`，代码旁注释解释了为什么改成 fast）——与 F-20 同类的文档漂移，一并归入文档债。

### 8.4 已排除（验证不成立的候选）

| 候选 | 排除理由 |
|---|---|
| `CheckpointPruningService` 无消费方 | 有：`scripts/prune_checkpoints.py:25-38` 是 CLI 运维入口。保留的较弱观察：无进程内定时调度，剪枝靠人工/外部 cron |
| `build_legal_open_slots`/`order_backfill_candidates` 零调用 | 在 `itinerary_planner/node.py:70-71` import、`:2450/:2454` 真实调用，且有测试 |
| 历史截断使自动压缩不可达 | 已修复；`agents/utils.py:143-159` docstring 是在记录该历史 bug，两个调用点均已去掉二次上限 |
| `RunDeadlineConfig` 文档与默认秒数不符 | 未复现；docstring 无分钟数，375/450/570/600 无误 |
| `mark_mutations_revalidated` coverage 恒为 None | 部分不成立，降级改写为 F-21（三组调用点填充程度不同） |

---

## 9. 覆盖边界与勘误

### 9.1 这份报告的结论强度

全部结论来自静态阅读与 grep，零测试运行、零代码执行。参考仓库是取样阅读：codex 只展开了 core/protocol/agent-roles（审批流 approvals.rs、guardian、ConfigLayerStack 未读），openpi 25 个扩展展开了 6 个。第 7 节的"他们怎么写的"只代表读到的部分。

### 9.2 仍未覆盖的部分（按体量）

`services/` 46 文件 19,455 行与 `entities/` 46 文件 15,790 行没有任何一份笔记以它为主范围，只有穿插覆盖（两者合计占全仓 35%）；`services/` 最大五个文件里 `delivery_projection.py`、`nominatim_place_search.py`、`amap_route_search.py` 全文未读。`db/` 目录 2460 行零覆盖（schema 契约怎么被强制、checkpoint 表怎么建）。`preset/` 856 行零覆盖（但已核实它在主链路上：作为图入参写进初始 state，落点是注入四段里的 `<active_preset>` 信封）。装配层 `builders.py` 326 行零覆盖。门的判定内核 `intent_verification.py`（766 行）只核实了调用契约与路由，判什么 blocking 未读。组合的确定性中段 `itinerary_composition_v2.py:1138-2068`（连接器抽取/对齐/物化的函数体）未读。RAG 索引侧（indexer/chunker/sources 等约一半行数）未读。模型计价（`config/pricing.py`）与预算异常在节点侧的捕获点未读。快答 node 的 RAG/标注辅助函数群未读。

### 9.3 勘误与裁决（材料间矛盾的最终结论）

图节点数是 22，不是某些笔记写的 20（`grep -c add_node` = 22）。`amendment_continuations` 是 20 项，差的两个是 `scope_clarifier`（合同建立之前，无处可回）与 router 自身。`NODE_PHASES` 覆盖 21 个图节点加 2 个非图条目，漏的是 `intent_fidelity_gate`。组合模型调用点的两套编号（C 系 / D 系）统一采用 D 系。"某文件已全文读完"的自我声明不可交叉采信——有一处声称全读的笔记在预算耗尽分支的因果顺序上是错的（正确版本见 4.2 节 delivery_quality_gate 行）。codex 规模采用实测口径（103 个顶层目录）；state 字段总数两个口径不一致（97 vs 118），本报告不使用任何字段总数。`destination_researcher` 的模型档以代码为准是 fast，docstring 是漂移的一方。住宿绑定的高德/Nominatim 是按国家互斥路由，不是失败降级链（docstring 原话 "never a fallback chain"）——早期笔记的"兜底"提法不准确。

---

## 10. 附录

### 10.1 文件地图（目录级，`src/travel_agent/` 共 101,325 行）

| 目录 | 行数 | 文件数 | 内容 | 本报告的覆盖来源 |
|---|---|---|---|---|
| `agents/` | 22,547 | 37 | 节点实现：scope、orchestrator（planner/dispatcher/四门）、三 researcher、itinerary、fast_answer、共享 utils | 多份笔记，覆盖充分 |
| `services/` | 19,455 | 46 | 候选流水线、意图、组合、交付投影、provider 接入、run 控制服务 | 穿插覆盖（9.2 节） |
| `entities/` | 15,790 | 46 | 全部 typed 契约：state、合同、候选、组合、Bundle、预算 | 穿插覆盖 |
| `api/` | 7,785 | 21 | FastAPI 路由、SSE 流、恢复端点 | entry 笔记 |
| `infrastructure/` | 7,273 | 15 | 各 store、checkpointer、租约、账本 | persistence 笔记 |
| `rag/` | 5,129 | 20 | 检索管线 + 索引侧 | 检索侧覆盖，索引侧未读 |
| `workflows/` | 4,467 | 15 | 图定义、run 控制、deadline/budget、交付两节点 | 覆盖充分（第二遍核对基准） |
| `memory/` | 3,787 | 10 | 会话/长期记忆、压缩、抽取 | memory-rag 笔记 |
| `tools/` | 3,187 | 9 | registry、gateway、governance、MCP、降级 | platform 笔记 |
| `db/` | 2,460 | 12 | schema 契约、备份、指纹 | 零覆盖 |
| `panels/` | 2,209 | 2 | Constraint Pack 装配与投影 | scope 笔记（选段） |
| `config/` | 1,820 | 9 | 声明式配置管线（本仓工程质量高地之一） | 工程对照 §7.4 |
| `models/` | 1,715 | 5 | 模型路由、usage、strict schema | platform 笔记 |
| `preset/` | 856 | 6 | 产品预设 | 零覆盖（主链路接线已核实） |
| `utils/` | 765 | 11 | 杂项 helper | 零散 |
| `guardrails/` | 631 | 3 | 输入/输出护栏 | platform 笔记 |
| 顶层 | 455 | 4 | builders / capabilities / local_profile | 零覆盖 |

### 10.2 工作底稿

本报告的原材料是 22 份读代码/分析笔记，位于 `tmp/review/`（gitignored，随工作区存在）：17 份子系统与参考仓库笔记、4 份分析件（`routing-verified.md` 权威路由表、`infoflow.md` 信息流、`engineering-comparison.md` 工程对照、`findings.md` 发现清单）加 1 份缺口清单（`gaps.md`）。报告正文已收录全部关键结论与证据；底稿保留了更长的推导过程，需要留档可将该目录拷入 `docs/review/worksheets/`。
