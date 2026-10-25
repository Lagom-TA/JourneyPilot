"""Planning delivery evidence basis."""

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


PUBLIC_REFERENCE_HINT = "由规划模型依据公开资料写入，未附来源链接"


REFERENCE_SERVICE_LABEL = "参考班次"


REFERENCE_SERVICE_HINT = "来自供应商的真实班次，但未对你的出行日期确认"


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
    """A public surface found a Bundle shape its own contract forbids."""


def is_micro_transport_leg(leg: TransportLeg) -> bool:
    """Whether a leg is a short connector rather than a planned movement."""

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
    """One itinerary's evidence bases, derived once and read by every surface."""

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
        """Read one entity's basis, failing closed on an unattributable entity.

        ``DeliveryBundle`` already requires every report block to reference an
        itinerary entity, so a miss here means the payload contradicts its own
        contract.  Publishing it with a blank or guessed basis would let a
        model-authored entry pass as sourced, so the surface names it instead.
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
        """The basis a rendered surface should state, or ``None`` to stay silent.

        Only two entities stay silent, matching ``evidenceBasisForEntity`` on the
        client: a custom block is the traveller's own arrangement, and a micro
        connector is a link between places rather than a claim about one.
        """

        if entity_type is EntityType.CUSTOM_BLOCK:
            return None
        if (
            entity_type is EntityType.TRANSPORT_LEG
            and entity_id in self.micro_transport_leg_ids
        ):
            return None
        return self.basis_for(entity_type, entity_id)
