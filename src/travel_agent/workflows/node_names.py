"""节点名称常量表 —— 零仓内依赖的叶子模块。

节点名的唯一真源。`travel_planning` 是图定义文件、全仓最上游的消费方，
下游模块（门、run_control、api 路由）反向 import 它会成环，所以这张表
独立成叶子：任何模块都可以安全导入它，它不导入任何 travel_agent 模块。

纯数据表：不承载任何逻辑、校验或派生函数。
"""

NODE_CLARIFIER = "scope_clarifier"
NODE_REQUEST_CONTRACT_NORMALIZER = "request_contract_normalizer"
NODE_RESEARCH_BRIEF_BUILDER = "research_brief_builder"
NODE_INTENT_AMENDMENT_ROUTER = "intent_amendment_router"
NODE_MINIMUM_DELIVERY_DRAFT = "minimum_delivery_draft_builder"
NODE_DESTINATION_GEO_RESOLVER = "destination_geo_resolver"
NODE_WEATHER_CONTEXT_BUILDER = "weather_context_builder"
NODE_SUMMARY_CARD_BRIEF = "trip_summary_card_brief"
NODE_PLANNER = "planner"
NODE_PLAN_GATE = "plan_gate"
NODE_DISPATCHER = "dispatcher"
NODE_CANDIDATE_GATE = "candidate_gate"
NODE_DESTINATION = "destination_researcher"
NODE_TRANSPORT = "transport_researcher"
NODE_ACCOMMODATION = "accommodation_researcher"
NODE_ITINERARY = "itinerary_planner"
NODE_ARTIFACT_GATE = "artifact_gate"
NODE_INTENT_FIDELITY_GATE = "intent_fidelity_gate"
NODE_DELIVERY_QUALITY_GATE = "delivery_quality_gate"
NODE_BUDGET_ESTIMATE = "budget_estimate"
NODE_DELIVERY_PROJECTOR = "delivery_projector"
NODE_DELIVERY_FINALIZER = "delivery_finalizer"

# Worker 节点列表（dispatcher fan-out 的目标节点），顺序有语义，不许改。
WORKER_NODES = [
    NODE_DESTINATION,
    NODE_TRANSPORT,
    NODE_ACCOMMODATION,
    NODE_ITINERARY,
]

# 三个 research worker（与 WORKER_NODES 中的 itinerary_planner 相区分）。
RESEARCH_WORKER_NODES = frozenset({
    NODE_DESTINATION,
    NODE_TRANSPORT,
    NODE_ACCOMMODATION,
})

# 计划批准门：唯一支持断点续跑的门。
CHECKPOINT_GATE_NODES = frozenset({"plan_gate"})
