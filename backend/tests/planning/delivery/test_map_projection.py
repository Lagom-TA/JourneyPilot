"""地图投影只使用真实地点坐标，并在副本上补齐路线端点。"""

from types import SimpleNamespace

from travel_agent.planning.delivery.map_projection import project_map
from travel_agent.planning.delivery.map_projection import project_stored_bundle_map
from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.planning.research.evidence import FactAssertion, FactStoreSnapshot
from travel_agent.planning.transport import (
    TransportEndpoint,
    TransportMode,
    TransportSegment,
)


def _stop(
    item_id,
    name,
    latitude=None,
    longitude=None,
    *,
    fact_assertion_ids=(),
):
    return SimpleNamespace(
        item_id=item_id,
        name=name,
        place_id=f"authored:test:{item_id}",
        latitude=latitude,
        longitude=longitude,
        lineage=SimpleNamespace(fact_assertion_ids=list(fact_assertion_ids)),
    )


def _stay(stay_id, name, *, fact_assertion_ids=()):
    return SimpleNamespace(
        stay_id=stay_id,
        name=name,
        place_id=f"authored:test:{stay_id}",
        lineage=SimpleNamespace(fact_assertion_ids=list(fact_assertion_ids)),
    )


def _coordinate_facts(entity_type, entity_id, latitude, longitude):
    facts = [
        FactAssertion(
            fact_assertion_id=f"fact_{entity_id}_{field_path}",
            entity_ref=EntityRef(entity_type=entity_type, entity_id=entity_id),
            field_path=field_path,
            asserted_value=value,
            criticality="auxiliary",
            status="verified",
        )
        for field_path, value in (
            ("latitude", latitude),
            ("longitude", longitude),
        )
    ]
    return facts, [fact.fact_assertion_id for fact in facts]


def _endpoint(name, place_id=None):
    return TransportEndpoint(name=name, place_id=place_id)


def _leg(leg_id, endpoints, *, route_status="ready"):
    first, middle, last = endpoints
    segments = [
        TransportSegment(
            segment_id=f"segment_{leg_id}_1",
            mode=TransportMode.WALK,
            from_endpoint=_endpoint(first.name, first.place_id),
            to_endpoint=_endpoint(middle.name, middle.place_id),
        ),
        TransportSegment(
            segment_id=f"segment_{leg_id}_2",
            mode=TransportMode.WALK,
            from_endpoint=_endpoint(middle.name, middle.place_id),
            to_endpoint=_endpoint(last.name, last.place_id),
        ),
    ]
    return SimpleNamespace(
        transport_leg_id=leg_id,
        transport_class="flexible",
        selected_mode=TransportMode.WALK,
        route_status=route_status,
        from_endpoint=_endpoint(first.name, first.place_id),
        to_endpoint=_endpoint(last.name, last.place_id),
        segments=segments,
    )


def _workspace(*, dining_stops=(), lodging_stays=(), transport_legs=()):
    return SimpleNamespace(
        workspace_revision=0,
        itinerary=SimpleNamespace(
            visit_stops=[_stop("visit", "景点", 35.0, 139.0)],
            dining_stops=list(dining_stops),
            lodging_stays=list(lodging_stays),
            transport_legs=list(transport_legs),
        ),
    )


def test_stops_without_coordinates_stay_off_the_map():
    workspace = SimpleNamespace(
        workspace_revision=0,
        itinerary=SimpleNamespace(
            visit_stops=[
                _stop("visit_located", "有坐标地点", 35.0, 139.0),
                _stop("visit_unlocated", "无坐标地点"),
            ],
            dining_stops=[],
            lodging_stays=[],
            transport_legs=[],
        ),
    )

    projection = project_map(workspace, FactStoreSnapshot(fact_data_revision=0), [])

    names = [place.name for place in projection.content.places]
    assert names == ["有坐标地点"]


def test_all_place_kinds_use_direct_and_verified_fact_coordinates():
    dining_facts, dining_fact_ids = _coordinate_facts(
        EntityType.DINING_STOP, "dining", 35.1, 139.1
    )
    lodging_facts, lodging_fact_ids = _coordinate_facts(
        EntityType.LODGING_STAY, "lodging", 35.2, 139.2
    )
    workspace = _workspace(
        dining_stops=[
            _stop("dining", "餐厅", fact_assertion_ids=dining_fact_ids)
        ],
        lodging_stays=[
            _stay("lodging", "酒店", fact_assertion_ids=lodging_fact_ids)
        ],
    )
    facts = FactStoreSnapshot(
        fact_data_revision=1,
        fact_assertions=[*dining_facts, *lodging_facts],
    )

    projection = project_map(workspace, facts, [])

    assert {
        place.entity_ref.entity_type: (place.latitude, place.longitude)
        for place in projection.content.places
    } == {
        EntityType.VISIT_STOP: (35.0, 139.0),
        EntityType.DINING_STOP: (35.1, 139.1),
        EntityType.LODGING_STAY: (35.2, 139.2),
    }


def test_ready_route_endpoints_are_hydrated_without_mutating_workspace():
    dining_facts, dining_fact_ids = _coordinate_facts(
        EntityType.DINING_STOP, "dining", 35.1, 139.1
    )
    lodging_facts, lodging_fact_ids = _coordinate_facts(
        EntityType.LODGING_STAY, "lodging", 35.2, 139.2
    )
    visit = _workspace().itinerary.visit_stops[0]
    dining = _stop("dining", "餐厅", fact_assertion_ids=dining_fact_ids)
    lodging = _stay("lodging", "酒店", fact_assertion_ids=lodging_fact_ids)
    leg = _leg(
        "leg_ready",
        (
            _endpoint(visit.name, visit.place_id),
            _endpoint(dining.name, dining.place_id),
            _endpoint(lodging.name, lodging.place_id),
        ),
    )
    workspace = _workspace(
        dining_stops=[dining],
        lodging_stays=[lodging],
        transport_legs=[leg],
    )
    facts = FactStoreSnapshot(
        fact_data_revision=1,
        fact_assertions=[*dining_facts, *lodging_facts],
    )
    original_endpoints = [
        leg.from_endpoint,
        leg.to_endpoint,
        *(
            endpoint
            for segment in leg.segments
            for endpoint in (segment.from_endpoint, segment.to_endpoint)
        ),
    ]

    projection = project_map(workspace, facts, [])

    route = projection.content.routes[0]
    assert (route.from_endpoint.latitude, route.from_endpoint.longitude) == (35.0, 139.0)
    assert (route.to_endpoint.latitude, route.to_endpoint.longitude) == (35.2, 139.2)
    assert [
        (
            segment.from_endpoint.latitude,
            segment.from_endpoint.longitude,
            segment.to_endpoint.latitude,
            segment.to_endpoint.longitude,
        )
        for segment in route.segments
    ] == [
        (35.0, 139.0, 35.1, 139.1),
        (35.1, 139.1, 35.2, 139.2),
    ]
    assert all(
        endpoint.latitude is None and endpoint.longitude is None
        for endpoint in original_endpoints
    )


def test_unknown_or_non_ready_routes_do_not_acquire_coordinates():
    unknown = _endpoint("未知地点", "authored:test:unknown")
    anonymous = _endpoint("无标识地点")
    visit = _workspace().itinerary.visit_stops[0]
    located = _endpoint(visit.name, visit.place_id)
    ready = _leg("leg_ready", (unknown, anonymous, located))
    pending = _leg(
        "leg_pending",
        (unknown, anonymous, located),
        route_status="pending",
    )
    workspace = _workspace(transport_legs=[ready, pending])

    projection = project_map(workspace, FactStoreSnapshot(fact_data_revision=0), [])

    assert [route.entity_ref.entity_id for route in projection.content.routes] == [
        "leg_ready"
    ]
    route = projection.content.routes[0]
    assert route.from_endpoint.latitude is None
    assert route.from_endpoint.longitude is None
    assert route.segments[0].to_endpoint.latitude is None
    assert route.segments[0].to_endpoint.longitude is None
    assert (route.to_endpoint.latitude, route.to_endpoint.longitude) == (35.0, 139.0)
    assert pending.from_endpoint.latitude is None
    assert pending.from_endpoint.longitude is None


def test_stored_bundle_map_is_rebuilt_from_its_snapshots():
    bundle = SimpleNamespace(
        workspace=_workspace(),
        fact_snapshot=FactStoreSnapshot(fact_data_revision=0),
        report_projection=SimpleNamespace(citations=[]),
    )

    projection = project_stored_bundle_map(bundle)

    assert [(place.name, place.latitude, place.longitude) for place in projection.content.places] == [
        ("景点", 35.0, 139.0)
    ]
