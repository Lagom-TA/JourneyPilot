"""Integrations rail errors."""

from __future__ import annotations


class Rail12306Error(RuntimeError):
    """Any failure that must not be reported as 'no trains found'."""


class StationNotFoundError(Rail12306Error):
    """A station name or telecode is absent from the committed snapshot."""


class QueryRefusedError(Rail12306Error):
    """12306 refused the request: redirect, stale path, or unusable body."""
