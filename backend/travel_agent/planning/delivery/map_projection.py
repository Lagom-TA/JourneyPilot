"""交付地图投影。"""

from __future__ import annotations

from travel_agent.planning.delivery.citation_projection import _citation_lookup
from travel_agent.planning.delivery.projections import MapPlaceProjection
from travel_agent.planning.delivery.projections import MapProjection
from travel_agent.planning.delivery.projections import MapProjectionContent
from travel_agent.planning.delivery.projections import MapRouteProjection
from travel_agent.planning.delivery.projections import PublicCitationProjection
from travel_agent.planning.itinerary.dispersion import entity_coordinates
from travel_agent.planning.references import EntityRef
from travel_agent.planning.references import EntityType
from travel_agent.planning.research.evidence import FactStoreSnapshot
from travel_agent.planning.transport import TransportEndpoint
from travel_agent.planning.workspace import TripWorkspaceV2
from typing import Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from travel_agent.planning.delivery.bundle import DeliveryBundle


def _hydrate_endpoint(
    endpoint: TransportEndpoint,
    coordinate_index: dict[str, tuple[float, float]],
) -> TransportEndpoint:
    """只用同 place_id 停留点的真实坐标补齐端点。"""
    if endpoint.place_id is None or (
        endpoint.latitude is not None and endpoint.longitude is not None
    ):
        return endpoint
    coordinates = coordinate_index.get(endpoint.place_id)
    if coordinates is None:
        return endpoint
    latitude, longitude = coordinates
    update = {}
    if endpoint.latitude is None:
        update["latitude"] = latitude
    if endpoint.longitude is None:
        update["longitude"] = longitude
    return endpoint.model_copy(update=update)


def project_map(
    workspace: TripWorkspaceV2,
    facts: FactStoreSnapshot,
    citations: Sequence[PublicCitationProjection],
) -> MapProjection:
    _by_fact, by_entity = _citation_lookup(citations)
    fact_index = {fact.fact_assertion_id: fact for fact in facts.fact_assertions}
    itinerary = workspace.itinerary
    places: list[MapPlaceProjection] = []
    coordinate_index: dict[str, tuple[float, float]] = {}
    for entity, entity_type, entity_id, name, place_id in [
        *[
            (item, EntityType.VISIT_STOP, item.item_id, item.name, item.place_id)
            for item in itinerary.visit_stops
        ],
        *[
            (item, EntityType.DINING_STOP, item.item_id, item.name, item.place_id)
            for item in itinerary.dining_stops
        ],
        *[
            (item, EntityType.LODGING_STAY, item.stay_id, item.name, item.place_id)
            for item in itinerary.lodging_stays
        ],
    ]:
        latitude, longitude = entity_coordinates(entity, fact_index)
        if latitude is None or longitude is None:
            # 没有坐标的条目仍留在行程正文里，只是无法放到地图上。
            continue
        coordinate_index.setdefault(place_id, (latitude, longitude))
        places.append(
            MapPlaceProjection(
                entity_ref=EntityRef(entity_type=entity_type, entity_id=entity_id),
                name=name,
                place_id=place_id,
                latitude=latitude,
                longitude=longitude,
                citation_ids=by_entity.get(entity_id, []),
            )
        )
    routes: list[MapRouteProjection] = []
    for leg in itinerary.transport_legs:
        if leg.route_status != "ready":
            continue
        segments = [
            segment.model_copy(
                update={
                    "from_endpoint": _hydrate_endpoint(
                        segment.from_endpoint, coordinate_index
                    ),
                    "to_endpoint": _hydrate_endpoint(
                        segment.to_endpoint, coordinate_index
                    ),
                }
            )
            for segment in leg.segments
        ]
        routes.append(
            MapRouteProjection(
                entity_ref=EntityRef(
                    entity_type=EntityType.TRANSPORT_LEG, entity_id=leg.transport_leg_id
                ),
                transport_class=leg.transport_class,
                selected_mode=leg.selected_mode,
                route_status=leg.route_status,
                from_endpoint=_hydrate_endpoint(leg.from_endpoint, coordinate_index),
                to_endpoint=_hydrate_endpoint(leg.to_endpoint, coordinate_index),
                segments=segments,
                citation_ids=by_entity.get(leg.transport_leg_id, []),
            )
        )
    return MapProjection(
        source_workspace_revision=workspace.workspace_revision,
        content=MapProjectionContent(places=places, routes=routes),
    )


def project_stored_bundle_map(bundle: "DeliveryBundle") -> MapProjection:
    """按持久化快照重建读取时的地图投影，不改写历史记录。"""
    return project_map(
        bundle.workspace,
        bundle.fact_snapshot,
        bundle.report_projection.citations,
    )
