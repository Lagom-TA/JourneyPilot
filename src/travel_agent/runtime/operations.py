from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Optional
from .context import (
    ModelWindow,
    current_model_window,
    current_node,
    current_run_deadline,
)
from .cancellation import check_cancel_requested
from .deadlines import DeadlineObservation, observe_run_deadline


class ModelWindowClosed(RuntimeError):
    """A model/provider/tool call attempted after its own window's cutoff.

    This is intentionally distinct from :class:`RunCancelled`: the user did
    not cancel the TripRun, so callers must converge through deterministic
    closeout rather than emit a cancelled terminal state.
    """

    def __init__(
        self,
        operation: str,
        observation: DeadlineObservation,
        window: ModelWindow,
    ) -> None:
        self.operation = operation
        self.observation = observation
        self.window = window
        super().__init__(
            f"{window} window closed before {operation} "
            f"(elapsed={observation.elapsed_seconds:.3f}s)"
        )


class DeliveryDeadlineExceeded(RuntimeError):
    """A delivery-only operation crossed the durable eight-minute deadline."""

    def __init__(self, operation: str, observation: DeadlineObservation) -> None:
        self.operation = operation
        self.observation = observation
        super().__init__(
            f"delivery deadline exceeded before {operation} "
            f"(elapsed={observation.elapsed_seconds:.3f}s)"
        )


def observe_current_run_deadline() -> tuple[
    Optional[Any], Optional[DeadlineObservation]
]:
    """Observe the active durable deadline without resetting its budget."""

    deadline = current_run_deadline.get()
    if deadline is None:
        return None, None
    observed, observation = observe_run_deadline(deadline)
    current_run_deadline.set(observed)
    return observed, observation


def remaining_model_seconds(operation: str) -> Optional[float]:
    """Return this context's model budget, or reject a new call.

    The window comes from :data:`current_model_window`: research calls must
    finish by its closeout, itinerary composition by its own later one.  Either
    way the interval past that boundary is excluded — a call may start only
    while it can still finish inside its window, and what the composition
    window leaves belongs to deterministic projection, validation and
    persistence.

    The *seconds* come from the run's own sealed snapshot, never from this
    process's policy defaults.  The snapshot is the cross-process source of
    truth, so how much budget a call gets must be decided by the same numbers
    that decide which phase the run is in: a later ``run_deadline`` change may
    neither fund an in-flight run past the closeout it was audited against nor
    cut short one whose snapshot still funds it.
    """

    check_cancel_requested(current_node.get())
    deadline, observation = observe_current_run_deadline()
    if observation is None or deadline is None:
        return None
    window = current_model_window.get()
    if window == "composition":
        window_seconds = deadline.composition_seconds
        closed = observation.composition_closed
    else:
        window_seconds = deadline.closeout_seconds
        closed = observation.research_closed
    remaining = max(0.0, window_seconds - observation.elapsed_seconds)
    if closed or remaining <= 0:
        raise ModelWindowClosed(operation, observation, window)
    return remaining


def remaining_delivery_seconds(operation: str) -> Optional[float]:
    """Return the shared finalization budget, or reject post-deadline work.

    ``observation.remaining_seconds`` already *is* that budget, measured against
    the delivery deadline embedded in the run's own snapshot — for the same
    reason as :func:`remaining_model_seconds`.
    """

    check_cancel_requested(current_node.get())
    _deadline, observation = observe_current_run_deadline()
    if observation is None:
        return None
    remaining = observation.remaining_seconds
    if observation.phase == "expired" or remaining <= 0:
        raise DeliveryDeadlineExceeded(operation, observation)
    return remaining


async def await_model_operation(awaitable: Awaitable[Any], *, operation: str) -> Any:
    """Await one external model/provider operation within its own window."""

    try:
        remaining = remaining_model_seconds(operation)
    except BaseException:
        # Call sites naturally construct the coroutine before passing it here.
        # Closing an unstarted coroutine avoids an unawaited-coroutine warning
        # when the deadline rejects the operation synchronously.
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise
    if remaining is None:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout=remaining)
    except asyncio.TimeoutError as exc:
        _deadline, observation = observe_current_run_deadline()
        if observation is None:  # pragma: no cover - defensive context reset
            raise
        raise ModelWindowClosed(
            operation, observation, current_model_window.get()
        ) from exc


async def await_delivery_operation(awaitable: Awaitable[Any], *, operation: str) -> Any:
    """Await one finalization operation within the common eight-minute cap."""

    try:
        remaining = remaining_delivery_seconds(operation)
    except BaseException:
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise
    if remaining is None:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout=remaining)
    except asyncio.TimeoutError as exc:
        _deadline, observation = observe_current_run_deadline()
        if observation is None:  # pragma: no cover - defensive context reset
            raise
        raise DeliveryDeadlineExceeded(operation, observation) from exc
