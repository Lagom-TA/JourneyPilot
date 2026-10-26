"""地图投影：无坐标条目不落图，有坐标条目正常落图。"""

from types import SimpleNamespace

from travel_agent.planning.delivery.map_projection import project_map
from travel_agent.planning.research.evidence import FactStoreSnapshot


def _stop(item_id, name, latitude=None, longitude=None):
    return SimpleNamespace(
        item_id=item_id,
        name=name,
        place_id=f"authored:test:{item_id}",
        latitude=latitude,
        longitude=longitude,
        lineage=SimpleNamespace(fact_assertion_ids=[]),
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
