# ADR-0013：内容质量由模型负责

## 背景

生成的旅游计划不可用。根因是层层叠加的内容质量验证：候选层检查、意图匹配、组合规则、覆盖与忠实度评估、交付质量检查和修复循环互相耦合。行程能否交付取决于各层规则能否同时通过，而不是模型能否写出可用的计划。

## 决定

移除内容质量验证体系。行程内容的质量由模型负责，服务端不再对候选、行程结构或文本内容做质量裁决。

保留以下能力：

- 入参解析与 Pydantic 结构校验：保证数据可解析、字段类型正确、身份与代际一致，不判断内容好坏。
- 限流、预算、用量记账与时限：继续约束资源消耗。
- `plan_gate` 用户确认：计划审批、修改、追加要求与取消交互不变。
- RAG 按需工具调用：知识检索作为工具供模型使用。
- 服务端 `ResearchQueryPlan` 编排：Worker 按服务端生成的 Query ID 执行，调度结构保留。
- mutation 编辑历史：用户编辑与撤销继续记录为编辑台账，不再触发提交前的质量重验。

## 影响

- 主链路为：`scope_clarifier` → `request_contract_normalizer` → `research_brief_builder` → `minimum_delivery_draft_builder` → `destination_geo_resolver` → `weather_context_builder` → `trip_summary_card_brief` → `planner` → `plan_gate` → `dispatcher` → `destination_researcher` / `transport_researcher` / `accommodation_researcher` → `itinerary_planner` → `budget_estimate` → `delivery_projector` → `delivery_finalizer`。另有控制节点 `intent_amendment_router` 处理计划修改与追加要求的路由。Dispatcher 收齐 worker packet 后调用 `assembly.py` 的 `build_candidate_catalog` 构建 `RecommendationCatalog`，模型直接读取 catalog 组合行程。
- 契约版本升级：`ResearchPacket` v6、`RecommendationCatalog` v7、`TripWorkspaceV2` v11、`DeliveryBundle` v10。旧持久化产物不可加载，不提供兼容读取层。
- 测试策略转为精准行为测试：每个测试回答「给定输入，关键输出是什么」，不再维护门控断言、哈希或快照对照、修复循环矩阵。
