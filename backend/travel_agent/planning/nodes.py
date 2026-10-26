from __future__ import annotations


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


NODE_DESTINATION = "destination_researcher"


NODE_TRANSPORT = "transport_researcher"


NODE_ACCOMMODATION = "accommodation_researcher"


NODE_ITINERARY = "itinerary_planner"


NODE_BUDGET_ESTIMATE = "budget_estimate"


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


CHECKPOINT_GATE_NODES = frozenset({"plan_gate"})
