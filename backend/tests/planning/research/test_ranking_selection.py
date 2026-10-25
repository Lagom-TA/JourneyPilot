
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import travel_agent.planning.research.destination.discovery as planning_research_destination_discovery
from tests.fixtures.research_catalog import (
    make_catalog,
    make_intent_spec,
    make_local_transport_packet,
    make_research_brief,
    make_research_intent,
    make_visit_packet,
)
from travel_agent.planning.delivery.report_projection import (
    _reportable_selection_options,
)
from travel_agent.planning.itinerary.checks import validate_placement_skeleton
from travel_agent.planning.itinerary.connectors import LocalConnectorGap
from travel_agent.planning.itinerary.draft import (
    DayComposition,
    ItineraryCompositionDraft,
    ItineraryCompositionError,
    VisitPlacement,
)
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.itinerary.options import SelectionOption, SelectionSlot
from travel_agent.planning.itinerary.selected_supply import (
    catalog_for_candidate_selection,
    catalog_for_workspace_materialization,
    selected_candidate_capabilities,
)
from travel_agent.planning.itinerary.selection import _transport_alternatives
from travel_agent.planning.outcomes import CandidateResearchGap
from travel_agent.planning.references import EntityLineage, EntityRef, EntityType
from travel_agent.planning.requirements.candidate_evaluation import (
    evaluate_candidate_intents,
)
from travel_agent.planning.requirements.candidate_match_contracts import (
    CandidateIntentMatch,
    IntentMatchStatus,
)
from travel_agent.planning.requirements.composition_compiler import (
    compile_composition_rules,
)
from travel_agent.planning.requirements.intent_contracts import (
    CountIntentValue,
    IntentItem,
    IntentKind,
    IntentStrength,
    IntentTarget,
    VerificationMode,
)
from travel_agent.planning.research.candidates import (
    CandidateAdmissionResult,
    TransportCandidate,
)
from travel_agent.planning.research.deadlines import (
    _closeout_blocks_targeted_round,
    _research_closeout_can_skip_connector_pass,
)
from travel_agent.planning.research.discovery_contracts import CandidateDiscoveryOrigin
from travel_agent.planning.research.domains import ResearchDomain
from travel_agent.planning.research.evidence import (
    FieldProvenance,
)
from travel_agent.planning.research.fallback_policy import FallbackQueryPolicy
from travel_agent.planning.research.history import _apply_candidate_caps
from travel_agent.planning.research.output.choices import (
    _default_provider_place_selections,
    _provider_place_selections_or_default,
    _provider_route_selection_limit,
    _provider_route_selections_or_default,
)
from travel_agent.planning.research.output.lineage import (
    _bind_candidate_discovery_lineage,
)
from travel_agent.planning.research.output.schemas import (
    _provider_selection_response_schema,
)
from travel_agent.planning.research.query_contracts import ResearchQueryKind
from travel_agent.planning.research.query_planner import (
    append_structural_connector_query,
    append_targeted_repair_query,
    build_research_query_plan,
)
from travel_agent.planning.research.ranking import rank_candidates
from travel_agent.planning.research.ranking_contracts import GENERIC_FALLBACK_PENALTY
from travel_agent.planning.research.selection_contracts import (
    CandidateSelectionRole,
    SelectionPolicy,
)
from travel_agent.planning.research.selection_policy import (
    build_candidate_selection_plan,
)
from travel_agent.planning.state import TravelAgentState
from travel_agent.planning.transport import (
    TransportEndpoint,
    TransportMode,
    TransportSegment,
)
from travel_agent.planning.weather.models import WeatherSensitivity
from travel_agent.runtime.context import current_node, current_run_id


def _single_visit_skeleton(
    candidate_id: str,
    *,
    planned_start: datetime,
    planned_end: datetime,
) -> ItineraryCompositionDraft:
    return ItineraryCompositionDraft(
        itinerary_id="itinerary_opening_window",
        title="Opening window fixture",
        duration_days=1,
        days=[
            DayComposition(
                day_id="day_1",
                day=1,
                date=planned_start.date(),
                destination_id="destination_tokyo",
                placements=[
                    VisitPlacement(
                        candidate_id=candidate_id,
                        planned_start=planned_start,
                        planned_end=planned_end,
                        duration_minutes=int(
                            (planned_end - planned_start).total_seconds() // 60
                        ),
                    )
                ],
            )
        ],
    )


def _transport_candidate(
    candidate_id: str,
    *,
    scope_id: str,
    origin: str,
    destination: str,
) -> TransportCandidate:
    from_endpoint = TransportEndpoint(name=origin, station_code=origin)
    to_endpoint = TransportEndpoint(name=destination, station_code=destination)
    segment = TransportSegment(
        segment_id=f"segment_{candidate_id}",
        mode=TransportMode.HIGH_SPEED_RAIL,
        from_endpoint=from_endpoint,
        to_endpoint=to_endpoint,
        duration_minutes=60,
    )
    return TransportCandidate(
        candidate_id=candidate_id,
        research_packet_id=f"packet_{candidate_id}",
        destination_id="destination_hangzhou",
        fact_assertion_ids=[f"fact_{candidate_id}"],
        source_record_ids=[f"source_{candidate_id}"],
        field_paths=["segments"],
        weather_sensitivity=WeatherSensitivity(
            exposure="indoor",
            rain_sensitivity="low",
            heat_sensitivity="low",
            cold_sensitivity="low",
            wind_sensitivity="low",
            requires_clear_visibility=False,
        ),
        selection_reasons=["exact route", "current provider result"],
        tradeoff="fixture",
        freshness_status="current",
        route_id=f"route_{candidate_id}",
        transport_class="long_distance",
        provider_evidence_scope_id=scope_id,
        selected_mode=TransportMode.HIGH_SPEED_RAIL,
        from_endpoint=from_endpoint,
        to_endpoint=to_endpoint,
        duration_minutes=60,
        segments=[segment],
        booking_status="recommended",
    )




def _selection_option(
    slot_id: str, candidate_id: str, rank: int, *, target_id: str
) -> SelectionOption:
    return SelectionOption(
        option_id=f"option_{slot_id}_{candidate_id}",
        selection_slot_id=slot_id,
        candidate_id=candidate_id,
        candidate_entity_ref=EntityRef(
            entity_type=EntityType.VISIT_STOP, entity_id=target_id
        ),
        rank=rank,
        selection_reasons=["verified identity", "comparison fixture"],
        tradeoff="fixture",
        comparison_facts=["name"],
        availability_status="confirmed",
        fact_assertion_ids=[f"fact_{candidate_id}"],
        source_record_ids=[f"source_{candidate_id}"],
    )


def test_structural_connector_query_is_server_owned_and_idempotent():
    spec = make_intent_spec(make_research_intent("intent_architecture", "architecture"))
    plan = build_research_query_plan(intent_spec=spec, brief=make_research_brief(spec))

    updated, query = append_structural_connector_query(
        plan,
        destination_id="destination_tokyo",
        destination_name="Tokyo",
        route_pairs=[("place_station", "place_garden"), ("place_garden", "place_cafe")],
    )
    replayed, replayed_query = append_structural_connector_query(
        updated,
        destination_id="destination_tokyo",
        destination_name="Tokyo",
        route_pairs=[("place_garden", "place_cafe"), ("place_station", "place_garden")],
    )

    assert query.domain is ResearchDomain.LOCAL_TRANSPORT
    assert query.query_kind is ResearchQueryKind.STRUCTURAL
    assert query.provider_route == "route_provider"
    assert query.query_id in updated.query_index()
    assert updated.content_hash != plan.content_hash
    assert replayed == updated
    assert replayed_query == query


def test_long_distance_alternatives_must_share_the_exact_route_scope():
    outbound_scope = "a" * 64
    return_scope = "b" * 64
    selected = _transport_candidate(
        "outbound_primary",
        scope_id=outbound_scope,
        origin="SHH",
        destination="HZH",
    )
    same_direction = _transport_candidate(
        "outbound_alternative",
        scope_id=outbound_scope,
        origin="AOH",
        destination="HZH",
    )
    reverse = _transport_candidate(
        "return_train",
        scope_id=return_scope,
        origin="HZH",
        destination="SHH",
    )
    leg = TransportLeg(
        transport_leg_id="leg_outbound",
        transport_class="long_distance",
        selected_mode=selected.selected_mode,
        from_endpoint=selected.from_endpoint,
        to_endpoint=selected.to_endpoint,
        duration_minutes=selected.duration_minutes,
        transfer_count=0,
        segments=selected.segments,
        booking_status=selected.booking_status,
        route_status="ready",
        lineage=EntityLineage(
            research_packet_id=selected.research_packet_id,
            candidate_id=selected.candidate_id,
            fact_assertion_ids=selected.fact_assertion_ids,
            source_record_ids=selected.source_record_ids,
        ),
    )

    alternatives = _transport_alternatives(
        leg,
        {item.candidate_id: item for item in (selected, same_direction, reverse)},
    )

    assert {item.candidate_id for item in alternatives} == {
        "outbound_primary",
        "outbound_alternative",
    }


def test_report_alternatives_are_unique_and_never_already_selected():
    slot_one_options = [
        _selection_option("slot_one", "selected_one", 1, target_id="target_one"),
        _selection_option("slot_one", "shared_alternative", 2, target_id="target_one"),
    ]
    slot_two_options = [
        _selection_option("slot_two", "selected_two", 1, target_id="target_two"),
        _selection_option("slot_two", "shared_alternative", 2, target_id="target_two"),
        _selection_option("slot_two", "selected_one", 3, target_id="target_two"),
    ]
    slots = [
        SelectionSlot(
            selection_slot_id="slot_one",
            slot_type="visit",
            target_entity_id="target_one",
            context={},
            options=slot_one_options,
            recommended_option_id=slot_one_options[0].option_id,
            selected_option_id=slot_one_options[0].option_id,
            status="ready",
        ),
        SelectionSlot(
            selection_slot_id="slot_two",
            slot_type="visit",
            target_entity_id="target_two",
            context={},
            options=slot_two_options,
            recommended_option_id=slot_two_options[0].option_id,
            selected_option_id=slot_two_options[0].option_id,
            status="ready",
        ),
    ]

    reportable = _reportable_selection_options(slots)

    assert [[option.candidate_id for option in row] for row in reportable] == [
        ["selected_one", "shared_alternative"],
        ["selected_two"],
    ]


def test_visit_must_fit_inside_published_opening_window():
    packet = make_visit_packet(
        "candidate_garden",
        "郭庄",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_garden",
        intent_id="intent_garden",
        opening_window="08:00-17:00",
    )
    catalog = make_catalog(packet)
    local_tz = ZoneInfo("Asia/Tokyo")

    with pytest.raises(ItineraryCompositionError, match="outside the published"):
        validate_placement_skeleton(
            _single_visit_skeleton(
                "candidate_garden",
                planned_start=datetime(2026, 8, 29, 7, 30, tzinfo=local_tz),
                planned_end=datetime(2026, 8, 29, 9, 0, tzinfo=local_tz),
            ),
            catalog,
        )

    validate_placement_skeleton(
        _single_visit_skeleton(
            "candidate_garden",
            planned_start=datetime(2026, 8, 29, 8, 0, tzinfo=local_tz),
            planned_end=datetime(2026, 8, 29, 9, 30, tzinfo=local_tz),
        ),
        catalog,
    )


def test_visit_rejects_published_weekday_closure():
    packet = make_visit_packet(
        "candidate_museum",
        "博物馆",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_museum",
        intent_id="intent_museum",
        opening_window="09:00-17:00（周一闭馆）",
    )
    catalog = make_catalog(packet)
    local_tz = ZoneInfo("Asia/Tokyo")

    with pytest.raises(ItineraryCompositionError, match="published closed day"):
        validate_placement_skeleton(
            _single_visit_skeleton(
                "candidate_museum",
                planned_start=datetime(2026, 8, 24, 9, 0, tzinfo=local_tz),
                planned_end=datetime(2026, 8, 24, 10, 30, tzinfo=local_tz),
            ),
            catalog,
        )


def test_provider_duration_conflict_is_reported_without_changing_the_draft(monkeypatch):

    import travel_agent.planning.itinerary.checks as checks_module
    import travel_agent.planning.itinerary.connectors as connectors_module

    local_tz = ZoneInfo("Asia/Shanghai")
    garden = make_visit_packet(
        "candidate_garden",
        "郭庄",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_garden",
        intent_id="intent_garden",
        opening_window="08:00-17:00",
    ).candidates[0]
    museum = make_visit_packet(
        "candidate_museum",
        "城市规划馆",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_museum",
        intent_id="intent_museum",
        opening_window="09:00-16:30",
    ).candidates[0]
    garden = garden.model_copy(update={"place_id": "place_garden"})
    museum = museum.model_copy(update={"place_id": "place_museum"})
    from_endpoint = TransportEndpoint(name="郭庄", place_id="place_garden")
    to_endpoint = TransportEndpoint(name="城市规划馆", place_id="place_museum")
    segment = TransportSegment(
        segment_id="segment_local_bus",
        mode=TransportMode.BUS,
        from_endpoint=from_endpoint,
        to_endpoint=to_endpoint,
        duration_minutes=66,
    )
    route = TransportCandidate(
        candidate_id="candidate_local_bus",
        research_packet_id="packet_local_bus",
        destination_id="destination_tokyo",
        fact_assertion_ids=["fact_local_bus"],
        source_record_ids=["source_local_bus"],
        field_paths=["segments"],
        weather_sensitivity=WeatherSensitivity(
            exposure="mixed",
            rain_sensitivity="low",
            heat_sensitivity="low",
            cold_sensitivity="low",
            wind_sensitivity="low",
            requires_clear_visibility=False,
        ),
        selection_reasons=["provider duration", "exact endpoints"],
        tradeoff="fixture",
        freshness_status="current",
        route_id="route_local_bus",
        transport_class="public_transit",
        selected_mode=TransportMode.BUS,
        from_endpoint=from_endpoint,
        to_endpoint=to_endpoint,
        duration_minutes=66,
        segments=[segment],
        booking_status="not_required",
    )
    passed = {
        garden.candidate_id: garden,
        museum.candidate_id: museum,
        route.candidate_id: route,
    }
    monkeypatch.setattr(
        connectors_module, "_passed_candidates", lambda _catalog: passed
    )
    monkeypatch.setattr(checks_module, "_passed_candidates", lambda _catalog: passed)
    skeleton = ItineraryCompositionDraft(
        itinerary_id="itinerary_provider_alignment",
        title="Provider alignment fixture",
        duration_days=1,
        days=[
            DayComposition(
                day_id="day_1",
                day=1,
                date=datetime(2026, 8, 28).date(),
                destination_id="destination_tokyo",
                placements=[
                    VisitPlacement(
                        candidate_id=garden.candidate_id,
                        planned_start=datetime(2026, 8, 28, 13, 30, tzinfo=local_tz),
                        planned_end=datetime(2026, 8, 28, 15, 0, tzinfo=local_tz),
                        duration_minutes=90,
                    ),
                    VisitPlacement(
                        candidate_id=museum.candidate_id,
                        planned_start=datetime(2026, 8, 28, 15, 30, tzinfo=local_tz),
                        planned_end=datetime(2026, 8, 28, 16, 30, tzinfo=local_tz),
                        duration_minutes=60,
                    ),
                ],
            )
        ],
    )
    gap = LocalConnectorGap(
        gap_id="gap_garden_museum",
        day_id="day_1",
        day_date=datetime(2026, 8, 28).date(),
        destination_id="destination_tokyo",
        from_entry_key=f"candidate:{garden.candidate_id}",
        from_place_id="place_garden",
        to_entry_key=f"candidate:{museum.candidate_id}",
        to_place_id="place_museum",
        departure_time=datetime(2026, 8, 28, 15, 0, tzinfo=local_tz),
        latest_arrival_time=datetime(2026, 8, 28, 15, 30, tzinfo=local_tz),
        allowed_transport_classes=["public_transit"],
        preferred_transport_class="public_transit",
        weather_data_revision=0,
    )

    before = skeleton.model_dump()
    assert connectors_module.connector_candidate_quality_error(route, gap) == "route_arrives_after_following_stop"
    assert connectors_module.connector_gap_rejection_reasons(object(), gap) == {
        route.candidate_id: "route_arrives_after_following_stop",
    }
    with pytest.raises(ItineraryCompositionError, match="candidate_local_bus.*duration=66min"):
        connectors_module.materialize_skeleton_connectors(skeleton, object(), [gap], {})
    assert skeleton.model_dump() == before


def test_json_object_composition_schema_keeps_semantics_without_null_branches():
    from travel_agent.planning.itinerary.model_schema import (
        _composition_response_schema,
    )

    prompt_schema = _composition_response_schema(strict_wire=False)
    strict_schema = _composition_response_schema(strict_wire=True)
    prompt_required = set(prompt_schema["$defs"]["VisitPlacement"]["required"])
    strict_required = set(strict_schema["$defs"]["VisitPlacement"]["required"])

    assert {"placement_kind", "duration_minutes"} <= prompt_required
    assert "candidate_id" not in prompt_required
    assert "authored_place" not in prompt_required
    assert {
        "candidate_id",
        "authored_place",
        "planned_start",
        "planned_end",
    } <= strict_required


def test_theme_changes_query_plan_and_museum_exclusion_keeps_broad_discovery():
    architecture = make_intent_spec(make_research_intent("intent_arch", "contemporary architecture"))
    temple = make_intent_spec(make_research_intent("intent_temple", "traditional temple garden"))
    architecture_plan = build_research_query_plan(
        intent_spec=architecture,
        brief=make_research_brief(architecture),
    )
    temple_plan = build_research_query_plan(intent_spec=temple, brief=make_research_brief(temple))

    assert architecture_plan.content_hash != temple_plan.content_hash
    assert "contemporary architecture" in " ".join(
        query.query_text for query in architecture_plan.queries
    )
    assert "traditional temple garden" in " ".join(
        query.query_text for query in temple_plan.queries
    )

    exclusion = make_intent_spec(
        make_research_intent(
            "intent_no_museum",
            "不要博物馆",
            kind=IntentKind.MUST_EXCLUDE,
            strength=IntentStrength.HARD,
            verification=VerificationMode.MIXED,
        )
    )
    excluded_plan = build_research_query_plan(
        intent_spec=exclusion,
        brief=make_research_brief(exclusion),
    )
    assert all(
        "museum" not in query.query_text.casefold() for query in excluded_plan.queries
    )
    assert all("不要博物馆" in query.excluded_categories for query in excluded_plan.queries)


def test_admission_is_stable_while_ranking_and_selection_change_with_theme():
    architecture = make_research_intent("intent_arch", "contemporary architecture")
    temple = make_research_intent("intent_temple", "traditional temple garden")
    packet_arch = make_visit_packet(
        "candidate_arch",
        "Tokyo International Forum contemporary architecture",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_arch",
        intent_id=architecture.intent_id,
    )
    packet_temple = make_visit_packet(
        "candidate_temple",
        "Sensoji traditional temple garden",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_temple",
        intent_id=temple.intent_id,
    )
    catalog = make_catalog(packet_arch, packet_temple)
    admission_snapshot = [result.model_dump() for result in catalog.admission_results]

    architecture_matches = [
        CandidateIntentMatch(
            candidate_id="candidate_arch",
            intent_id=architecture.intent_id,
            status=IntentMatchStatus.MATCHED,
            score=1,
            method="semantic_batch_evaluation",
            supporting_fact_assertion_ids=["fact_candidate_arch"],
            supporting_source_record_ids=["source_candidate_arch"],
            reason_code="semantic_match",
        ),
        CandidateIntentMatch(
            candidate_id="candidate_temple",
            intent_id=architecture.intent_id,
            status=IntentMatchStatus.NOT_MATCHED,
            score=0,
            method="semantic_batch_evaluation",
            supporting_fact_assertion_ids=["fact_candidate_temple"],
            supporting_source_record_ids=["source_candidate_temple"],
            reason_code="semantic_not_match",
        ),
    ]
    architecture_spec = make_intent_spec(architecture)
    architecture_ranking = rank_candidates(
        catalog=catalog,
        intent_spec=architecture_spec,
        matches=architecture_matches,
    )
    architecture_plan = build_candidate_selection_plan(
        catalog=catalog,
        intent_spec=architecture_spec,
        ranking_scores=architecture_ranking,
        duration_days=1,
        destination_count=1,
    )

    temple_matches = [
        match.model_copy(
            update={
                "intent_id": temple.intent_id,
                "status": (
                    IntentMatchStatus.MATCHED
                    if match.candidate_id == "candidate_temple"
                    else IntentMatchStatus.NOT_MATCHED
                ),
                "score": 1 if match.candidate_id == "candidate_temple" else 0,
            }
        )
        for match in architecture_matches
    ]
    temple_spec = make_intent_spec(temple)
    temple_ranking = rank_candidates(
        catalog=catalog,
        intent_spec=temple_spec,
        matches=temple_matches,
    )
    temple_plan = build_candidate_selection_plan(
        catalog=catalog,
        intent_spec=temple_spec,
        ranking_scores=temple_ranking,
        duration_days=1,
        destination_count=1,
    )

    assert admission_snapshot == [
        result.model_dump() for result in catalog.admission_results
    ]
    assert architecture_plan.entries[0].candidate_id == "candidate_arch"
    assert temple_plan.entries[0].candidate_id == "candidate_temple"
    assert architecture_plan.content_hash != temple_plan.content_hash
    architecture_only = architecture_plan.model_copy(
        update={"entries": [architecture_plan.entries[0]]}
    )
    composition_catalog = catalog_for_candidate_selection(
        catalog,
        architecture_only,
    )
    assert [
        result.candidate_id for result in composition_catalog.admission_results
    ] == ["candidate_arch"]


def test_each_required_place_is_promoted_to_required_primary():
    west_lake = make_research_intent(
        "intent_west_lake",
        "西湖",
        kind=IntentKind.MUST_INCLUDE,
        strength=IntentStrength.HARD,
        verification=VerificationMode.MIXED,
    )
    guozhuang = make_research_intent(
        "intent_guozhuang",
        "郭庄",
        kind=IntentKind.MUST_INCLUDE,
        strength=IntentStrength.HARD,
        verification=VerificationMode.MIXED,
    )
    spec = make_intent_spec(west_lake, guozhuang)
    catalog = make_catalog(
        make_visit_packet(
            "candidate_west_lake",
            "西湖风景名胜区",
            origin=CandidateDiscoveryOrigin.INTENT_QUERY,
            query_id="query_west_lake",
            intent_id=west_lake.intent_id,
        ),
        make_visit_packet(
            "candidate_guozhuang",
            "郭庄",
            origin=CandidateDiscoveryOrigin.INTENT_QUERY,
            query_id="query_guozhuang",
            intent_id=guozhuang.intent_id,
        ),
    )
    matches = [
        CandidateIntentMatch(
            candidate_id="candidate_west_lake",
            intent_id=west_lake.intent_id,
            status=IntentMatchStatus.MATCHED,
            score=1,
            method="deterministic",
            supporting_fact_assertion_ids=["fact_candidate_west_lake"],
            supporting_source_record_ids=["source_candidate_west_lake"],
            reason_code="category_term_match",
        ),
        CandidateIntentMatch(
            candidate_id="candidate_guozhuang",
            intent_id=guozhuang.intent_id,
            status=IntentMatchStatus.MATCHED,
            score=1,
            method="deterministic",
            supporting_fact_assertion_ids=["fact_candidate_guozhuang"],
            supporting_source_record_ids=["source_candidate_guozhuang"],
            reason_code="category_term_match",
        ),
    ]

    ranking = rank_candidates(catalog=catalog, intent_spec=spec, matches=matches)
    selection = build_candidate_selection_plan(
        catalog=catalog,
        intent_spec=spec,
        ranking_scores=ranking,
        duration_days=1,
        destination_count=1,
    )

    required = {
        entry.candidate_id: entry
        for entry in selection.entries
        if entry.role is CandidateSelectionRole.REQUIRED_PRIMARY
    }
    assert set(required) == {"candidate_west_lake", "candidate_guozhuang"}
    assert required["candidate_west_lake"].covered_intent_ids == [west_lake.intent_id]
    assert required["candidate_guozhuang"].covered_intent_ids == [guozhuang.intent_id]
    assert selection.uncovered_intent_ids == []


def test_selection_preserves_each_exact_local_connector_beyond_domain_capacity():
    packets = [
        make_local_transport_packet(
            f"candidate_connector_{index}",
            origin_place_id=f"place_{index}",
            destination_place_id=f"place_{index + 1}",
        )
        for index in range(4)
    ]
    catalog = make_catalog(*packets)
    spec = make_intent_spec()
    ranking = rank_candidates(catalog=catalog, intent_spec=spec, matches=[])

    selection = build_candidate_selection_plan(
        catalog=catalog,
        intent_spec=spec,
        ranking_scores=ranking,
        duration_days=2,
        destination_count=1,
    )

    connector_entries = [
        entry
        for entry in selection.entries
        if entry.domain is ResearchDomain.LOCAL_TRANSPORT
    ]
    assert len(connector_entries) == 4
    assert all(
        entry.role is CandidateSelectionRole.REQUIRED_PRIMARY
        and entry.eligible_for_composition
        for entry in connector_entries
    )


def test_research_closeout_keeps_deterministic_connector_reconciliation():
    closed = SimpleNamespace(research_closed=True)

    assert _research_closeout_can_skip_connector_pass(
        TravelAgentState.model_construct(placement_skeleton=None), closed
    )
    assert not _research_closeout_can_skip_connector_pass(
        TravelAgentState.model_construct(placement_skeleton=object()), closed
    )


def test_closeout_only_allows_exact_connector_targeted_rounds():
    connector = SimpleNamespace(gap_id="connector_gap_1")

    assert not _closeout_blocks_targeted_round(
        SimpleNamespace(research_closed=True, composition_closed=False),
        [connector],
    )
    assert _closeout_blocks_targeted_round(
        SimpleNamespace(research_closed=True, composition_closed=False),
        [],
    )
    assert _closeout_blocks_targeted_round(
        SimpleNamespace(research_closed=True, composition_closed=True),
        [connector],
    )


def test_candidate_gate_routes_exact_connector_lookup_during_closeout(monkeypatch):
    from travel_agent.planning.research import node as candidate_gate

    state = TravelAgentState.model_construct(
        candidate_gate_route="transport_researcher",
        run_deadline=object(),
        placement_skeleton=object(),
        trip_workspace_v2=None,
        agent_assignments={
            "transport_researcher": {
                "require_current_candidate": True,
                "required_transport_classes": ["public_transit"],
                "connector_gaps": [{"gap_id": "connector_gap_1"}],
            }
        },
    )
    monkeypatch.setattr(
        candidate_gate,
        "observe_run_deadline",
        lambda deadline: (
            deadline,
            SimpleNamespace(research_closed=True, composition_closed=False),
        ),
    )

    assert candidate_gate.route_after_candidate_gate(state) == "transport_researcher"


def test_candidate_gate_stops_exact_connector_lookup_after_composition(monkeypatch):
    from travel_agent.planning.research import node as candidate_gate

    state = TravelAgentState.model_construct(
        candidate_gate_route="transport_researcher",
        run_deadline=object(),
        placement_skeleton=object(),
        trip_workspace_v2=None,
        agent_assignments={
            "transport_researcher": {
                "require_current_candidate": True,
                "required_transport_classes": ["public_transit"],
                "connector_gaps": [{"gap_id": "connector_gap_1"}],
            }
        },
    )
    monkeypatch.setattr(
        candidate_gate,
        "observe_run_deadline",
        lambda deadline: (
            deadline,
            SimpleNamespace(research_closed=True, composition_closed=True),
        ),
    )

    assert candidate_gate.route_after_candidate_gate(state) == "passed"


def test_selection_never_promotes_a_gate_rejected_candidate():
    intent = make_research_intent("intent_arch", "contemporary architecture")
    spec = make_intent_spec(intent)
    catalog = make_catalog(
        make_visit_packet(
            "candidate_rejected",
            "Unverified architecture candidate",
            origin=CandidateDiscoveryOrigin.INTENT_QUERY,
            query_id="query_arch",
            intent_id=intent.intent_id,
        )
    )
    matches = [
        CandidateIntentMatch(
            candidate_id="candidate_rejected",
            intent_id=intent.intent_id,
            status=IntentMatchStatus.MATCHED,
            score=1,
            method="semantic_batch_evaluation",
            supporting_fact_assertion_ids=["fact_candidate_rejected"],
            supporting_source_record_ids=["source_candidate_rejected"],
            reason_code="semantic_match",
        )
    ]
    ranking = rank_candidates(catalog=catalog, intent_spec=spec, matches=matches)
    assert ranking[0].hard_eligible is True

    plan_from_passed_catalog = build_candidate_selection_plan(
        catalog=catalog,
        intent_spec=spec,
        ranking_scores=ranking,
        duration_days=1,
        destination_count=1,
    )
    rejected_catalog = catalog.model_copy(
        update={
            "admission_results": [
                CandidateAdmissionResult(
                    candidate_id="candidate_rejected",
                    status="insufficient_for_admission",
                    missing_field_paths=["provider_evidence.name"],
                    evaluated_fact_revision=1,
                    evaluated_weather_revision=0,
                )
            ]
        }
    )

    rejected_plan = build_candidate_selection_plan(
        catalog=rejected_catalog,
        intent_spec=spec,
        ranking_scores=ranking,
        duration_days=1,
        destination_count=1,
    )

    assert rejected_plan.entries == []
    assert rejected_plan.uncovered_intent_ids == [intent.intent_id]
    with pytest.raises(ValueError, match="non-admitted candidate"):
        catalog_for_candidate_selection(rejected_catalog, plan_from_passed_catalog)


def test_composition_rules_preserve_prohibition_and_daily_capacity_semantics():
    exclusion = make_research_intent(
        "intent_no_museum",
        "museum",
        kind=IntentKind.MUST_EXCLUDE,
        strength=IntentStrength.HARD,
        verification=VerificationMode.DETERMINISTIC,
    ).model_copy(update={"impact_stages": ["research", "admission", "composition"]})
    capacity = IntentItem(
        intent_id="intent_two_visits",
        kind=IntentKind.QUANTITY,
        target=IntentTarget.VISIT,
        strength=IntentStrength.HARD,
        priority=100,
        value=CountIntentValue(operator="at_most", count=2, unit="day"),
        source_kind="current_request",
        source_ref_id="source_capacity",
        linked_constraint_ids=[],
        verification_mode=VerificationMode.DETERMINISTIC,
        impact_stages=["composition"],
        public_summary="每天最多两个主要景点",
    )

    rules = compile_composition_rules(make_intent_spec(exclusion, capacity))

    assert [(rule.rule_kind.value, rule.policy_on_failure) for rule in rules] == [
        ("must_not_place", "never_violate"),
        ("max_per_day", "never_violate"),
    ]
    assert rules[1].parameters.model_dump() == {
        "parameter_kind": "count",
        "count": 2,
        "unit": "day",
    }


def test_selected_capabilities_exclude_alternatives_from_composition_pool():
    intent = make_research_intent("intent_arch", "contemporary architecture")
    spec = make_intent_spec(intent)
    catalog = make_catalog(
        make_visit_packet(
            "candidate_arch",
            "Tokyo International Forum",
            origin=CandidateDiscoveryOrigin.INTENT_QUERY,
            query_id="query_arch",
            intent_id=intent.intent_id,
        )
    )
    matches = [
        CandidateIntentMatch(
            candidate_id="candidate_arch",
            intent_id=intent.intent_id,
            status=IntentMatchStatus.MATCHED,
            score=1,
            method="semantic_batch_evaluation",
            supporting_fact_assertion_ids=["fact_candidate_arch"],
            supporting_source_record_ids=["source_candidate_arch"],
            reason_code="semantic_match",
        )
    ]
    ranking = rank_candidates(catalog=catalog, intent_spec=spec, matches=matches)
    plan = build_candidate_selection_plan(
        catalog=catalog,
        intent_spec=spec,
        ranking_scores=ranking,
        duration_days=1,
        destination_count=1,
    )
    catalog = catalog.model_copy(update={"candidate_ranking_scores": ranking})

    selected, alternatives = selected_candidate_capabilities(
        catalog=catalog,
        selection_plan=plan,
    )

    assert [item.candidate_id for item in selected] == ["candidate_arch"]
    assert alternatives == []
    assert selected[0].matched_intent_ids == [intent.intent_id]
    assert selected[0].schedule_capabilities["recommended_duration_minutes"] == 90


def test_explore_selection_is_seeded_reproducible_and_diverse():
    intent = make_research_intent("intent_arch", "contemporary architecture")
    spec = make_intent_spec(intent)
    catalog = make_catalog(
        *[
            make_visit_packet(
                f"candidate_{index}",
                f"Architecture {index}",
                origin=CandidateDiscoveryOrigin.INTENT_QUERY,
                query_id=f"query_{index}",
                intent_id=intent.intent_id,
            )
            for index in range(1, 6)
        ]
    )
    matches = [
        CandidateIntentMatch(
            candidate_id=f"candidate_{index}",
            intent_id=intent.intent_id,
            status=IntentMatchStatus.MATCHED,
            score=1 - index * 0.005,
            method="semantic_batch_evaluation",
            supporting_fact_assertion_ids=[f"fact_candidate_{index}"],
            supporting_source_record_ids=[f"source_candidate_{index}"],
            reason_code="semantic_match",
        )
        for index in range(1, 6)
    ]
    ranking = rank_candidates(catalog=catalog, intent_spec=spec, matches=matches)

    def selected(seed: int):
        return build_candidate_selection_plan(
            catalog=catalog,
            intent_spec=spec,
            ranking_scores=ranking,
            duration_days=1,
            destination_count=1,
            selection_policy=SelectionPolicy(
                mode="explore",
                selection_seed=seed,
                diversity_strength=1,
                policy_version="candidate_selection.v1",
            ),
        )

    first = selected(1)
    replay = selected(1)
    variants = {
        tuple(
            entry.candidate_id
            for entry in selected(seed).entries
            if entry.eligible_for_composition
        )
        for seed in range(1, 8)
    }

    assert first == replay
    assert len(variants) > 1
    assert all(len(candidate_ids) == 2 for candidate_ids in variants)
    alternative_ids = {
        entry.candidate_id
        for entry in first.entries
        if not entry.eligible_for_composition
    }
    assert alternative_ids
    composition_catalog = catalog_for_candidate_selection(catalog, first)
    workspace_catalog = catalog_for_workspace_materialization(catalog, first)
    assert alternative_ids.isdisjoint(
        {item.candidate_id for item in composition_catalog.admission_results}
    )
    assert alternative_ids <= {
        item.candidate_id
        for item in workspace_catalog.admission_results
        if item.status == "passed"
    }


def test_fallback_candidate_is_penalized_and_targeted_repair_is_stable():
    intent = make_research_intent("intent_arch", "contemporary architecture")
    spec = make_intent_spec(intent)
    plan = build_research_query_plan(intent_spec=spec, brief=make_research_brief(spec))
    repeated, targeted = append_targeted_repair_query(
        plan,
        intent=intent,
        destination_id="destination_tokyo",
        destination_name="Tokyo",
        domain=ResearchDomain.VISIT,
        desired_candidate_count=2,
    )
    repeated_again, targeted_again = append_targeted_repair_query(
        repeated,
        intent=intent,
        destination_id="destination_tokyo",
        destination_name="Tokyo",
        domain=ResearchDomain.VISIT,
        desired_candidate_count=2,
    )
    assert targeted.query_id == targeted_again.query_id
    assert repeated.content_hash == repeated_again.content_hash
    fallback = next(
        query
        for query in plan.queries
        if query.query_kind is ResearchQueryKind.GENERIC_FALLBACK
    )
    policy = FallbackQueryPolicy()
    assert not policy.is_allowed(
        fallback,
        executed_query_ids=set(fallback.fallback_after_query_ids),
        admitted_candidate_count=0,
        required_candidate_count=1,
        research_window_open=False,
        run_budget_available=True,
    )
    assert policy.is_allowed(
        fallback,
        executed_query_ids=set(fallback.fallback_after_query_ids),
        admitted_candidate_count=0,
        required_candidate_count=1,
        research_window_open=True,
        run_budget_available=True,
    )
    excluded_fallback = fallback.model_copy(
        update={"excluded_categories": ["不要博物馆"]}
    )
    assert policy.is_allowed(
        excluded_fallback,
        executed_query_ids=set(excluded_fallback.fallback_after_query_ids),
        admitted_candidate_count=0,
        required_candidate_count=1,
        research_window_open=True,
        run_budget_available=True,
    )

    intent_packet = make_visit_packet(
        "candidate_intent",
        "Intent Place",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_intent",
        intent_id=intent.intent_id,
    )
    fallback_packet = make_visit_packet(
        "candidate_fallback",
        "Fallback Place",
        origin=CandidateDiscoveryOrigin.GENERIC_FALLBACK,
        query_id="query_fallback",
        intent_id=intent.intent_id,
    )
    catalog = make_catalog(intent_packet, fallback_packet)
    matches = [
        CandidateIntentMatch(
            candidate_id=candidate_id,
            intent_id=intent.intent_id,
            status=IntentMatchStatus.MATCHED,
            score=1,
            method="semantic_batch_evaluation",
            supporting_fact_assertion_ids=[f"fact_{candidate_id}"],
            supporting_source_record_ids=[f"source_{candidate_id}"],
            reason_code="semantic_match",
        )
        for candidate_id in ("candidate_intent", "candidate_fallback")
    ]
    ranking = rank_candidates(catalog=catalog, intent_spec=spec, matches=matches)
    by_id = {score.candidate_id: score for score in ranking}
    assert by_id["candidate_intent"].generic_fallback_penalty == 0
    assert by_id["candidate_fallback"].generic_fallback_penalty > 0
    selection = build_candidate_selection_plan(
        catalog=catalog,
        intent_spec=spec,
        ranking_scores=ranking,
        duration_days=1,
        destination_count=1,
    )
    assert selection.entries[0].candidate_id == "candidate_intent"


def test_generic_fallback_origin_lands_in_the_ranking_tuple():
    """GENERIC_FALLBACK 来源的候选，ranking_tuple 的扣分位就是常量的相反数。"""
    intent = make_research_intent("intent_arch", "contemporary architecture")
    spec = make_intent_spec(intent)
    intent_packet = make_visit_packet(
        "candidate_intent",
        "Intent Place",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_intent",
        intent_id=intent.intent_id,
    )
    fallback_packet = make_visit_packet(
        "candidate_fallback",
        "Fallback Place",
        origin=CandidateDiscoveryOrigin.GENERIC_FALLBACK,
        query_id="query_fallback",
        intent_id=intent.intent_id,
    )
    catalog = make_catalog(intent_packet, fallback_packet)
    matches = [
        CandidateIntentMatch(
            candidate_id=candidate_id,
            intent_id=intent.intent_id,
            status=IntentMatchStatus.MATCHED,
            score=1,
            method="semantic_batch_evaluation",
            supporting_fact_assertion_ids=[f"fact_{candidate_id}"],
            supporting_source_record_ids=[f"source_{candidate_id}"],
            reason_code="semantic_match",
        )
        for candidate_id in ("candidate_intent", "candidate_fallback")
    ]
    by_id = {
        score.candidate_id: score
        for score in rank_candidates(catalog=catalog, intent_spec=spec, matches=matches)
    }
    # ranking_tuple 的第 11 位（下标 10）是 fallback 扣分位，见 candidate_ranking.py
    # 里构造 ranking_tuple 的那段。
    fallback_slot = 10
    assert by_id["candidate_fallback"].ranking_tuple[fallback_slot] == (
        -GENERIC_FALLBACK_PENALTY
    )
    assert by_id["candidate_intent"].ranking_tuple[fallback_slot] == 0.0
    # 同一个值还要进 CandidateRankingScore，candidate_selection 在加总时减的是它。
    assert by_id["candidate_fallback"].generic_fallback_penalty == (
        GENERIC_FALLBACK_PENALTY
    )


@pytest.mark.asyncio
async def test_semantic_evaluator_cannot_claim_a_match_without_evidence():
    intent = make_research_intent("intent_arch", "contemporary architecture")
    spec = make_intent_spec(intent)
    packet = make_visit_packet(
        "candidate_one",
        "A place",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_one",
        intent_id=intent.intent_id,
    )

    class FakeModel:
        async def ainvoke(self, *_args, **_kwargs):
            return json.dumps(
                {
                    "matches": [
                        {
                            "candidate_id": "candidate_one",
                            "intent_id": intent.intent_id,
                            "status": "matched",
                            "score": 1,
                            "supporting_fact_assertion_ids": [],
                            "supporting_source_record_ids": [],
                            "reason_code": "unsupported_claim",
                            "public_reason": "looks suitable",
                        }
                    ]
                }
            )

    matches, _cache = await evaluate_candidate_intents(
        catalog=make_catalog(packet),
        intent_spec=spec,
        llm=FakeModel(),
    )
    assert matches[0].status is IntentMatchStatus.UNKNOWN
    assert matches[0].score is None


@pytest.mark.asyncio
async def test_exact_miss_defers_to_compact_structured_semantic_evaluation():
    exact_intent = make_research_intent(
        "intent_local_name",
        "西湖",
        kind=IntentKind.MUST_INCLUDE,
        strength=IntentStrength.HARD,
        verification=VerificationMode.DETERMINISTIC,
    )
    theme_intent = make_research_intent("intent_theme", "waterside landscape")
    spec = make_intent_spec(exact_intent, theme_intent)
    packet = make_visit_packet(
        "candidate_west_lake",
        "West Lake Scenic Area",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_west_lake",
        intent_id=exact_intent.intent_id,
    )

    class FakeModel:
        kwargs = None
        payload = None

        async def ainvoke(self, messages, **kwargs):
            self.kwargs = kwargs
            self.payload = json.loads(messages[-1]["content"])
            return json.dumps(
                {
                    "matches": [
                        {
                            "candidate_id": "candidate_west_lake",
                            "intent_id": intent.intent_id,
                            "status": "matched",
                            "score": 1,
                            "supporting_fact_assertion_ids": [
                                "fact_candidate_west_lake"
                            ],
                            "supporting_source_record_ids": [
                                "source_candidate_west_lake"
                            ],
                            "reason_code": "semantic_name_equivalence",
                            "public_reason": "Provider 名称与结构化意图语义一致",
                        }
                        for intent in (exact_intent, theme_intent)
                    ]
                }
            )

    model = FakeModel()
    matches, _cache = await evaluate_candidate_intents(
        catalog=make_catalog(packet),
        intent_spec=spec,
        llm=model,
    )

    assert {
        match.intent_id
        for match in matches
        if match.status is IntentMatchStatus.MATCHED
    } == {
        exact_intent.intent_id,
        theme_intent.intent_id,
    }
    assert len(model.payload["candidates"]) == 1
    assert len(model.payload["intents"]) == 2
    assert len(model.payload["evaluations"]) == 2
    assert "max_output_tokens" not in model.kwargs


@pytest.mark.asyncio
async def test_semantic_exclusion_becomes_a_hard_ranking_violation():
    intent = make_research_intent(
        "intent_no_museum",
        "不要博物馆",
        kind=IntentKind.MUST_EXCLUDE,
        strength=IntentStrength.HARD,
        verification=VerificationMode.SEMANTIC,
    )
    spec = make_intent_spec(intent)
    packet = make_visit_packet(
        "candidate_museum",
        "Museum Place",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_museum",
        intent_id=intent.intent_id,
    )
    catalog = make_catalog(packet)

    class FakeModel:
        async def ainvoke(self, *_args, **_kwargs):
            return json.dumps(
                {
                    "matches": [
                        {
                            "candidate_id": "candidate_museum",
                            "intent_id": intent.intent_id,
                            "status": "matched",
                            "score": 1,
                            "supporting_fact_assertion_ids": ["fact_candidate_museum"],
                            "supporting_source_record_ids": ["source_candidate_museum"],
                            "reason_code": "excluded_category_present",
                            "public_reason": "候选属于博物馆",
                        }
                    ]
                }
            )

    matches, _cache = await evaluate_candidate_intents(
        catalog=catalog,
        intent_spec=spec,
        llm=FakeModel(),
    )
    ranking = rank_candidates(catalog=catalog, intent_spec=spec, matches=matches)
    assert matches[0].status is IntentMatchStatus.VIOLATED
    assert ranking[0].hard_eligible is False
    assert ranking[0].hard_violation_intent_ids == [intent.intent_id]


@pytest.mark.asyncio
async def test_worker_executes_intent_and_structural_queries_before_fallback(
    monkeypatch,
):
    intent = make_research_intent("intent_arch", "contemporary architecture")
    spec = make_intent_spec(intent)
    plan = build_research_query_plan(intent_spec=spec, brief=make_research_brief(spec))
    queries = [query for query in plan.queries if query.domain is ResearchDomain.VISIT]
    calls = []

    async def fake_execute_tool(_name, arguments, **_kwargs):
        calls.append((_name, arguments["query"]))
        results = (
            [
                {
                    "title": "Tokyo International Forum — visitor information",
                    "snippet": "A contemporary architectural landmark open to visitors.",
                }
            ]
            if "official visitor guide" in arguments["query"]
            else []
        )
        return {
            "status": "success",
            "audit_id": f"audit_{len(calls)}",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "sanitized_result": {"results": results},
        }

    monkeypatch.setattr('travel_agent.planning.research.destination.dining_binding.execute_tool', fake_execute_tool)
    monkeypatch.setattr('travel_agent.planning.research.destination.discovery.execute_tool', fake_execute_tool)
    monkeypatch.setattr('travel_agent.planning.research.destination.operating_information.execute_tool', fake_execute_tool)
    executed = []
    await planning_research_destination_discovery.discover_and_resolve_required_places(
        messages=[],
        available_tools=[{"schema": {"function": {"name": name}}} for name in ("global_place_search", "free_web_search")],
        required_candidate_kinds=["visit"],
        destination_boundaries=[
            {
                "destination_id": "destination_tokyo",
                "name": "Tokyo",
                "country_code": "jp",
                "latitude": 35.68,
                "longitude": 139.76,
            }
        ],
        tool_context={},
        authoritative_tool_results=[],
        planned_queries=queries,
        executed_query_ids=executed,
    )
    kinds = [plan.query_index()[query_id].query_kind for query_id in executed]
    assert kinds == [
        ResearchQueryKind.INTENT_PRIMARY,
        ResearchQueryKind.STRUCTURAL,
        ResearchQueryKind.GENERIC_FALLBACK,
    ]
    assert "contemporary architecture" in calls[0][1]
    assert all(name == "free_web_search" for name, _query in calls)
    assert all("museum" not in query.casefold() for _name, query in calls)


def test_packet_compiler_owns_and_merges_candidate_discovery_lineage():
    packet = make_visit_packet(
        "candidate_one",
        "Candidate One",
        origin=CandidateDiscoveryOrigin.GENERIC_FALLBACK,
        query_id="model_query",
        intent_id="model_intent",
    )
    payload = packet.model_dump(mode="python")
    payload["executed_query_ids"] = ["query_primary", "query_structural"]
    payload["query_context"] = {
        "research_round": 2,
        "query_lineage": [
            {
                "query_id": "query_primary",
                "domain": "visit",
                "query_kind": "intent_primary",
                "intent_ids": ["intent_arch"],
            },
            {
                "query_id": "query_structural",
                "domain": "visit",
                "query_kind": "structural",
                "intent_ids": [],
            },
        ],
    }

    _bind_candidate_discovery_lineage(payload)

    assert payload["candidate_discovery_records"] == [
        {
            "candidate_id": "candidate_one",
            "generation_id": "generation_test",
            "query_ids": ["query_primary", "query_structural"],
            "intent_ids": ["intent_arch"],
            "origins": ["intent_query", "structural_query"],
            "provider_audit_ids": ["audit_candidate_one"],
            "discovered_at_rounds": [2],
        }
    ]


def test_packet_lineage_does_not_attach_hard_intent_to_generic_provider_query():
    packet = make_visit_packet(
        "candidate_museum",
        "City Museum",
        origin=CandidateDiscoveryOrigin.GENERIC_FALLBACK,
        query_id="model_query",
        intent_id="model_intent",
    )
    payload = packet.model_dump(mode="python")
    payload["executed_query_ids"] = ["query_required", "query_generic"]
    payload["query_context"] = {
        "research_round": 0,
        "query_lineage": [
            {
                "query_id": "query_required",
                "domain": "visit",
                "query_kind": "intent_primary",
                "query_text": "City Required Garden places",
                "aliases": ["Required Garden"],
                "intent_ids": ["intent_required"],
            },
            {
                "query_id": "query_generic",
                "domain": "visit",
                "query_kind": "generic_fallback",
                "query_text": "museum in City",
                "aliases": [],
                "intent_ids": [],
            },
        ],
    }
    payload["source_records"][0]["snapshot"]["query"] = "museum in City"

    _bind_candidate_discovery_lineage(payload)

    record = payload["candidate_discovery_records"][0]
    assert record["query_ids"] == ["query_generic"]
    assert record["intent_ids"] == []
    assert record["origins"] == ["generic_fallback"]


def test_targeted_packet_keeps_traced_candidate_and_prunes_unrelated_extras():
    required = make_visit_packet(
        "candidate_required",
        "Required Garden",
        origin=CandidateDiscoveryOrigin.TARGETED_REPAIR,
        query_id="model_query",
        intent_id="model_intent",
    )
    unrelated = make_visit_packet(
        "candidate_unrelated",
        "Unrelated Tower",
        origin=CandidateDiscoveryOrigin.TARGETED_REPAIR,
        query_id="model_query",
        intent_id="model_intent",
    )
    payload = required.model_dump(mode="python")
    payload["candidates"].extend(
        candidate.model_dump(mode="python") for candidate in unrelated.candidates
    )
    payload["source_records"].extend(
        source.model_dump(mode="python") for source in unrelated.source_records
    )
    payload["fact_assertions"].extend(
        fact.model_dump(mode="python") for fact in unrelated.fact_assertions
    )
    payload["field_provenance"].extend(
        item.model_dump(mode="python") for item in unrelated.field_provenance
    )
    payload["executed_query_ids"] = ["query_targeted"]
    payload["query_context"] = {
        "research_round": 1,
        "query_lineage": [
            {
                "query_id": "query_targeted",
                "domain": "visit",
                "query_kind": "targeted_repair",
                "query_text": "City Required Garden places",
                "aliases": ["Required Garden"],
                "intent_ids": ["intent_required"],
            }
        ],
    }
    payload["source_records"][0]["snapshot"]["query"] = "Required Garden City"
    payload["source_records"][1]["snapshot"]["query"] = "Unrelated Tower City"

    _bind_candidate_discovery_lineage(payload)

    assert [candidate["candidate_id"] for candidate in payload["candidates"]] == [
        "candidate_required"
    ]
    assert [
        record["candidate_id"] for record in payload["candidate_discovery_records"]
    ] == ["candidate_required"]
    assert payload["candidate_discovery_records"][0]["intent_ids"] == [
        "intent_required"
    ]
    assert [fact["entity_ref"]["entity_id"] for fact in payload["fact_assertions"]] == [
        "candidate_required"
    ]
    assert [source["source_record_id"] for source in payload["source_records"]] == [
        "source_candidate_required"
    ]


def test_targeted_packet_still_rejects_when_no_candidate_has_query_lineage():
    from travel_agent.planning.research.output.policy import ResearchPacketOutputError

    packet = make_visit_packet(
        "candidate_unrelated",
        "Unrelated Tower",
        origin=CandidateDiscoveryOrigin.TARGETED_REPAIR,
        query_id="model_query",
        intent_id="model_intent",
    )
    payload = packet.model_dump(mode="python")
    payload["executed_query_ids"] = ["query_targeted"]
    payload["query_context"] = {
        "query_lineage": [
            {
                "query_id": "query_targeted",
                "domain": "visit",
                "query_kind": "targeted_repair",
                "query_text": "City Required Garden places",
                "aliases": ["Required Garden"],
                "intent_ids": ["intent_required"],
            }
        ]
    }
    payload["source_records"][0]["snapshot"]["query"] = "Unrelated Tower City"

    with pytest.raises(
        ResearchPacketOutputError,
        match="no server-owned executed query lineage",
    ):
        _bind_candidate_discovery_lineage(payload)


def test_provider_fallback_prioritizes_llm_structured_intent_aliases():
    base_payload = {
        "query_context": {
            "controlled_trip_identity": {
                "destinations": [{"place_id": "destination_city"}],
            },
            "query_lineage": [
                {
                    "query_id": "query_one",
                    "domain": "visit",
                    "query_kind": "intent_primary",
                    "query_text": "City Required Garden places",
                    "aliases": ["Required Garden"],
                    "intent_ids": ["intent_one"],
                },
                {
                    "query_id": "query_two",
                    "domain": "visit",
                    "query_kind": "intent_primary",
                    "query_text": "City Historic House places",
                    "aliases": ["Historic House"],
                    "intent_ids": ["intent_two"],
                },
            ],
        }
    }
    options = {
        "visit": [
            {
                "candidate_kind": "visit",
                "place_id": "place_generic",
                "name": "Generic Museum",
                "provider_query": "museum in City",
            },
            {
                "candidate_kind": "visit",
                "place_id": "place_garden",
                "name": "Required Garden Scenic Area",
                "provider_query": "Required Garden",
            },
            {
                "candidate_kind": "visit",
                "place_id": "place_house",
                "name": "Historic House",
                "provider_query": "Historic House City",
            },
        ]
    }

    selected = _default_provider_place_selections(
        base_payload=base_payload,
        scoped_options=options,
        selection_limit=3,
    )["selections"]

    assert [row["place_id"] for row in selected] == [
        "place_garden",
        "place_house",
        "place_generic",
    ]
    assert selected[0]["selection_reasons"][0].startswith("命中 LLM 结构化意图查询")


def test_empty_model_place_selection_preserves_verified_provider_supply():
    base_payload = {
        "query_context": {
            "controlled_trip_identity": {
                "destinations": [{"place_id": "destination_city"}],
                "start_date": "2026-08-28",
                "end_date": "2026-08-29",
            }
        }
    }
    options = {
        "lodging": [
            {
                "candidate_kind": "lodging",
                "place_id": "hotel_one",
                "name": "Provider Hotel",
                "provider_query": "lodging in City",
            }
        ]
    }
    schema = _provider_selection_response_schema(
        "accommodation_researcher",
        options,
    )

    selections = _provider_place_selections_or_default(
        {"selections": []},
        model_authored=True,
        base_payload=base_payload,
        expected_worker="accommodation_researcher",
        scoped_options=options,
        selection_schema=schema,
    )

    assert [selection["place_id"] for selection in selections] == ["hotel_one"]
    assert selections[0]["nights"] == 1


def test_invalid_route_selection_fallback_keeps_each_local_adjacency():
    def route_option(index: int, origin: str, destination: str) -> dict[str, object]:
        return {
            "route_id": f"route_{index}",
            "transport_class": "public_transit",
            "selected_mode": "bus",
            "from_endpoint": {"place_id": origin, "name": origin},
            "to_endpoint": {"place_id": destination, "name": destination},
            "duration_minutes": 10 + index,
            "provider_evidence_scope_id": None,
        }

    options = [
        route_option(1, "station", "garden"),
        route_option(2, "garden", "lake"),
        route_option(3, "lake", "restaurant"),
        route_option(4, "restaurant", "museum"),
    ]
    maximum = _provider_route_selection_limit(
        options,
        required_transport_classes=["public_transit"],
    )
    invalid_model_payload = {
        "selections": [
            {
                "route_id": "route_1",
                "destination_id": "destination_city",
                "selection_reasons": ["端点正确", "路线可执行"],
                "tradeoff": "动态路况待确认",
                "booking_status": "not_required",
                "weather_sensitivity": {
                    "exposure": "mixed",
                    "rain_sensitivity": "low",
                    "heat_sensitivity": "low",
                    "cold_sensitivity": "low",
                    "wind_sensitivity": "low",
                    "requires_clear_visibility": False,
                },
                "invented_field": "not in the typed domain",
            }
        ]
    }

    selections = _provider_route_selections_or_default(
        invalid_model_payload,
        model_authored=True,
        eligible_route_options=options,
        destination_ids=["destination_city"],
        maximum_selections=maximum,
    )

    assert maximum == 4
    assert [selection["route_id"] for selection in selections] == [
        "route_1",
        "route_2",
        "route_3",
        "route_4",
    ]


def test_route_fallback_keeps_one_option_per_long_distance_scope():
    options = [
        {
            "route_id": "outbound_fast",
            "transport_class": "long_distance",
            "selected_mode": "high_speed_rail",
            "from_endpoint": {"place_id": "origin"},
            "to_endpoint": {"place_id": "destination"},
            "duration_minutes": 45,
            "provider_evidence_scope_id": "scope_outbound",
        },
        {
            "route_id": "outbound_slow",
            "transport_class": "long_distance",
            "selected_mode": "high_speed_rail",
            "from_endpoint": {"place_id": "origin"},
            "to_endpoint": {"place_id": "destination"},
            "duration_minutes": 60,
            "provider_evidence_scope_id": "scope_outbound",
        },
        {
            "route_id": "return_only",
            "transport_class": "long_distance",
            "selected_mode": "high_speed_rail",
            "from_endpoint": {"place_id": "destination"},
            "to_endpoint": {"place_id": "origin"},
            "duration_minutes": 50,
            "provider_evidence_scope_id": "scope_return",
        },
    ]
    maximum = _provider_route_selection_limit(
        options,
        required_transport_classes=["long_distance"],
    )

    selections = _provider_route_selections_or_default(
        {"selections": []},
        model_authored=True,
        eligible_route_options=options,
        destination_ids=["destination_city"],
        maximum_selections=maximum,
    )

    assert maximum == 2
    assert [selection["route_id"] for selection in selections] == [
        "outbound_fast",
        "return_only",
    ]


def test_domain_cap_keeps_targeted_and_intent_candidates_before_fallback():
    targeted = make_visit_packet(
        "candidate_targeted",
        "Targeted Place",
        origin=CandidateDiscoveryOrigin.TARGETED_REPAIR,
        query_id="query_targeted",
        intent_id="intent_arch",
    )
    intent = make_visit_packet(
        "candidate_intent",
        "Intent Place",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_intent",
        intent_id="intent_arch",
    )
    fallback = make_visit_packet(
        "candidate_fallback",
        "Fallback Place",
        origin=CandidateDiscoveryOrigin.GENERIC_FALLBACK,
        query_id="query_fallback",
        intent_id="intent_arch",
    )

    capped = _apply_candidate_caps(
        [fallback, intent, targeted],
        {ResearchDomain.VISIT.value: 2},
    )

    assert {
        candidate.candidate_id for packet in capped for candidate in packet.candidates
    } == {"candidate_targeted", "candidate_intent"}


# ─────────────────────────────────────────────────────────────────────────────
# 静默降级留痕（评审条目 B9 的第二处）。
#
# 这个模块原来有三条静默路径：模型响应解析失败被吞成「没有任何行」、分数解析失败被
# 哨兵值丢掉、以及「精确匹配不中就交给语义评估器」这条正常移交发生时不留痕。三条
# 都必须带得出「哪一次执行的哪个域、这一轮多大」—— 这张图有修复回边、有并发扇出，
# 一条 backend.log 里三个 worker 的输出会交织，不带这些就没法归因。
#
# 断言写在这里而不是新文件里：上面那批 `_intent` / `_packet` / `_catalog` 就是这三条
# 路径要的输入，重建一份只会多一份要跟着改的夹具。
# ─────────────────────────────────────────────────────────────────────────────

_EVAL_LOGGER = "travel_agent.planning.requirements.candidate_evaluation"


def _warnings(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == _EVAL_LOGGER and record.levelno == logging.WARNING
    ]


@pytest.mark.asyncio
async def test_unparsed_model_response_is_logged_with_domain_and_round_scale(caplog):
    """(1) 整批响应解析失败 → WARNING，带异常类型、domain、本轮规模。"""

    intent = make_research_intent("intent_arch", "contemporary architecture")
    spec = make_intent_spec(intent)
    packet = make_visit_packet(
        "candidate_one",
        "A place",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_one",
        intent_id=intent.intent_id,
    )

    class BrokenModel:
        async def ainvoke(self, *_args, **_kwargs):
            return "not json at all"

    with caplog.at_level(logging.WARNING, logger=_EVAL_LOGGER):
        matches, _cache = await evaluate_candidate_intents(
            catalog=make_catalog(packet),
            intent_spec=spec,
            llm=BrokenModel(),
        )

    lines = _warnings(caplog)
    assert len(lines) == 1, lines
    assert "semantic batch unparsed" in lines[0]
    assert "domain=visit" in lines[0]
    assert "pairs=1 candidates=1 intents=1" in lines[0]
    assert "error=" in lines[0]
    assert "run=" in lines[0] and "node=" in lines[0]
    # 降级的后果本身没变：本域每个候选照旧落 UNKNOWN。
    assert [match.status for match in matches] == [IntentMatchStatus.UNKNOWN]


@pytest.mark.asyncio
async def test_unparsed_score_is_logged_and_the_score_is_still_dropped(caplog):
    """(2) 分数解析失败 → WARNING 指名具体哪一对；score 仍然是 None。"""

    intent = make_research_intent("intent_arch", "contemporary architecture")
    spec = make_intent_spec(intent)
    packet = make_visit_packet(
        "candidate_one",
        "A place",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_one",
        intent_id=intent.intent_id,
    )

    class BadScoreModel:
        async def ainvoke(self, *_args, **_kwargs):
            return json.dumps(
                {
                    "matches": [
                        {
                            "candidate_id": "candidate_one",
                            "intent_id": intent.intent_id,
                            "status": "matched",
                            "score": "很高",
                            "supporting_fact_assertion_ids": ["fact_candidate_one"],
                            "supporting_source_record_ids": ["source_candidate_one"],
                        }
                    ]
                }
            )

    with caplog.at_level(logging.WARNING, logger=_EVAL_LOGGER):
        matches, _cache = await evaluate_candidate_intents(
            catalog=make_catalog(packet),
            intent_spec=spec,
            llm=BadScoreModel(),
        )

    lines = _warnings(caplog)
    assert len(lines) == 1, lines
    assert "score unparsed" in lines[0]
    assert "domain=visit" in lines[0]
    assert "pairs=1" in lines[0]
    assert "candidate=candidate_one" in lines[0]
    assert f"intent={intent.intent_id}" in lines[0]
    assert "run=" in lines[0] and "node=" in lines[0]
    # 行为不变：-1.0 哨兵让 0.0 <= x <= 1.0 不成立，分数被丢掉。
    assert [match.score for match in matches] == [None]


@pytest.mark.asyncio
async def test_deferral_to_semantic_evaluator_leaves_a_debug_trace(caplog):
    """(3) 移交语义评估器 → DEBUG（级别低于前两条），带 domain 与本轮规模。

    要的是 `_deterministic_match` 里 ``if not matched_terms`` 那一条，所以 intent 必须
    先过得了它上面那道门（kind 在确定性集合里、verification_mode 不是 SEMANTIC），
    再在词面上不中 —— 「潜水」不在 "A place" 里。
    """

    intent = make_research_intent(
        "intent_diving",
        "潜水",
        kind=IntentKind.MUST_INCLUDE,
        strength=IntentStrength.HARD,
        verification=VerificationMode.DETERMINISTIC,
    )
    spec = make_intent_spec(intent)
    packet = make_visit_packet(
        "candidate_one",
        "A place",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_one",
        intent_id=intent.intent_id,
    )

    with caplog.at_level(logging.DEBUG, logger=_EVAL_LOGGER):
        await evaluate_candidate_intents(
            catalog=make_catalog(packet),
            intent_spec=spec,
            llm=None,
        )

    messages = [
        record.getMessage() for record in caplog.records if record.name == _EVAL_LOGGER
    ]
    # 这条路径不该产生 WARNING：它是正常移交，不是降级。
    assert _warnings(caplog) == []

    deferred = [m for m in messages if "deferred to semantic evaluator" in m]
    assert len(deferred) == 1, messages
    assert "domain=visit" in deferred[0]
    assert "candidate=candidate_one" in deferred[0]
    assert f"intent={intent.intent_id}" in deferred[0]

    # 本轮规模由按域那条给（`_deterministic_match` 一次只看一对，拿不到规模）。
    scale = [m for m in messages if "semantic batch |" in m]
    assert len(scale) == 1, messages
    assert "domain=visit" in scale[0]
    assert "pairs=1 candidates=1 intents=1" in scale[0]
    assert "llm=no" in scale[0]


@pytest.mark.asyncio
async def test_trace_scope_reads_the_ambient_run_and_node(caplog):
    """归因串取自 runtime.context 的 contextvar，不是新加的参数穿透。"""

    intent = make_research_intent("intent_arch", "contemporary architecture")
    spec = make_intent_spec(intent)
    packet = make_visit_packet(
        "candidate_one",
        "A place",
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id="query_one",
        intent_id=intent.intent_id,
    )

    class BrokenModel:
        async def ainvoke(self, *_args, **_kwargs):
            return "not json at all"

    run_token = current_run_id.set("run_under_test")
    node_token = current_node.set("candidate_gate")
    try:
        with caplog.at_level(logging.WARNING, logger=_EVAL_LOGGER):
            await evaluate_candidate_intents(
                catalog=make_catalog(packet),
                intent_spec=spec,
                llm=BrokenModel(),
            )
    finally:
        current_run_id.reset(run_token)
        current_node.reset(node_token)

    lines = _warnings(caplog)
    assert len(lines) == 1
    assert "run=run_under_test node=candidate_gate" in lines[0]


def _quality_packet(
    candidate_id,
    *,
    longitude=None,
    minutes=90,
    visit_type="culture",
    provider_type="museum",
):
    packet = make_visit_packet(
        candidate_id,
        candidate_id,
        origin=CandidateDiscoveryOrigin.INTENT_QUERY,
        query_id=f"query_{candidate_id}",
        intent_id="intent_theme",
    )
    candidate = packet.candidates[0].model_copy(
        update={
            "recommended_duration_minutes": minutes,
            "visit_type": visit_type,
            "provider_place_type": provider_type,
        }
    )
    facts = list(packet.fact_assertions)
    if longitude is not None:
        for field, value in (("latitude", 35.68), ("longitude", longitude)):
            facts.append(
                packet.fact_assertions[0].model_copy(
                    update={
                        "fact_assertion_id": f"{candidate_id}_{field}",
                        "field_path": field,
                        "asserted_value": value,
                    }
                )
            )
        candidate = candidate.model_copy(
            update={
                "fact_assertion_ids": [fact.fact_assertion_id for fact in facts],
                "field_paths": ["name", "latitude", "longitude"],
            }
        )
    provenance = [
        FieldProvenance(
            origin="external_fact",
            entity_ref=fact.entity_ref,
            field_path=fact.field_path,
            reference_ids=[fact.fact_assertion_id],
        )
        for fact in facts
    ]
    return packet.model_copy(
        update={
            "candidates": [candidate],
            "fact_assertions": facts,
            "field_provenance": provenance,
        }
    )


def _quality_selection(spec, *packets, budgets=None, destinations=None):
    catalog = make_catalog(*packets)
    matches = [
        CandidateIntentMatch(
            candidate_id=packet.candidates[0].candidate_id,
            intent_id=intent.intent_id,
            status=IntentMatchStatus.MATCHED,
            score=1,
            method="semantic_batch_evaluation",
            supporting_fact_assertion_ids=[packet.fact_assertions[0].fact_assertion_id],
            supporting_source_record_ids=[packet.source_records[0].source_record_id],
            reason_code="semantic_match",
        )
        for packet in packets
        for intent in spec.active_items
        if intent.kind in {IntentKind.THEME, IntentKind.MUST_INCLUDE}
    ]
    rankings = rank_candidates(catalog=catalog, intent_spec=spec, matches=matches)
    plan = build_candidate_selection_plan(
        catalog=catalog,
        intent_spec=spec,
        ranking_scores=rankings,
        duration_days=len(budgets) if budgets is not None else 1,
        destination_count=len(set(destinations)) if destinations else 1,
        daily_visit_minutes=budgets,
        daily_destination_ids=destinations,
    )
    return plan, {score.candidate_id: score for score in rankings}


def test_selection_uses_verified_nearby_places_without_forcing_culture_diversity():
    spec = make_intent_spec(make_research_intent("intent_theme", "museums and opera"))
    plan, scores = _quality_selection(
        spec,
        _quality_packet("a_remote", longitude=140.1),
        _quality_packet("b_museum", longitude=139.760),
        _quality_packet("c_opera_museum", longitude=139.761),
        _quality_packet("d_unknown"),
    )
    assert plan.composition_candidate_ids() == {"b_museum", "c_opera_museum"}
    assert (
        scores["a_remote"].travel_cost_penalty > scores["b_museum"].travel_cost_penalty
    )
    assert scores["d_unknown"].travel_cost_penalty > 0
    unknown_plan, _ = _quality_selection(spec, _quality_packet("d_unknown"))
    assert any(
        "坐标尚待核实" in reason
        for entry in unknown_plan.entries
        for reason in entry.selection_reasons
    )

    diversity = make_research_intent(
        "intent_variety", "different experiences", kind=IntentKind.DIVERSITY
    )
    diverse_plan, _ = _quality_selection(
        make_intent_spec(*spec.active_items, diversity),
        _quality_packet("a_museum", longitude=139.760),
        _quality_packet("b_museum", longitude=139.761),
        _quality_packet(
            "c_garden", longitude=139.762, visit_type="nature", provider_type="garden"
        ),
    )
    assert "c_garden" in diverse_plan.composition_candidate_ids()


def test_selection_uses_time_budget_and_keeps_required_candidates_when_time_is_short():
    theme = make_research_intent("intent_theme", "culture")
    packets = [
        _quality_packet(
            f"candidate_{index}", longitude=139.76 + index / 1000, minutes=90
        )
        for index in range(5)
    ]
    brief, _ = _quality_selection(make_intent_spec(theme), *packets, budgets=[90, 0])
    full, _ = _quality_selection(make_intent_spec(theme), *packets, budgets=[270, 0])
    assert len(brief.composition_candidate_ids()) == 1
    assert len(full.composition_candidate_ids()) == 3
    kyoto = _quality_packet("kyoto_visit", longitude=135.77)
    kyoto = kyoto.model_copy(
        update={
            "candidates": [
                kyoto.candidates[0].model_copy(
                    update={"destination_id": "destination_kyoto"}
                )
            ]
        }
    )
    multi_city, _ = _quality_selection(
        make_intent_spec(theme),
        *packets,
        kyoto,
        budgets=[90, 270],
        destinations=["destination_tokyo", "destination_kyoto"],
    )
    assert "kyoto_visit" in multi_city.composition_candidate_ids()
    assert len(multi_city.composition_candidate_ids()) == 2

    required = theme.model_copy(
        update={"kind": IntentKind.MUST_INCLUDE, "strength": IntentStrength.HARD}
    )
    required_plan, _ = _quality_selection(make_intent_spec(required), packets[0], budgets=[0])
    assert required_plan.composition_candidate_ids() == {"candidate_0"}
    assert required_plan.entries[0].role is CandidateSelectionRole.REQUIRED_PRIMARY

    unavailable, _ = _quality_selection(make_intent_spec(theme), packets[0], budgets=[0])
    assert unavailable.composition_candidate_ids() == set()
    assert unavailable.uncovered_intent_ids == ["intent_theme"]


def test_selection_respects_explicit_counts_and_does_not_duplicate_places():
    quantity = make_research_intent(
        "intent_count", "one visit", kind=IntentKind.QUANTITY
    ).model_copy(
        update={
            "value": CountIntentValue(operator="exactly", count=1, unit="trip"),
            "strength": IntentStrength.HARD,
        }
    )
    first = _quality_packet("a_museum", longitude=139.760)
    duplicate = _quality_packet("b_duplicate", longitude=139.760)
    duplicate = duplicate.model_copy(
        update={
            "candidates": [
                duplicate.candidates[0].model_copy(
                    update={"place_id": first.candidates[0].place_id}
                )
            ]
        }
    )
    distinct = _quality_packet("c_museum", longitude=139.761)
    plan, _ = _quality_selection(
        make_intent_spec(quantity), first, duplicate, distinct, budgets=[500]
    )
    assert len(plan.composition_candidate_ids()) == 1
    plan, _ = _quality_selection(make_intent_spec(), first, duplicate, distinct)
    assert plan.composition_candidate_ids() == {"a_museum", "c_museum"}
