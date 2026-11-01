# 01：用自然语言需求和任务说明贯通规划链路

- 编号：20261101-0035-generation-01-natural-language-foundation
- 状态：待真人验收
- 创建：2026-11-01 00:35
- 顺序：本批第 1 项，无前置任务
- 执行前先读：[本批总览](../discussions/20261031-generation-chain/README.md)、[工作目录 README](../README.md)、`AGENTS.md`、`docs/architecture/overview.md`、`docs/invariants.md`、`backend/tests/README.md`

## 1 用户反馈

> 我们不应该把它的所有内容全部都结构化，应该是一小部分适合结构化的内容，我们去给它做结构化，其他的我们都放到用户需求里面。

> 调研方案其实就是一个用来给后续的不同 Agent 的一小段提示词。

用户希望基础表单以结构化信息保存，自由描述、问答与补充以自然语言需求传递；调研方案由模型用几段文字形成，再将相关任务交给各 Agent。用户原话不需要逐条语义确认。

## 2 现象与发生条件

两种入口进入正式规划后，自然语言经过分句、归类、意图和约束合同，再生成研究标签、查询计划和精确操作清单。Worker、候选目录、天气与最低交付数据都依赖这些中间产物。只改计划正文，实际执行仍会受旧体系限制。

本项首先替换这条信息链，保留现有入口问答的可运行方式；工作台立即进入和联网问答由 02 完成。

## 3 根因

代码位置为改写起点，行号以开工时为准：

- `backend/travel_agent/conversation/intake.py:477`、`conversation/chat/preparation.py:502`：现有原文与问答已经可以组成图输入。
- `backend/travel_agent/planning/requirements/normalization/model.py:38`、`requirements/approval.py:568`：逐条理解、语义检查与计划确认混合。
- `backend/travel_agent/planning/research/selection.py:38`、`research/plan.py:68`：从标签选择到合同驱动的查询和分工。
- `backend/travel_agent/planning/state.py:382`：合同、意图、查询与操作批准的相互强依赖。
- 三个 Worker 的 `planning/research/*/node.py`、`research/packets.py`、`research/assembly.py`：强制消费查询计划、来源范围和相关版本。
- `planning/weather/node.py`、`planning/delivery/minimum_draft.py`：天气和后续交付也依赖旧合同与授权产物。
- `backend/travel_agent/tools/execution.py:60`：精确操作清单缺失时研究工具直接被拒绝。

这些是同一底座的生产者和消费者，必须一起迁移。

## 4 方案

目标状态：模型直接使用基础信息和需求文字形成自然语言调研方案；用户确认后，后续角色实际接收相关文字与任务，整条链路能够运行。

必须做：

1. 以现有存储为基础，保存适合结构化的少量基础信息、用户输入与问答，以及可忠实更新的当前需求文字。新表达能更新旧想法；不再强制拆分成逐条意图、约束、来源裁决或语义确认。
2. 模型根据当前需求写出简短、针对本次旅行的调研方案和各角色任务说明。计划不是标签选择或模板拼接。确认、补充、取消围绕同一份当前方案进行。
3. 同步改写后续必须消费旧产物的 Worker、候选包、目录、天气、最低交付数据、状态检查和修订入口。保留运行与产物的必要归属，使用简单的当前需求/方案版本表达；不维持伪造 Intent、空合同或回填旧查询计划的桥接层。
4. 移除与目标冲突的精确操作预编译和执行期参数匹配。Worker 在自身可用工具范围内根据任务调用，工具参数按实际需要生成。保留取消、运行归属、实际工具结果、费用与时间控制。
5. 用户仍需确认调研方案后才进入正式分工研究。后续 02 增加的理解阶段查询有独立使用场景，不再用“所有 Provider 都要等审批”约束整条应用。
6. 当前各角色能接收相关基础信息、需求文字和任务说明；同步重写这一边界的提示词与上下文，不把提示词改造留到最后。
7. 清理失去消费者的归一化、标签选择、语义确认、查询编译与 operation 层及其专属测试。更新架构总览、不变量与实际改变的接口说明。

执行者自己决定：需求文字的存储字段、现有类型的简化方式、方案外层结构、版本表达，以及必要的 API/SSE/checkpoint 调整。本项授权连带改变这些边界；数据库确需字段变化时按现有迁移机制完成。

不许碰：无关页面与视觉素材、私有模型配置和密钥、用户已有旅行数据。保留可靠交付、运行取消和租约等仍有实际职责的机制。

## 5 停下来报告的情况

一般代码耦合、接口字段调整、旧测试与新方向冲突均在本项范围内。只有需要破坏已有旅行数据、变更用户未决定的产品行为，或真实服务调用授权不足时报告。旧 checkpoint 可清楚说明恢复能力变化，不为保留旧链路创建长期双轨。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 自由描述和回答以文字进入实际 Worker 与组合上下文，无逐条语义审批。
2. 用户确认的方案与后续使用的任务说明一致；补充可更新方案。
3. 从现有入口到 Worker、候选装配和交付能够连续运行，不要求旧合同或精确查询清单。
4. 合理的动态查询和详情补查能到达工具边界，仍能取消并计入实际执行上限。
5. 无为过渡保留的两套需求权威、空壳合同和已无消费者的编译层。

### 6.2 必须运行的检查

在仓库根目录，使用隔离测试数据和模型/外部服务替身：

- `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/research/test_model_research_plan_flow.py backend/tests/planning/test_checkpoint_input_binding.py -q`
- `.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/conversation/test_chat_execution.py backend/tests/planning/research/test_worker_recovery.py -q`
- 改动 TypeScript 时：`npm --prefix frontend run type-check`。
- 对本项改动的 Python 文件运行 Ruff；涉及迁移时追加对应临时数据库检查。

重写或删除只验证旧约定的用例。测试文件因责任变化合并或删除时，记录实际运行的替代路径，保留“文字需求→方案→研究→交付”的代表性行为验证，不为旧文件名保留空测试。不跑全量套件。

### 6.3 实屏证据（执行者提供）

本项不重做工作台。若方案确认界面数据变化，用虚构会话保存当前方案及一次补充后的画面至 `output/polish/20261101-0035-generation-01-natural-language-foundation/`。模型质量留待本批最终真实联调，离线替身通过仅证明链路。

### 6.4 真人验收（用户操作）

1. 提交包含自由偏好的旅行需求并回答问题 → 计划具体体现原意，无逐条需求确认。
2. 补充一个改变当前想法的要求 → 调研方案更新，确认后各角色按最新任务工作。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-11-01 03:35 · ZCode／GPT-6

- 改动摘要：把正式规划链路改为“受控身份＋当前需求文字＋模型研究方案与角色任务”。用户原话、回答和补充保存为当前需求；方案生成失败或补充后重新生成方案，用户在计划门确认同一版本后，任务直接交给目的地、交通、住宿和行程组合。删除请求合同、Intent/Constraint 归一化、标签选择、查询计划、精确 operation 编译与执行期参数授权；保留取消、租约、预算、期限、工具审计、重试与真实工具结果。研究 Worker 改为在自身可用工具范围内按任务决定查询和参数；候选包、目录、天气、最低交付、状态校验和修订入口改用规划版本与当前需求。同步清理失去消费者的后端与前端语义确认组件、旧测试和文档。
- 改动文件：`backend/travel_agent/planning/{graph,state,execution,invalidation,recovery,nodes,presentation,trace,workflow}.py`、`planning/requirements/{natural_language,approval,amendments,amendment_contracts,inputs,generation_contracts,summary}.py`、`planning/delivery/{minimum_draft,bundle,report_projection}.py`、`planning/research/{research_plan_node,plan,prompts,packets,catalog,assembly,history,execution_lease,provider_contracts,provider_assignments,provider_scope_ids}.py`、`planning/research/{destination,accommodation,transport}/node.py`、`planning/research/output/{metadata,parsing,lineage}.py`、`planning/itinerary/{node,prompts,materialize,day_capacity,selected_supply}.py`、`planning/requirements/constraints/{planning,assembly,sources}.py`、`tools/execution.py`、`conversation/chat/{contracts,execution,preparation,progress_events}.py`、`api/{sse_projection,audit_projection}.py`、`llm/task_routing.py`；删除旧归一化、语义确认、请求合同、查询/能力计划、selection、operation 编译与授权模块；前端删除 `SemanticRequirementGate`、`semanticChallenge`、计划门的语义确认字段和旧结构化要求区域，并删除纯语义确认/旧计划门追问的 e2e；更新 `docs/architecture/overview.md`、`docs/invariants.md`、`docs/adr/ADR-0010`、`docs/adr/ADR-0013`。测试同步改写或删除只验证旧合同的用例。
- 偏离方案及理由：保留个人画像、手写记忆和 preset 的确定性 Constraint Pack，仅去掉自由文本分句和语义抽取；这些字段仍服务过敏提醒、天气风险、交通偏好和快答。按用户要求未保留旧数据、旧 checkpoint 或旧交付 Bundle 的兼容读取，相关契约版本随结构变化升级（Packet v7、Catalog v8、Workspace v12、Bundle v11）。未提供方案确认界面截图：本项不重做工作台，且用户明确本批以后端验证为主；界面沿用原有布局，仅文案和纯文本方案内容变化。
- 实际运行的检查与结果：`pytest -c backend/pyproject.toml backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/research/test_model_research_plan_flow.py backend/tests/planning/test_checkpoint_input_binding.py -q` → 8 passed；`pytest -c backend/pyproject.toml backend/tests/conversation/test_chat_execution.py backend/tests/planning/research/test_worker_recovery.py -q` → 28 passed；后端非数据库全量 `pytest -c backend/pyproject.toml backend/tests --ignore=backend/tests/db -q` → 768 passed；`ruff check backend` → 通过；`npm --prefix frontend run type-check` → 通过；`npm --prefix frontend run test -- --run` → 18 个测试文件、125 项通过；`backend/tests/db/test_offline_sql.py` → 6 passed（未改迁移）；`git diff --check` → 通过。新增离线链路测试覆盖：补充前不启动研究、补充后方案与角色任务进入实际 Worker 和组合、动态地点查询到达工具边界且只执行预算内的调用、真实候选进入目录并被组合选用、交付 Bundle 保存当前需求、追加要求不重置预算和期限。
- 实屏证据：不需要。本项不改工作台布局；方案确认界面只使用已有的 `plan_text`、`steps` 和 `decision_options`，未新增界面状态。
- 遗留问题或需要指挥决定的事：1）真实模型能否写出高质量方案、追问和自动返回研究，留待本批最终真实联调；离线替身只证明链路。2）旧 checkpoint、旧交付 Bundle 和旧采购数据不再兼容读取，数据库可重建；本轮未删除任何数据库数据。3）方案确认界面的文案与纯文本方案展示未做真实截图验收。4）未运行 Playwright e2e；其中依赖旧计划门展示的 `session-state`、`planner-intake` 等夹具未在本项改写，留给 02/05 工作台任务同步；本轮只删除了纯语义确认和旧计划门追问的 e2e。5）现有 `docs/polish/tasks/2026103*` 历史任务记录未改写；本批以本任务和后续 02–06 为准。

### 第 2 轮 · 2026-11-01 11:18 · ZCode／DeepSeek V4.1 Flash 1017

- 改动摘要：按指挥验收的四个返工项收尾。1）前端契约版本镜像同步到后端当前值（交付 Bundle v11、旅行工作台 v12），e2e 会话夹具同步到同一版本，并新增一条直接读取后端常量比对的回归检查；2）删除语义确认孤儿夹具与 `.plan-gate-requirements` 样式；3）修正契约注释、入口证据 docstring、Clarifier 日志，并把 constraints 装载层仍以已删「请求契约归一化／ConstraintNormalizer」命名的 docstring 与日志前缀改为实际职责；4）删除无消费者的 `structured_constraint_context`、恒为 None 的 `precomputed_free_text_constraints` 参数链与 `merge_precomputed_constraint_extraction`，移除摘要卡不可达的 `boundary=="verified"` 分支并简化调用方。
- 改动文件：`frontend/src/features/travel/types/{delivery,workspace}.ts`、`frontend/src/features/travel/types/contractVersionMirror.test.ts`（新增）、`frontend/e2e/fixtures/xianBundle.ts`、`frontend/e2e/fixtures/semantic-gate.{tsx,html}`（删除）、`frontend/src/index.css`、`backend/travel_agent/conversation/chat/contracts.py`、`backend/travel_agent/conversation/intake_evidence.py`、`backend/travel_agent/planning/requirements/{entry,summary}.py`、`backend/travel_agent/planning/requirements/constraints/{sources,assembly,extraction,loading}.py`。
- 偏离方案及理由：返工项 1 的检查放在前端 `vitest`（`npm run test`／`npm run check` 内执行），同时比对交付 Bundle、旅行工作台、天气快照三个前后端镜像常量及 e2e 会话夹具，不放 pytest：`backend/tests/README.md` 要求类型与生成物检查交给各自工具，不用 pytest 读源码重查。e2e 夹具没有改为从 `src` 导入常量：`tsconfig.node.json` 只列出 `e2e/**/*.ts`，跨 project 导入会触发 TS6307，故保留字面量并由上述测试守住。
- 实际运行的检查与结果：`pytest -c backend/pyproject.toml backend/tests/planning/requirements/test_control_plane.py backend/tests/planning/research/test_model_research_plan_flow.py backend/tests/planning/test_checkpoint_input_binding.py -q` → 8 passed；`pytest -c backend/pyproject.toml backend/tests/conversation/test_chat_execution.py backend/tests/planning/research/test_worker_recovery.py -q` → 28 passed；后端非数据库全量 `pytest -c backend/pyproject.toml backend/tests --ignore=backend/tests/db -q` → 768 passed；`ruff check backend` → 通过；`npm --prefix frontend run type-check` → 通过；`npm --prefix frontend run test -- --run` → 19 个测试文件、129 项通过（含新增镜像检查 4 项）；`git diff --check` → 通过。另做一次反向验证：临时把 `delivery.ts` 改回 v10 后镜像检查 2 项失败，恢复 v11 后 4 项通过，确认单边升级会被拦下。未运行数据库迁移检查（本轮无迁移改动）与 Playwright e2e（本轮为后端收尾与常量清理，未改工作台交互）。
- 实屏证据：不需要。本轮只改契约版本常量、注释与死代码，界面与布局未变化；`isPublicDeliveryBundle` 等前端校验使用同一常量，版本一致由新增检查覆盖。
- 遗留问题或需要指挥决定的事：1）真实交付在前端实际加载仍属本批最终真实联调范围；本轮只证明前后端版本一致，未跑一次真实生成。2）`frontend/e2e/fixtures/generation-progress.tsx`、`e2e/session-state.spec.ts` 的死代理名夹具、`e2e/fixtures/sessionData.ts` 的旧计划门展示依赖仍按第 1 轮记录留给 02/05；本轮只同步了版本常量。3）`docs/audits/2026-10-31-generation-chain/` 仍保留旧版本号与旧模块描述，作为当时状态的审计快照未改写。

### 第 3 轮 · 2026-11-01 11:50 · ZCode／GPT-6.1

- 改动摘要：复核已有两轮实现并修复剩余边界：补充要求更新规划版本时清除旧组合修改、天气影响、供应商结果与参考班次；计划门恢复同时收到运行中补充时保留确认、修改、重试或取消决定，拒绝补充后按原决定继续；确认按钮在存在未提交修改时禁用，非补充动作不接收正文。移除无生产者的未决语义状态、旧计划门澄清分支和重复 edit 动作；正式研究不再暴露无法恢复的 ask_user 路径。移除从自由文本关键词强制跨日查询的逻辑，由交通角色按完整需求自行选择参数。旧检查点不满足当前规划版本时提示重新规划。取消、租约丢失或断流信号在工具缓存、降级、铁路查询、路径补查和快答汇率预检中直接传播，不再作为普通失败继续调用。
- 改动文件：`backend/travel_agent/planning/{execution,graph,invalidation,state,workflow}.py`、`planning/requirements/{approval,route_legs,constraints/sources}.py`、`planning/research/{plan,provider_outcomes,destination/node,transport/node,transport/prompts,transport/scope,transport/rail/binding,transport/rail/stations,accommodation/node}.py`、`planning/itinerary/{day_capacity,place_resolution,prompts,rail_paths}.py`、`tools/{access,builtin_tools,execution,registry}.py`、`conversation/{answer/tool_context,chat/contracts,chat/preparation}.py`；`frontend/src/features/travel/{components/planning/TripBriefPlanGate,model/planApprovalGate,model/planGateActions,types/planner}.ts(x)`；`docs/architecture/overview.md`；相关回归见 `backend/tests/planning/{requirements/test_control_plane,research/test_model_research_plan_flow,research/test_worker_recovery,itinerary/test_rail_route_path_completion,test_checkpoint_input_binding}.py`、`backend/tests/{api/test_chat_use_cases,conversation/test_chat_execution,runtime/test_run_command_contract,tools/test_tool_policy_contract}.py` 和 `frontend/src/features/travel/model/planApprovalGate.test.ts`。
- 偏离方案及理由：研究阶段暂不提供 ask_user，因为现有图无法在该路径正确暂停和恢复；理解阶段的联网提问按 02 实施。自由需求按时间顺序保留原文和补充，由方案及各角色提示明确以最新表达为准，未增加语义提取或逐条审批。
- 实际运行的检查与结果：任务 6.2 第一组 `test_control_plane.py test_model_research_plan_flow.py test_checkpoint_input_binding.py` → 19 passed；第二组 `test_chat_execution.py test_worker_recovery.py` → 34 passed。铁路路径补查 `test_rail_route_path_completion.py` → 10 passed；另运行控制命令、预算、工具策略、接口、入口、组合、节点、上下文与来源的定向检查 → 186 passed（随后补充的取消修复已由上述相关文件复跑）。`npm --prefix frontend run type-check` → 通过；方案门与契约镜像 Vitest → 8 passed；`.venv/bin/ruff check backend` 与 `git diff --check` → 通过。未重复运行全量套件或数据库迁移检查，本轮无迁移改动。
- 实屏证据：虚构旅行和离线 API 替身，`output/polish/20261101-0035-generation-01-natural-language-foundation/round-3-final-before.png`、`round-3-final-edit.png`、`round-3-final-after.png`；检查原方案、未提交修改提示及补充后方案，不代表真实模型生成质量。
- 遗留问题或需要指挥决定的事：GLM 独立代码验收发现的补充拒绝续点、旧界面分支及取消传播问题均已修复并复核通过；真实付费模型、真实 Provider 与在线取消时序未运行，留待本批授权后的真实联调。旧计划门 e2e 夹具仍由 02/05 更新；旧 checkpoint 和旧交付不做兼容读取。当前需求保留旧表达与按序追加的新表达，由模型结合方案理解；自然语言中改变基础旅行身份的隐含说法仍可能绕过现有关键词守卫，基础条件重规划由 06 处理。方案生成在首次确认前每次调用有 120 秒超时，但尚无该阶段的累计调用次数或费用上限，正式研究的预算在确认时封存；02 改写理解阶段时需一并接入实际费用和时间控制。本轮只用离线替身，没有修改用户数据。

## 8 指挥验收（指挥填写）

### 2026-11-01 03:55 · 代码验收通过

对照第 6.1 节：

1. **文字进入实际研究与组合**：`current_requirements` 由入口原文、回答和 `IntentAmendment` 组成；`research_plan_generator`、三个 Worker 的 `<research_runtime>` 和 `_build_composition_prompt` 都读取它。前端语义确认组件、API 字段和计划门 `phase=semantics` 已删除，没有逐条语义审批。离线链路测试实际检查了补充文字出现在三个 Worker 请求和组合请求中。
2. **确认方案与后续任务一致**：计划门的 `plan.steps[].tasks` 与 `planner_node` 使用的是同一个 `ResearchPlan.tasks()`；测试逐项核对三个研究角色和行程组合收到的任务文本。补充会追加到当前需求、推进 `PlanningGeneration`、重新生成方案并重新请求确认。
3. **连续运行且不依赖旧合同**：完整离线用例从受控身份和文字需求运行到方案确认、三个 Worker、候选目录、组合、投影和 Bundle 保存；旧查询计划、operation manifest、精确参数授权和对应模块没有生产消费者。
4. **动态查询与控制边界**：Worker 只在 `filter_tools_for_agent` 给出的工具范围内调用；`execute_tool` 不再做 operation 参数匹配，但仍先经过 Gateway、取消检查和 `guard_run_budget`。测试用两个动态地点查询验证第一个执行、第二个在预算上限处被拒绝；既有取消与租约契约测试继续通过。
5. **清理结果**：`capability_planning`、`query_planner`、`selection`、`operation_compiler`、`operation_authority`、归一化、语义确认、意图合同、Brief/Query/Capability 合同及其专属测试已移除；`request_contract` 只剩面向补充要求的 `amendment_contracts`，`authorization_context` 只剩执行租约并已改名。个人画像、手写记忆和 preset 只保留确定性映射，不再解析自由文本。

检查复核：执行记录中两组定向检查分别为 8 passed、28 passed；后端非数据库全量 768 passed、离线 SQL 6 passed；Ruff、前端 type-check、前端 125 项单测和 `git diff --check` 均通过。检查面向当前代码和虚构替身，没有调用真实付费模型，没有清理用户数据库。

结论：代码验收通过，状态改为“待真人验收”。真人验收按 6.4 进行，重点看真实模型是否把自由偏好和补充真正转化为研究任务；旧数据读取能力变化已记录在执行记录中。

### 2026-11-01 11:08 · 代码验收返工

复审背景：第 1 轮验收记录之后，工作区仍有尾段改动（presentation.py、constraints/assembly.py、constraints/loading.py、agentStages.ts、orbState.ts、TripBriefPlanGate.tsx、harness_experiments.py，03:55–03:58），多数未被上一轮记录覆盖，故对最终状态整体复审。6.2 全部检查与后端非数据库全量在当前工作区复跑通过（定向 8＋28＋6 passed、全量 768 passed、Ruff、type-check、前端 125 项、git diff --check），另以四个只读审查分片覆盖需求底座、研究链与工具边界、交付与前端、横切一致性与测试映射。核实结论：6.1 第 1、2、4 条成立，第 5 条后端实质成立（残留见返工项 4）；第 3 条在交付边界不成立，判返工。上一轮验收与执行记录均未发现下列第 1 项。

返工项：

1. **前端契约版本镜像未随后端升级（阻断）**。后端本轮将交付 Bundle 升为 `journeypilot.delivery_bundle.v11`（`planning/delivery/bundle.py:35`）、工作台升为 `journeypilot.trip_workspace.v12`（`planning/workspace.py:31`），但 `frontend/src/features/travel/types/delivery.ts:5` 仍为 v10、`frontend/src/features/travel/types/workspace.ts:1` 仍为 v11，两文件本轮未改。为何不行：HEAD 上前后端一致（v10/v11），本轮单边升级构成回归；`isPublicDeliveryBundle` 在 deliveryProtocol、bundleConflict、TripWorkspaceShell、useSessionManager、useDeliveryEventRecovery、useCurrentBundleWeatherRefresh 处逐字比对，`storage/delivery_bundle_store.py:240` 读取同样强制 v11，此后每次新交付都会被前端判废，工作台、会话恢复与交付完成协议加载不出；前端单测用同批旧常量自建夹具，125 项全过证明不了这个边界。期望结果：前后端契约版本一致，新交付能被前端接受并实际加载；并补一条防止单边升级再次漏网的检查（形式执行者定）。
2. **清理失去消费者的语义确认残留**。`frontend/e2e/fixtures/semantic-gate.tsx` 与 `semantic-gate.html` 仍导入已删除的 `SemanticRequirementGate`、`semanticChallenge`，其消费 spec 已删；`frontend/src/index.css:4398-4402` 的 `.plan-gate-requirements` 样式块对应的「已识别的旅行要求」区域已删。为何不行：属“必须做 7”的清理范围，留下导入不存在模块的死文件与孤儿样式。期望结果：孤儿夹具与样式删除，前端内无对已删组件的引用。
3. **修正与代码不符的说明**。`conversation/chat/contracts.py:26` 注释漏列 `retry` 动作；`conversation/intake_evidence.py:5` docstring 仍写 "kept separately for later semantic confirmation"，该机制已删；`planning/requirements/entry.py:55` 日志仍写「进入请求合同归一化」。为何不行：说明与实际行为不符，误导后续执行与排障。期望结果：注释、docstring、日志与当前行为一致。
4. **清理本轮删出的 constraints 死管道**。`requirements/constraints/sources.py` 的 `structured_constraint_context` 已无消费者且 docstring 仍描述已删的归一化调用方；`precomputed_free_text_constraints` 参数链（constraints/assembly.py、loading.py、extraction.py）生产者已删、恒为 None；`requirements/summary.py` 的 `boundary=="verified"` 分支不可达（唯一调用传 "brief"）。为何不行：属“必须做 7”失去消费者的清理。期望结果：死函数、恒空参数与不可达分支移除，调用方相应简化，6.2 检查复跑通过。

记入但不列入本轮返工（已有归属）：`requirements/evidence_resolution.py` 及其专属测试在 HEAD 即无生产消费者（本任务未触碰），归全仓清扫；`frontend/e2e/fixtures/generation-progress.tsx` 与 `e2e/session-state.spec.ts` 的死代理名夹具改写，执行记录已声明留给 02/05；三个 Worker 读取恒空的 `recommended_tools/excluded_tools` 与 `research/plan.py` 缩进观感，02/03 改写同一片代码时顺带。

本轮不提交：用户要求审查通过后提交，审查未通过。返工完成后按 6.2 复跑，并补跑第 1 项要求的前后端版本一致性检查。

## 9 真人验收（指挥代录）
