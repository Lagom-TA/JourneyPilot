from travel_agent.planning.state import TravelAgentState


def restore_planning_state(current, **update):
    payload = current.model_dump()
    payload.update(update)
    return TravelAgentState.model_validate(payload)

def visit_placement(start="10:00", end="11:00"):
    return {
        **meal_placement(start=start, end=end),
        "placement_kind": "visit",
        "candidate_id": "candidate_visit",
        "meal_type": None,
    }

def visit_entry(start="10:00", end="11:00"):
    result = visit_placement(start, end)
    result.pop("meal_type")
    return result

def meal_placement(meal_type="breakfast", start="08:00", end="09:00", day="2026-10-10"):
    return {
        "placement_kind": "dining",
        "candidate_id": "candidate_dining",
        "meal_type": meal_type,
        "duration_minutes": 60,
        "planned_start": f"{day}T{start}:00+09:00",
        "planned_end": f"{day}T{end}:00+09:00",
    }

def itinerary_draft(placements=None):
    return {
        "itinerary_id": "itinerary_test",
        "title": "Tokyo",
        "duration_days": 1,
        "days": [
            {
                "day_id": "day_1",
                "day": 1,
                "date": "2026-10-10",
                "destination_id": "destination_tokyo",
                "placements": placements or [meal_placement()],
            }
        ],
    }
