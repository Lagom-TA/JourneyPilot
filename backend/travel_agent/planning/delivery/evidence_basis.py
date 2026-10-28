"""交付证据基础。"""

from __future__ import annotations

from dataclasses import dataclass
from travel_agent.planning.itinerary.models import StructuredItineraryV2
from travel_agent.planning.itinerary.models import TransportLeg
from travel_agent.planning.references import EntityType
from travel_agent.planning.transport import TransportMode
from typing import Dict
from typing import Mapping
from typing import Optional


CITED_SOURCE = "cited_source"


PUBLIC_REFERENCE = "public_reference"


REFERENCE_SERVICE = "reference_service"


PUBLIC_REFERENCE_LABEL = "公开资料整理"


REFERENCE_SERVICE_LABEL = "参考班次"


_BASIS_BY_LINEAGE_KIND = {
    "candidate_entity": CITED_SOURCE,
    "authored_entity": PUBLIC_REFERENCE,
    "reference_entity": REFERENCE_SERVICE,
}


LINEAGE_BEARING_COLLECTIONS = (
    ("visit_stops", EntityType.VISIT_STOP, "item_id"),
    ("dining_stops", EntityType.DINING_STOP, "item_id"),
    ("lodging_stays", EntityType.LODGING_STAY, "stay_id"),
    ("transport_legs", EntityType.TRANSPORT_LEG, "transport_leg_id"),
)


MICRO_TRANSPORT_MAX_DURATION_MINUTES = 10


MICRO_TRANSPORT_MAX_DISTANCE_METERS = 800


class PublicProjectionContractViolation(RuntimeError):
    """公开展示面遇到自身契约禁止的 Bundle 结构。"""


def is_micro_transport_leg(leg: TransportLeg) -> bool:
    """判断交通段是否只是短接驳而非计划中的移动。"""

    return (
        leg.transport_class == "flexible"
        and leg.route_status == "ready"
        and leg.selected_mode is TransportMode.WALK
        and leg.duration_minutes is not None
        and leg.duration_minutes <= MICRO_TRANSPORT_MAX_DURATION_MINUTES
        and leg.distance_meters is not None
        and leg.distance_meters <= MICRO_TRANSPORT_MAX_DISTANCE_METERS
        and (leg.total_cost_cny is None or leg.total_cost_cny == 0)
        and leg.transfer_count == 0
        and leg.booking_status == "not_required"
    )


@dataclass(frozen=True)
class EvidenceBasisView:
    """一份行程的证据基础，各展示面共用同一结果。"""

    basis_by_entity: Mapping[tuple[EntityType, str], str]
    micro_transport_leg_ids: frozenset[str]

    @classmethod
    def from_itinerary(cls, itinerary: StructuredItineraryV2) -> "EvidenceBasisView":
        basis: Dict[tuple[EntityType, str], str] = {}
        for collection, entity_type, id_field in LINEAGE_BEARING_COLLECTIONS:
            for entity in getattr(itinerary, collection):
                basis[(entity_type, getattr(entity, id_field))] = (
                    _BASIS_BY_LINEAGE_KIND[entity.lineage.lineage_kind]
                )
        return cls(
            basis_by_entity=basis,
            micro_transport_leg_ids=frozenset(
                leg.transport_leg_id
                for leg in itinerary.transport_legs
                if is_micro_transport_leg(leg)
            ),
        )

    def basis_for(self, entity_type: EntityType, entity_id: str) -> str:
        """读取实体的证据基础；无法归属时直接报错。

        ``DeliveryBundle`` 已要求每个报告条目引用行程实体，查不到说明载荷违反
        自身契约。用空值或猜测值发布会让模型写入的条目看似有来源，因此直接抛错。
        """

        basis = self.basis_by_entity.get((entity_type, entity_id))
        if basis is None:
            raise PublicProjectionContractViolation(
                "public projection cannot state an evidence basis for "
                f"{entity_type.value}/{entity_id}: it is absent from the canonical itinerary"
            )
        return basis

    def stated_basis_for(
        self, entity_type: EntityType, entity_id: str
    ) -> Optional[str]:
        """展示面应写出的证据基础；返回 ``None`` 表示不展示。

        只有两类实体不展示：custom block 是旅行者自己的安排，微型接驳是地点
        之间的连接而非关于某个地点的断言。
        """

        if entity_type is EntityType.CUSTOM_BLOCK:
            return None
        if (
            entity_type is EntityType.TRANSPORT_LEG
            and entity_id in self.micro_transport_leg_ids
        ):
            return None
        return self.basis_for(entity_type, entity_id)
