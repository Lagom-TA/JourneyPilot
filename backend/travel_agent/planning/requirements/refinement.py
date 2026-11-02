"""从当前交付创建新的规划执行。"""

from __future__ import annotations

from travel_agent.planning.delivery.minimum_draft import (
    build_minimum_delivery_draft,
    seal_minimum_delivery_draft,
)
from travel_agent.planning.requirements.natural_language import next_generation
from travel_agent.planning.research.plan import build_worker_assignment
from travel_agent.planning.state import TravelAgentState


async def seed_refinement_state(state: TravelAgentState, bundle, action: str) -> TravelAgentState:
    requirements = "\n".join(
        part for part in (bundle.workspace.requirements, f"后续补充：{state.user_query}") if part
    )
    state = state.model_copy(update={"current_requirements": requirements})
    if action != "revise":
        return state

    generation = next_generation(state, requirements)
    old_catalog = bundle.workspace.recommendation_catalog
    packets = [
        packet.model_copy(update={
            "run_id": state.run_id,
            "generation_id": generation.generation_id,
            "fact_data_revision": 0,
        })
        for packet in old_catalog.research_packets
    ]
    catalog = old_catalog.model_copy(update={
        "generation_id": generation.generation_id,
        "fact_data_revision": 0,
        "weather_data_revision": 0,
        "research_packets": packets,
    })
    latest_packets = {}
    for packet in packets:
        latest_packets[packet.worker_kind] = packet
    packet_source_ids = {source.source_record_id for packet in packets for source in packet.source_records}
    packet_fact_ids = {fact.fact_assertion_id for packet in packets for fact in packet.fact_assertions}
    packet_provenance = {
        (item.entity_ref.entity_id, item.field_path, item.origin)
        for packet in packets for item in packet.field_provenance
    }
    old_workspace = bundle.workspace.model_copy(update={
        "run_id": state.run_id,
        "generation_id": generation.generation_id,
        "workspace_revision": 0,
        "recommendation_catalog": catalog,
        "requirements": requirements,
        "composition_mutations": [],
    })
    weather = bundle.weather_snapshot.model_copy(update={
        "weather_data_revision": 0,
        "adjustment_proposals": [],
    })
    state = state.model_copy(update={
        "planning_generation": generation,
        "fact_data_revision": 0,
        "recommendation_catalog": catalog,
        "research_packets": {f"{name}@{generation.generation_id}": packet for name, packet in latest_packets.items()},
        "weather_context": weather,
        "weather_impacts": {impact.weather_impact_id: impact for impact in weather.impacts},
        "weather_source_records": [item for item in bundle.fact_snapshot.source_records if item.source_record_id not in packet_source_ids],
        "weather_fact_assertions": [item for item in bundle.fact_snapshot.fact_assertions if item.fact_assertion_id not in packet_fact_ids],
        "weather_field_provenance": [item for item in bundle.fact_snapshot.field_provenance if (item.entity_ref.entity_id, item.field_path, item.origin) not in packet_provenance],
        "trip_workspace": old_workspace,
    })
    draft = build_minimum_delivery_draft(state)
    state = state.model_copy(update={"minimum_delivery_draft": draft})
    state = state.model_copy(update=seal_minimum_delivery_draft(state))
    tasks = {
        "destination_researcher": "根据组合反馈补充目的地资料。",
        "transport_researcher": "根据组合反馈补充交通资料。",
        "accommodation_researcher": "根据组合反馈补充住宿资料。",
    }
    assignments = {name: build_worker_assignment(state, name, objective) for name, objective in tasks.items()}
    assignments["itinerary_planner"] = {
        "objective": "根据用户的新要求调整现有行程，优先沿用已有候选和不受影响的安排。"
    }
    return state.model_copy(update={
        "agent_assignments": assignments,
        "execution_plan": [["itinerary_planner"]],
        "agent_status": {},
    })
