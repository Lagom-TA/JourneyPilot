"""Planning research option availability."""

from __future__ import annotations

from travel_agent.planning.research.candidates import ResearchCandidate
from travel_agent.planning.research.candidates import VisitCandidate


def candidate_option_availability(candidate: ResearchCandidate) -> str:
    """State what a reader still has to check before turning up.

    Dining and lodging candidates carry a supplier's answer about inventory, so
    the option repeats it **verbatim** — including ``"unavailable"``, which
    ``SelectionOption`` then rejects outright.  That refusal is the existing
    behaviour and is left alone: an unusable candidate must not be quietly
    relabelled into a slot a traveller can pick.

    An attraction has no inventory anyone could hold, so the honest question is
    the other one: does it have to be booked ahead.
    """

    if isinstance(candidate, VisitCandidate):
        return "needs_confirmation" if candidate.reservation_required else "confirmed"
    return str(getattr(candidate, "availability_status", "confirmed"))
