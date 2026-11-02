from types import SimpleNamespace

import pytest

from travel_agent.planning.delivery.citation_projection import project_public_citations
from travel_agent.planning.delivery.projection_errors import DeliveryProjectionError
from travel_agent.planning.references import EntityRef, EntityType
from travel_agent.planning.research.evidence import FactAssertion, FactStoreSnapshot


def _project_fact(status, value):
    ref = EntityRef(entity_type=EntityType.VISIT_STOP, entity_id="visit-1")
    fact = FactAssertion(
        fact_assertion_id="hours", entity_ref=ref, field_path="opening_window",
        asserted_value=value, criticality="execution_critical", status=status,
    )
    stop = SimpleNamespace(item_id="visit-1", lineage=SimpleNamespace(fact_assertion_ids=["hours"]))
    itinerary = SimpleNamespace(visit_stops=[stop], dining_stops=[], lodging_stays=[], transport_legs=[])
    workspace = SimpleNamespace(itinerary=itinerary, selection_slots=[])
    facts = FactStoreSnapshot(fact_data_revision=0, fact_assertions=[fact])
    return project_public_citations(workspace, facts, SimpleNamespace(days=[]))


def test_missing_fact_without_value_does_not_block_delivery_or_create_citation():
    assert _project_fact("missing", None) == []


@pytest.mark.parametrize(("status", "value"), [("verified", "09:00–17:00"), ("missing", "09:00–17:00")])
def test_unsourced_value_still_rejects_delivery(status, value):
    with pytest.raises(DeliveryProjectionError, match="no public source"):
        _project_fact(status, value)
