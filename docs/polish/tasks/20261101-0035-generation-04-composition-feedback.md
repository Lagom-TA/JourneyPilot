# 04：组合自主补查，并反馈对应研究者重做严重错误

- 编号：20261101-0035-generation-04-composition-feedback
- 状态：待代码验收
- 创建：2026-11-01 00:35
- 顺序：第 4 项，依赖 [03](20261101-0035-generation-03-research-supply.md) 代码验收通过
- 执行前先读：[本批总览](../discussions/20261031-generation-chain/README.md)、[工作目录 README](../README.md)、`AGENTS.md`、`docs/architecture/overview.md`、`backend/tests/README.md`

## 1 用户反馈

> 组合 Agent 是需要给他一些能力的，要不然他在面临信息缺少的时候，会没有办法进行信息的补充。

> 不可以让行程组合为他们每个 Agent 的错误买单。

局部问题由组合直接补查，严重错误或完全不可用的研究交回对应 Worker 重做；保留其他有效成果，修正后继续组合。

## 2 现象与发生条件

组合目前主要是一次结构化生成，后面只有预设的路线补全。dispatcher 把研究失败当作步骤结束，组合没有反馈对应研究者再返回的分支。目录保留旧候选的逻辑也可能让被纠正的错误重新混入成果。

## 3 根因

- `backend/travel_agent/planning/itinerary/composition.py:19`：直接 ainvoke，没有自主工具研究和反馈动作。
- `backend/travel_agent/planning/itinerary/node.py:120`、`:192`：预设接驳补全与组合失败出口。
- `backend/travel_agent/planning/research/dispatch.py:19`、`:75`：失败视为结束、窗口关闭可跳组合。
- `backend/travel_agent/planning/research/history.py:34`：旧目录继续保留未出现候选，未表达“错误成果已被替代”的实际语义。
- `backend/travel_agent/planning/graph.py`：需要增加对应的真实路由，而非仅写提示词。

## 4 方案

目标状态：组合负责整趟旅行的选择与时间安排，有实际工具能力；遇到无法使用的上游成果，反馈给责任 Worker 修正后继续。

必须做：

1. 组合使用完整需求、规划意图和充分研究成果，能够调用与安排有关的工具，自主补查地点、具体衔接等局部信息。仅声明工具名而没有可执行调用不算完成。
2. 信息影响选点、时间或交通时，组合吸收补查结果调整安排；避免先固定时间、后查到实际路程却不调整。
3. 模型可以发出给某研究 Worker 的自然语言反馈，说明问题、为什么无法安排、需要重做什么；程序路由到该角色，Worker 接收原任务、相关需求、错误成果及必要草稿，重做后返回组合。
4. 返研只更新实际受影响成果。有效候选和其他研究保留；错误或被替代内容退出后续决策，不能作为“未入选备选”又自动合并回来。相关下游建议和草稿按实际影响修正。
5. 辅助价格、详细介绍缺失不触发返研。问题是否严重由模型结合能否支撑行程判断，不加评分 Agent、固定缺陷枚举、需求核销门或用户返研审批。
6. 使用现有执行上限、取消与恢复能力。调整原有“研究窗口关闭就不能再研究”的阶段控制，使组合阶段确实可以在剩余运行资源内返研；不因返回 Worker 重置已花费用、调用量或期限。资源不足或返研仍无可用结果时，保留有效成果并明确当前无法完成的实际安排，不把失败伪装成交付，也不增加新的无限自修复流程。
7. 工具补查、返研、返回组合在同一工作台可见；同步重写组合和返研上下文、提示词及阶段说明。

执行者自己决定：反馈动作的外层结构、图路由、草稿续用和结果替换方式、可用工具集合。允许必要的状态与事件调整，不要求新增协调 Agent 或通用调度框架。

不许碰：用户需求的自然语言表达方式、无关界面、私有配置和用户已有数据。最终文案与地图整理归 05。

## 5 停下来报告的情况

若完成目标需要改变已经确认的旅行范围、自动追加付费服务，或覆盖用户已有交付，报告实际需要。正常返研分支、状态变更和旧测试调整已授权。

## 6 验收标准

### 6.1 代码验收（指挥检查）

1. 组合可以实际补查并使用结果，尤其能根据交通时间调整安排。
2. 严重不可用研究经过“组合反馈→指定 Worker→新成果→继续组合”。
3. 其他有效成果保留，错误旧候选不回流。
4. 缺价格可正常安排，无评分与额外审批；取消和资源不足能清楚结束。

### 6.2 必须运行的检查

- 新增或合并少量行为场景到 `backend/tests/planning/itinerary/test_research_feedback.py`：`.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/planning/itinerary/test_research_feedback.py backend/tests/planning/itinerary/test_connector_route_completion.py backend/tests/planning/research/test_worker_recovery.py -q`
- 直接验证一次局部补查、一次指定角色返研往返和错误候选替换。模型和 Provider 才使用替身，内部路由与状态真实执行。
- `npm --prefix frontend run type-check`
- 本地前端启动后，在 `frontend/` 执行：`JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8080 npx playwright test e2e/research-progress.spec.ts --workers=1 --output=../output/polish/20261101-0035-generation-04-composition-feedback/playwright`，加入返研后继续组合的代表事件。

不为每种错误建立测试矩阵或 prompt 全文断言。

### 6.3 实屏证据（执行者提供）

保存一次虚构返研与继续组合的工作台状态。行为正确以真实内部调用链测试证明，界面截图只证明进度表达。

### 6.4 真人验收（用户操作）

1. 生成行程时查看过程 → 组合可以继续查所需信息，安排吸收查询结果。
2. 人工验收严重错误场景可用明确标注的本地数据 → 对应角色重做后继续，其他研究仍在。真实模型是否主动判断正确留待最终联调。

## 7 执行记录（执行者填写）

### 第 1 轮 · 2026-11-01 20:40 · ZCode／GLM-5.3（信息勘察由 DeepSeek V4.1 Flash 1017 工作流完成，事实地图见 `output/polish/20261101-0035-generation-04-composition-feedback/research-notes.md` 与 notes/ 六份分域笔记）

- 改动摘要：把「组合＝一次结构化生成，研究失败即步骤结束」改为「组合有真实工具能力，严重不可用研究经反馈返对应 Worker 重做后继续组合」。①组合补查：`itinerary/composition.py` 由单次 ainvoke＋response_format 改为 `streaming_react_loop`（≤5 轮，stream_queue 让工具事件进工作台）；`tools/access.py` 的 itinerary_planner 策略由 deny-all 放开为地点/路线/网页检索白名单（不含 ask_user/knowledge_search）；组合提示词新增 `<tool_use>`（先查询后落时间、查询结果只是资料）与 `<research_feedback>`（返研请求输出模式；判断标准＝成果能否支撑行程；价格等辅助资料缺失不返研；一次只请求一个角色）。②返研合同：新建 `research/feedback.py`（ResearchRedoRequest、解析、`RESEARCH_REDO_ROUNDS_CAP=1`、错误成果摘要 6000 字上限、返研消息构造与消费）；state 新增 `research_redo_requests`（单写者替换）与 `research_redo_rounds`；三个 Worker 节点在任务消息后追加「组合反馈（问题/为什么无法安排/需要重做什么）＋原任务＋相关需求＋上一轮错误成果摘要」，消费后从待处理集合移除；`invalidation_update` 清空两个字段。③图路由：`graph.py` 组合出边新增返研目标（`_route_after_itinerary` 读 `next_agent`）；`dispatcher` 在组合组未完成重入时同步重建候选目录（返研新 packet 进入组合可见目录）；组合节点 `_research_redo_update` 写完整 assignments（新增 `_r2` 键、经 `plan.build_worker_assignment` 续编 provider 证据尝试，避免同 attempt 冲突）、组合置回 pending、清 placement_skeleton；组合每次返回显式清 `next_agent`，杜绝残留把图引回 Worker 的死循环。④返研窗口：`execution.py` `_model_window_for_node` 对带轮次后缀的返研 Worker 使用 composition 窗口——研究窗口（closeout）关闭后仍可在组合窗口内返研，预算与期限沿用封存快照、不重置已花费用。⑤错误候选退出：`history.py` 目录重建时，同 Worker 已有新 packet 且旧 packet 来自 state（真实 Worker 轮次）→ 旧 packet 整体退出，不再作为「未入选备选」回流；组合接驳补全产生的目录内 packet（不在 state）仍保留；`memory/research_context.py` 上游视图按 Worker 最高轮次过滤。⑥进度可见：组合补查与返研轮复用既有 tool_start/tool_done 事件（同一过程区）；`research/progress.py` 的 worker_result 对组合返研请求输出「已要求按反馈重做」结论；e2e 夹具新增「组合返研」代表序列（组合补查→返研结论→目的地第二轮→继续组合）。⑦测试：新建 `test_research_feedback.py`（7 个行为场景：组合真实调用 route 工具并按实际时长调整 planned_end；返研往返与错误候选替换；目录退出＋其他 Worker 保留＋connector packet 保留；上游视图按轮次；进度可见；上限与解析合同；返研轮组合窗口）；`test_worker_supply`/`test_model_research_plan_flow` 的组合替身补 astream_with_tools 分支；`test_revision` 6 个替身同步工具循环形态；`test_tool_policy_contract` 同步新白名单。
- 改动文件：后端 `planning/itinerary/{composition.py,node.py,prompts.py}`、`planning/research/{feedback.py(新),plan.py,dispatch.py,history.py,progress.py}`、`planning/research/{destination,transport,accommodation}/node.py`、`planning/{state.py,execution.py,graph.py,invalidation.py}`、`memory/research_context.py`、`tools/access.py`；测试新增 `tests/planning/itinerary/test_research_feedback.py`，更新 `tests/planning/itinerary/test_revision.py`、`tests/planning/research/{test_worker_supply.py,test_model_research_plan_flow.py}`、`tests/tools/test_tool_policy_contract.py`；前端 `e2e/fixtures/research-progress.tsx`、`e2e/research-progress.spec.ts`。
- 偏离方案及理由：①任务书的根因行号（composition.py:19 等）是 10-31 审计快照，03 串行改造后组合结构已变，本轮按当前代码落点实施；②返研次数上限选每 Worker 1 次（不新增无限自修复流程；资源不足或返研后仍不可用时，组合按提示词直接基于其余成果继续并写明无法安排的部分）；③e2e 证据写入本任务 output 目录的 e2e/ 子目录（research-progress.spec.ts 的旧 EVIDENCE_DIR 属其他任务，未改动）。
- 实际运行的检查与结果：①`.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/planning/itinerary/test_research_feedback.py backend/tests/planning/itinerary/test_connector_route_completion.py backend/tests/planning/research/test_worker_recovery.py -q` → 43 passed。②后端非数据库全量 → 759 passed；`ruff check backend` → 通过。③`npm --prefix frontend run type-check` → 0 错误；全量 vitest → 128 passed。④`JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8080 npx playwright test e2e/research-progress.spec.ts --workers=1 --output=../output/polish/20261101-0035-generation-04-composition-feedback/playwright` → 22 passed（含新用例「组合补查、反馈返研与返研后继续组合在同一工作台可见」）。⑤DeepSeek 勘察工作流另发现并已按结论实现：`agent_assignments` 整体替换语义（返研更新必须携带完整字典）、返研轮 provider 证据尝试须续编、connector packet 不受旧轮次退出判定影响。
- 实屏证据：`output/polish/20261101-0035-generation-04-composition-feedback/e2e/`（process-2000-composition-redo.png 与 composition-redo-progress.json：虚构返研与继续组合的工作台状态；行为正确性由上述真实图调用链测试证明）。
- 遗留问题或需要指挥决定的事：1）组合补查的工具结果只影响草稿本身（时间、顺序、说明），不回写候选目录——模型仍只能引用目录内 candidate_id；让补查产生的新地点进入目录属候选体系扩展，未在本项实施。2）接驳补全（complete_local_connector_routes、_author_connector_routes）仍为骨架定稿后的预设路径，未改为模型自主调用；其产物作为目录内 packet 在返研后的重建中保留。3）真实模型是否主动正确判断返研与补查，留待本批最终真实联调（6.4 第 2 条已注明）。

### 第 2 轮 · 2026-11-01 21:15 · ZCode／GLM-5.3（按 GPT-6.1-sol 验收结论返工）

- 改动摘要：修复验收 7 项发现。F1（超窗回炉）：`connectors.py` 抽出 `_selected_connector_option` 并新增 `overtimed_connector_gaps`；物化阶段发现已选市内路线超过相邻停留点可用窗口时，回炉一次让组合按真实耗时修正排程（`composition_reschedule_rounds` 计数，上限 1，`invalidation` 清零；次数用尽后按真实耗时照常物化，不压缩分钟数）。F2（返研无新成果也退出）：`history.py` 目录重建时按 `research_redo_rounds` 判定——组合已请求返研但返研轮没有产出 packet 时，该 Worker 旧轮次成果整体退出，不再作为「未入选备选」继续供给，其他 Worker 保留。F3（未安排说明保留）：`day_design_contracts.py` 新增 `DayDesign.unresolved`（模型逐条写明确无法安排的事项），`day_design.py` 把它保留进工作台 `important_notes`（「未能安排：…」），不随说明重建丢失；组合提示词同步要求如实写出。F4（失败不重入）：`dispatch.py` 研究窗口关闭跳组合的分支加「组合未 failed」守卫，组合已失败时收敛到预算与交付收口，不再反复重入。F5（返研轮工作台可见）：三个 Worker 节点在返研轮以带轮次的 `output_key` 发事件（显示名「目的地调研（第2轮补充）」），前端 `agentStages.ts` 允许带轮次的研究步骤把过程区焦点拉回研究（继续组合后自动回到路线）；e2e 新增真实 `GenerationJourneyPanel` 链路用例（generation-progress 夹具）。F6（对照成果限版本）：`feedback.py` `latest_worker_packet` 只在当前 run/generation/事实版本内选取，旧规划版本的 `_r2` 不再压过当前轮次。F7（市内路线可读）：组合候选目录与排程能力投影改为全量阅读范围（含交通研究的市内实测路线与 `duration_minutes`），可引用范围仍由 JSON Schema 枚举（skeleton_only）约束；骨架提示词说明参考实测耗时落时间。
- 改动文件：后端 `planning/itinerary/{connectors.py,node.py,prompts.py,day_design.py,day_design_contracts.py,selected_supply.py}`、`planning/research/{history.py,dispatch.py,feedback.py}`、`planning/research/{destination,transport,accommodation}/node.py`、`planning/{state.py,invalidation.py}`；测试 `tests/planning/itinerary/test_research_feedback.py`（新增 4 个行为场景：返研无新成果退出、对照成果限版本、失败组合不重入、超窗回炉与未安排保留并入补查场景）、`tests/planning/itinerary/test_revision.py`（超窗照用→回炉一次语义、物化失败窗口加宽）、`tests/planning/itinerary/test_connector_route_completion.py`（gap 窗口加宽至可容纳测试路线，保持接驳补全语义不变）；前端 `src/features/chat/model/agentStages.ts`（返研轮焦点回退）、`src/features/chat/model/agentStages.test.ts`、`e2e/fixtures/{research-progress,generation-progress}.tsx`、`e2e/research-progress.spec.ts`（新增真实面板返研用例）。
- 偏离方案及理由：①F3 的「finalizer 仍将结果标为完成」部分未在本轮修改——完成状态与完成标准（「完成看行程空缺」）属 05 精简交付的范畴，本轮只做到「模型明确报告的未安排内容保留到用户可见的工作台重要说明」，请在指挥验收时裁决边界。②F5 采用「返研轮事件带轮次显示名＋焦点回退」而非新增 SSE 事件类型——复用现有事件与显示名机制（presentation 已支持轮次后缀），避免 7 层契约改动的成本。③超窗回炉上限 1 次（不新增无限自修复流程）；接驳测试的时间窗口加宽是为保持其原有语义（验证补全机制），超窗行为由 test_revision 的专测覆盖。
- 实际运行的检查与结果：①6.2 命令：`.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/planning/itinerary/test_research_feedback.py backend/tests/planning/itinerary/test_connector_route_completion.py backend/tests/planning/research/test_worker_recovery.py -q` → 46 passed。②后端非数据库全量 → 762 passed；`ruff check backend` → 通过。③`npm --prefix frontend run type-check` → 0 错误；全量 vitest → 129 passed。④e2e `JP_COMPONENT_E2E=1 JOURNEYPILOT_APP_URL=http://127.0.0.1:8080 npx playwright test e2e/research-progress.spec.ts --workers=1 --output=../output/polish/20261101-0035-generation-04-composition-feedback/playwright` → 23 passed（新增「生成工作台面板把返研重做过程留在当前活动区并归并轮次」真实面板用例）。
- 实屏证据：`output/polish/20261101-0035-generation-04-composition-feedback/e2e/`（新增 generation-panel-composition-redo.png：真实工作台面板上返研重做与继续组合；此前 process-2000-composition-redo.png 与 composition-redo-progress.json 保留）。
- 遗留问题或需要指挥决定的事：1）F3 的交付「完成状态」边界留指挥裁决（见偏离①）。2）第 1 轮遗留事项不变（补查结果不回写候选目录；接驳补全仍为预设路径；真实模型判断留待联调）。3）返研轮 journal 重放依赖 assignment 键与 `__pregel_task_id` 变化区分轮次，未在图级测试显式构造崩溃恢复场景（验收 notCovered 同项），如需可补。

## 8 指挥验收（指挥填写）

## 9 真人验收（指挥代录）
