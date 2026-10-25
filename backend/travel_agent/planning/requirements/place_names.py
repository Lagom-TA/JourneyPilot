"""Planning requirements place names."""

from __future__ import annotations

from typing import Mapping
from typing import Optional


CONTROLLED_DESTINATION_ANCHOR_PREFIX = "controlled_trip_identity.destinations."


def controlled_public_place_name(value: Mapping) -> Optional[str]:
    """Return the public place name carried by a controlled-identity anchor value.

    ``None`` when the value carries no usable name; callers decide whether that is
    tolerable (composition falls back to naming a Day by its own places) or fatal
    (the projection refuses to publish).
    """

    name = str(value.get("name") or "").strip()
    return name or None
