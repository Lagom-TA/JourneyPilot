"""Planning requirements constraint applicability."""

from __future__ import annotations

from typing import Mapping


def _scoped_active_constraints(
    constraint_pack: Mapping[str, object] | None,
    *,
    worker_kind: str | None,
) -> list[Mapping[str, object]]:
    if not isinstance(constraint_pack, Mapping):
        return []
    items = constraint_pack.get("hard_constraints") or []
    if not isinstance(items, list):
        return []
    scoped: list[Mapping[str, object]] = []
    for item in items:
        if not isinstance(item, Mapping) or item.get("status") != "active":
            continue
        scoped_workers = item.get("candidate_worker_kinds")
        if not isinstance(scoped_workers, list):
            continue
        if worker_kind is not None and worker_kind not in scoped_workers:
            continue
        constraint_id = str(item.get("constraint_id") or "").strip()
        if not constraint_id:
            continue
        scoped.append(item)
    return scoped


def active_hard_constraint_ids(
    constraint_pack: Mapping[str, object] | None,
    *,
    worker_kind: str | None = None,
) -> tuple[str, ...]:
    """Return the active hard constraints applicable to one worker domain."""

    identifiers: list[str] = []
    for item in _scoped_active_constraints(constraint_pack, worker_kind=worker_kind):
        constraint_id = str(item.get("constraint_id") or "").strip()
        if constraint_id and constraint_id not in identifiers:
            identifiers.append(constraint_id)
    return tuple(identifiers)


def active_hard_constraints(
    constraint_pack: Mapping[str, object] | None,
    *,
    worker_kind: str,
) -> tuple[Mapping[str, object], ...]:
    """Return the canonical candidate-local hard payload for one worker."""

    return tuple(_scoped_active_constraints(constraint_pack, worker_kind=worker_kind))
