# ADR-0011：内容质量由模型负责

状态：已采纳
影响：`planning/delivery/` 的投影与持久化、`api/schemas/` 的公开交付合同、测试策略

## 决定

服务端只保证结构、合同与资源边界，不判断候选、行程结构或文本内容的"质量"：

- 入参解析与 Pydantic 结构校验：数据可解析、字段类型正确、身份与代际一致。
- 限流、预算、用量记账与时限：约束资源消耗。
- `plan_gate` 用户确认：计划审批、修改、追加要求与取消交互。
- RAG 按需工具调用：知识检索作为工具供模型使用。
- Worker 在自身可用工具范围内按任务调用；运行、取消、租约和预算约束保留。
- 最终交付只接受一份结构完整的 `DeliveryBundle`；报告、地图、PDF 与来源都从它投影。

## 为什么

旅行内容的好坏没有一套能同时通过、又互不矛盾的本地规则。把质量裁决放在服务端，
交付与否就取决于规则层叠是否同时通过，而不是模型能否写出可用计划；每一层规则还需
独立维护，模型改写后仍可能被误杀。服务端能可靠保证的是结构、身份、代际与资源边界。

## 替代方案与为什么没选

- **保留服务端质量门禁与修复循环**：规则互相耦合、维护成本高，且无法解释"为什么被拒"。
- **只保留覆盖度/忠实度评分**：评分没有可执行的修复动作，只会变成另一个不透明门禁。
- **让 Worker 直接写最终行程、跳过候选目录**：丢失跨角色候选与来源一致性，交付前无法统一校验。

## 后果

- 主链路：`scope_clarifier` → `understanding_agent` / `understanding_gate` →
  `requirements_preparer` → `research_plan_generator` → `minimum_delivery_draft_builder` →
  `destination_geo_resolver` → `trip_summary_card_brief` → `planner` → `plan_gate` →
  `weather_context_builder` → `dispatcher` → `destination_researcher` /
  `transport_researcher` / `accommodation_researcher` → `itinerary_planner` →
  `delivery_projector` → `delivery_finalizer`。`intent_amendment_router` 负责计划修改与
  追加要求的路由；Dispatcher 收齐 packet 后构建 `RecommendationCatalog`，模型直接读取
  catalog 组合行程。
- 持久化产物按当前结构读取；结构不匹配时不加载，也不提供兼容读取层。
- 测试以行为为主：断言给定输入的关键输出或状态变化，不维护质量门禁矩阵或快照对照。

## 对应不变量

INV-PLAN-001、INV-SSE-001。
