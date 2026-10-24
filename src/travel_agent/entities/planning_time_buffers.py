"""Explicit planning allowances; these are not provider boarding deadlines."""


def planned_boarding_buffer_minutes(mode: object) -> int:
    """Allow 90 minutes before flights and 30 before other long-distance legs.

    This conservative default must be disclosed as a planning assumption. A
    published operator deadline or a user's larger allowance still takes priority.
    The provider's actual departure timestamp is never changed.
    """
    return 90 if str(getattr(mode, "value", mode)) == "flight" else 30


def planned_alighting_buffer_minutes(mode: object) -> int:
    """Reserve 45 minutes after flights, 15 after other long-distance arrivals.

    This planning allowance covers getting off and leaving the terminal before
    the separately measured local route starts; it is not a provider guarantee.
    """
    return 45 if str(getattr(mode, "value", mode)) == "flight" else 15
