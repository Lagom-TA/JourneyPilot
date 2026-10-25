"""Planning delivery projection errors."""

from __future__ import annotations


class DeliveryProjectionError(ValueError):
    """Raised when immutable v2 facts cannot produce a truthful projection."""
