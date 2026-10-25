"""Planning delivery provider environment."""

from __future__ import annotations

from dataclasses import dataclass
from travel_agent.integrations.provider_environment import SANDBOX_EVIDENCE_NOTE
from travel_agent.integrations.provider_environment import _declared
from typing import Any
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from travel_agent.planning.delivery.bundle import DeliveryBundle


@dataclass(frozen=True)
class ProviderEnvironmentView:
    """One Run's data-environment fact, reduced once and read by every surface.

    Run-level rather than per-leg on purpose.  A traveller does not act
    differently on leg three than on leg one here: the useful statement is "some
    of the transport evidence in this plan came from a test environment, do not
    try to book from it", and a per-leg badge would spend the reader's attention
    on a distinction that changes nothing they do.
    """

    has_sandbox_evidence: bool

    @classmethod
    def from_bundle(cls, bundle: "DeliveryBundle") -> "ProviderEnvironmentView":
        """Reduce over every source record that states an environment.

        Two places can state it and both are read.  ``cache_provenance`` carries
        it for the tools the provider snapshot cache covers — place identity and
        route lookups, never a flight search — and the provider's own sanitized
        payload carries it for everything else.  The two must agree for one
        response, which is what stops the disclosure depending on whether Redis
        happened to hold the answer.  Reading only the first is why this
        disclosure never fired for the case it was built for: a Duffel flight
        search never goes through that cache, so every leg of a sandbox itinerary
        reported production by silence, on screen and in the exported PDF.

        Total by construction: a stored Bundle must reduce, never raise.  The
        obligation to *state* an environment is enforced where the record is
        written, not where a finished plan is read.
        """

        return cls(
            has_sandbox_evidence=any(
                _source_data_environment(source) == "sandbox"
                for source in bundle.fact_snapshot.source_records
            )
        )

    @property
    def sandbox_note(self) -> Optional[str]:
        """The sentence to state, or ``None`` when every response was production."""

        return SANDBOX_EVIDENCE_NOTE if self.has_sandbox_evidence else None


def _source_data_environment(source: Any) -> Optional[str]:
    provenance = getattr(source, "cache_provenance", None)
    if provenance is not None:
        return provenance.data_environment
    return _declared(getattr(source, "snapshot", None))
