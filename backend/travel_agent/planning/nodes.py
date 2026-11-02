from __future__ import annotations


NODE_CLARIFIER = "scope_clarifier"


NODE_UNDERSTANDING_AGENT = "understanding_agent"


NODE_UNDERSTANDING_GATE = "understanding_gate"


NODE_REQUIREMENTS_PREPARER = "requirements_preparer"


NODE_RESEARCH_PLAN_GENERATOR = "research_plan_generator"


NODE_INTENT_AMENDMENT_ROUTER = "intent_amendment_router"


NODE_MINIMUM_DELIVERY_DRAFT = "minimum_delivery_draft_builder"


NODE_DESTINATION_GEO_RESOLVER = "destination_geo_resolver"


NODE_WEATHER_CONTEXT_BUILDER = "weather_context_builder"


NODE_SUMMARY_CARD_BRIEF = "trip_summary_card_brief"


NODE_PLANNER = "planner"


NODE_PLAN_GATE = "plan_gate"


NODE_DISPATCHER = "dispatcher"


NODE_DESTINATION = "destination_researcher"


NODE_TRANSPORT = "transport_researcher"


NODE_ACCOMMODATION = "accommodation_researcher"


NODE_ITINERARY = "itinerary_planner"


NODE_DELIVERY_PROJECTOR = "delivery_projector"


NODE_DELIVERY_FINALIZER = "delivery_finalizer"


WORKER_NODES = [
    NODE_DESTINATION,
    NODE_TRANSPORT,
    NODE_ACCOMMODATION,
    NODE_ITINERARY,
]


RESEARCH_WORKER_NODES = frozenset(
    {
        NODE_DESTINATION,
        NODE_TRANSPORT,
        NODE_ACCOMMODATION,
    }
)


CHECKPOINT_GATE_NODES = frozenset({NODE_PLAN_GATE, NODE_UNDERSTANDING_GATE})


# 补充要求可以续跑的节点边界。入口整理（scope_clarifier）、提问暂停点
# （understanding_gate）与路由器自身不是可恢复的边界；图的条件边表与运行时
# 的 divert 守卫都从这里取，避免两边各写一份。
AMENDMENT_CONTINUATION_NODES = frozenset(
    {
        NODE_UNDERSTANDING_AGENT,
        NODE_REQUIREMENTS_PREPARER,
        NODE_RESEARCH_PLAN_GENERATOR,
        NODE_MINIMUM_DELIVERY_DRAFT,
        NODE_DESTINATION_GEO_RESOLVER,
        NODE_WEATHER_CONTEXT_BUILDER,
        NODE_SUMMARY_CARD_BRIEF,
        NODE_PLANNER,
        NODE_PLAN_GATE,
        NODE_DISPATCHER,
        NODE_DESTINATION,
        NODE_TRANSPORT,
        NODE_ACCOMMODATION,
        NODE_ITINERARY,
        NODE_DELIVERY_PROJECTOR,
        NODE_DELIVERY_FINALIZER,
    }
)
