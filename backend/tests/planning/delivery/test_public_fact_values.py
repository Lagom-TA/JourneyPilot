from datetime import datetime, timezone

import pytest

from tests.fixtures.itinerary import itinerary_draft, meal_placement, visit_entry
from tests.fixtures.research_catalog import make_visit_packet
from travel_agent.planning.delivery.assembly import assemble_delivery_bundle
from travel_agent.planning.delivery.fact_projection import build_fact_snapshot
from travel_agent.planning.delivery.projection_builder import build_delivery_projections
from travel_agent.planning.delivery.projection_errors import DeliveryProjectionError
from travel_agent.planning.delivery.public.bundle import public_delivery_bundle
from travel_agent.planning.itinerary.draft import ItineraryCompositionDraft
from travel_agent.planning.itinerary.day_design import apply_day_design
from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.planning.requirements.inputs import UserInputAnchor
from travel_agent.planning.requirements.place_names import CONTROLLED_DESTINATION_ANCHOR_PREFIX
from travel_agent.planning.research.candidates import CandidateBase, DiningCandidate, LodgingCandidate, VisitCandidate
from travel_agent.planning.research.catalog import RecommendationCatalog
from travel_agent.planning.research.evidence import FactAssertion, FactSourceLink, FieldProvenance
from travel_agent.planning.research.packets import ResearchPacket
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.weather.models import WeatherContextSnapshot


NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _packet(kind, candidate_id, values, assertions):
    base = make_visit_packet(candidate_id, f"名称 {candidate_id}")
    common = base.candidates[0].model_dump(include=set(CandidateBase.model_fields))
    identity = {
        "place_id": f"place_{candidate_id}",
        "provider_place_type": "tourism;attraction",
        "provider_country_code": "JP",
        "address": "Tokyo",
    }
    entity_type, candidate_class, domain, name_field, worker = {
        "visit": (
            EntityType.VISIT_STOP, VisitCandidate,
            {"name": f"名称 {candidate_id}", "visit_type": "culture", "recommended_duration_minutes": 60},
            "name", "destination_researcher",
        ),
        "dining": (
            EntityType.DINING_STOP, DiningCandidate,
            {"branch_name": f"名称 {candidate_id}", "meal_types": ["breakfast"], "availability_status": "needs_confirmation"},
            "branch_name", "destination_researcher",
        ),
        "lodging": (
            EntityType.LODGING_STAY, LodgingCandidate,
            {"property_name": f"名称 {candidate_id}", "check_in_date": "2026-10-10", "check_out_date": "2026-10-11", "nights": 1, "availability_status": "needs_confirmation"},
            "property_name", "accommodation_researcher",
        ),
    }[kind]
    candidate = candidate_class(**common, **identity, **domain, **values)
    ref = EntityRef(entity_type=entity_type, entity_id=candidate_id)
    assertions = [(name_field, domain[name_field], "verified", "supports"), *assertions]
    facts = [
        FactAssertion(
            fact_assertion_id=f"{candidate_id}-{index}",
            entity_ref=ref,
            field_path=field,
            asserted_value=value,
            criticality="auxiliary" if index else "decision_critical",
            status=status,
            source_links=[FactSourceLink(
                source_record_id=base.source_records[0].source_record_id,
                relation=relation,
                source_locator=f"fixture.{field}",
            )] if relation else [],
        )
        for index, (field, value, status, relation) in enumerate(assertions)
    ]
    return ResearchPacket.model_validate({
        **base.model_dump(mode="python"),
        "worker_kind": worker,
        "candidates": [candidate],
        "fact_assertions": facts,
        "field_provenance": [FieldProvenance(
            origin="external_fact", entity_ref=ref, field_path=field,
            reference_ids=[fact.fact_assertion_id for fact in facts if fact.field_path == field],
        ) for field in dict.fromkeys(fact.field_path for fact in facts)],
    })


def _delivery(*packets, placements=None, lodging_ids=()):
    catalog = RecommendationCatalog(
        generation_id="generation_test", fact_data_revision=1, weather_data_revision=0,
        research_packets=list(packets),
    )
    draft_payload = itinerary_draft(placements or [visit_entry()])
    draft_payload["lodging_candidate_ids"] = list(lodging_ids)
    if lodging_ids:
        next_day_visit = visit_entry()
        next_day_visit["planned_start"] = "2026-10-11T10:00:00+09:00"
        next_day_visit["planned_end"] = "2026-10-11T11:00:00+09:00"
        draft_payload["duration_days"] = 2
        draft_payload["days"].append({
            "day_id": "day_2", "day": 2, "date": "2026-10-11",
            "destination_id": "destination_tokyo", "placements": [next_day_visit],
        })
    workspace = materialize_trip_workspace(
        run_id="run_test", workspace_revision=0,
        composition=ItineraryCompositionDraft.model_validate(draft_payload),
        catalog=catalog, requirements="", composition_mutations=[],
        user_input_anchors=[UserInputAnchor(
            anchor_id="destination", field_path=f"{CONTROLLED_DESTINATION_ANCHOR_PREFIX}destination_tokyo",
            value={"place_id": "destination_tokyo", "name": "东京"}, input_kind="controlled_identity",
        )],
    )
    facts = build_fact_snapshot(workspace)
    trip_date = workspace.itinerary.day_plans[0].date
    weather = WeatherContextSnapshot(
        weather_data_revision=0, trip_start_date=trip_date,
        trip_end_date=workspace.itinerary.day_plans[-1].date, days=[], retrieved_at=NOW,
    )
    report, map_projection, source_index = build_delivery_projections(
        workspace, facts, weather, generated_at=NOW,
    )
    bundle = assemble_delivery_bundle(TravelAgentState(
        run_id="run_test", trip_workspace=workspace, fact_store_snapshot=facts,
        weather_context=weather, report_projection=report, map_projection=map_projection,
        source_index_projection=source_index,
    ))
    return bundle, public_delivery_bundle(bundle)


def test_unplanned_day_and_missing_items_survive_delivery_projections():
    packet = _packet("visit", "candidate_visit", {}, [])
    catalog = RecommendationCatalog(
        generation_id="generation_test", fact_data_revision=1, weather_data_revision=0,
        research_packets=[packet],
    )
    payload = itinerary_draft([visit_entry()])
    payload["duration_days"] = 2
    payload["days"].append({
        "day_id": "day_2", "day": 2, "date": "2026-10-11",
        "destination_id": "destination_tokyo", "placements": [],
        "day_design": {"unresolved": ["第二天尚未安排"]},
    })
    composition = ItineraryCompositionDraft.model_validate(payload)
    workspace = materialize_trip_workspace(
        run_id="run_test", workspace_revision=0, composition=composition,
        catalog=catalog, requirements="", composition_mutations=[],
        user_input_anchors=[UserInputAnchor(
            anchor_id="destination", field_path=f"{CONTROLLED_DESTINATION_ANCHOR_PREFIX}destination_tokyo",
            value={"place_id": "destination_tokyo", "name": "东京"}, input_kind="controlled_identity",
        )],
    )
    workspace = apply_day_design(workspace, composition)
    facts = build_fact_snapshot(workspace)
    weather = WeatherContextSnapshot(
        weather_data_revision=0, trip_start_date=workspace.itinerary.day_plans[0].date,
        trip_end_date=workspace.itinerary.day_plans[-1].date, days=[], retrieved_at=NOW,
    )
    report, map_projection, source_index = build_delivery_projections(workspace, facts, weather, generated_at=NOW)
    bundle = assemble_delivery_bundle(TravelAgentState(
        run_id="run_test", trip_workspace=workspace, fact_store_snapshot=facts,
        weather_context=weather, report_projection=report, map_projection=map_projection,
        source_index_projection=source_index,
    ))
    public = public_delivery_bundle(bundle)

    assert public["workspace"]["itinerary"]["day_plans"][1]["timeline"] == []
    assert public["report_projection"]["document"]["days"][1]["blocks"] == []
    assert public["workspace"]["itinerary"]["unresolved"] == ["第二天尚未安排"]
    assert public["report_projection"]["document"]["unresolved"] == ["第二天尚未安排"]


def test_missing_optional_facts_are_not_published_or_counted(caplog):
    packet = _packet("visit", "candidate_visit", {
        "opening_window": "09:00–17:00", "estimated_cost_cny": 88,
        "reservation_required": False,
    }, [
        ("opening_window", None, "missing", None),
        ("estimated_cost_cny", None, "missing", None),
        ("reservation_required", None, "missing", None),
    ])
    bundle, public = _delivery(packet)

    assert bundle.workspace.itinerary.visit_stops[0].opening_window == "09:00–17:00"
    assert bundle.workspace.itinerary.visit_stops[0].estimated_cost_cny == 88
    assert public["report_projection"]["status"] == "ready"
    stop = public["workspace"]["itinerary"]["visit_stops"][0]
    assert stop["opening_window"] is None
    assert stop["estimated_cost_cny"] is None
    assert stop["reservation_required"] is None
    report = public["report_projection"]["document"]
    details = report["days"][0]["blocks"][0]["details"]
    assert details["opening_window"] is None
    assert details["estimated_cost_cny"] is None
    assert details["reservation_required"] is None
    assert details["price_label"] is None
    assert not any(line.startswith(("开放：", "预约：")) for line in details["facts"])
    assert report["cost_summary"]["known_subtotal_cny"] is None
    assert public["workspace"]["itinerary"]["cost_summary"] == report["cost_summary"]
    assert report["unresolved"] == []
    assert "营业时间" not in report["selections"][0]["options"][0]["comparison_facts"]
    assert not [record for record in caplog.records if record.levelname in {"WARNING", "ERROR"}]


def test_optional_values_without_any_fact_are_not_published_or_counted():
    packet = _packet("visit", "candidate_visit", {
        "opening_window": "09:00–17:00", "estimated_cost_cny": 88,
    }, [])
    _, public = _delivery(packet)

    stop = public["workspace"]["itinerary"]["visit_stops"][0]
    report = public["report_projection"]["document"]
    assert stop["opening_window"] is None
    assert stop["estimated_cost_cny"] is None
    assert report["days"][0]["blocks"][0]["details"]["opening_window"] is None
    assert report["cost_summary"]["known_subtotal_cny"] is None


def test_independently_sourced_values_survive_missing_facts_including_zero_and_false():
    packet = _packet("visit", "candidate_visit", {
        "opening_window": "09:00–17:00", "estimated_cost_cny": 0,
        "reservation_required": False,
    }, [
        ("opening_window", None, "missing", None),
        ("opening_window", "09:00–17:00", "verified", "supports"),
        ("estimated_cost_cny", None, "missing", None),
        ("estimated_cost_cny", 0, "verified", "supports"),
        ("reservation_required", False, "verified", "supports"),
    ])
    _, public = _delivery(packet)

    stop = public["workspace"]["itinerary"]["visit_stops"][0]
    assert (stop["opening_window"], stop["estimated_cost_cny"], stop["reservation_required"]) == ("09:00–17:00", 0, False)
    report = public["report_projection"]["document"]
    details = report["days"][0]["blocks"][0]["details"]
    assert "开放：09:00–17:00" in details["facts"]
    assert "预约：无需预约" in details["facts"]
    assert details["price_label"] is not None
    assert report["cost_summary"]["known_subtotal_cny"] is None
    assert "营业时间" in report["selections"][0]["options"][0]["comparison_facts"]


def test_another_candidate_or_different_value_cannot_support_a_field():
    selected = _packet("visit", "candidate_visit", {"opening_window": "09:00–17:00"}, [
        ("opening_window", None, "missing", None),
        ("opening_window", "08:00–16:00", "verified", "supports"),
    ])
    alternative = _packet("visit", "candidate_alternative", {"opening_window": "09:00–17:00"}, [
        ("opening_window", "09:00–17:00", "verified", "supports"),
    ])
    _, public = _delivery(selected, alternative)

    assert public["workspace"]["itinerary"]["visit_stops"][0]["opening_window"] is None
    options = public["report_projection"]["document"]["selections"][0]["options"]
    assert "营业时间" not in options[0]["comparison_facts"]
    assert "营业时间" in options[1]["comparison_facts"]
    assert any(
        citation["supported_values"][0]["value"] == "09:00–17:00"
        and citation["entity_ref"]["entity_id"] == "candidate_alternative"
        for citation in public["source_index"]["content"]["citations"]
    )


def test_concrete_unsourced_assertions_still_fail():
    packet = _packet("visit", "candidate_visit", {"opening_window": "09:00–17:00"}, [
        ("opening_window", "09:00–17:00", "verified", None),
    ])
    with pytest.raises(DeliveryProjectionError, match="no public source"):
        _delivery(packet)


def test_dining_and_lodging_prices_are_checked_independently():
    visit = _packet("visit", "candidate_visit", {}, [])
    dining = _packet("dining", "candidate_dining", {
        "opening_window": "08:00–20:00", "average_spend_cny": 66,
        "reservation_required": True,
    }, [
        ("opening_window", None, "missing", None),
        ("average_spend_cny", 66, "verified", "supports"),
        ("reservation_required", None, "missing", None),
    ])
    lodging = _packet("lodging", "candidate_lodging", {
        "nightly_price_cny": 300, "total_price_cny": 300,
    }, [
        ("nightly_price_cny", 300, "verified", "supports"),
        ("total_price_cny", None, "missing", None),
    ])
    _, public = _delivery(
        visit, dining, lodging,
        placements=[meal_placement(), visit_entry()], lodging_ids=["candidate_lodging"],
    )
    itinerary = public["workspace"]["itinerary"]
    meal = itinerary["dining_stops"][0]
    stay = itinerary["lodging_stays"][0]
    assert (meal["average_spend_cny"], meal["estimated_cost_cny"]) == (66, 66)
    assert meal["opening_window"] is None and meal["reservation_required"] is None
    assert stay["nightly_price_cny"] == 300 and stay["total_price_cny"] is None
    report = public["report_projection"]["document"]
    assert itinerary["cost_summary"] == report["cost_summary"]
    assert report["cost_summary"]["known_subtotal_cny"] is None
    assert report["cost_summary"]["estimated_total_cny"] is None
    blocks = {block["entity_kind"]: block for block in report["days"][0]["blocks"]}
    assert blocks["dining"]["details"]["opening_window"] is None
    assert blocks["lodging"]["details"]["nightly_price_cny"] == 300
    assert blocks["lodging"]["details"]["total_price_cny"] is None
