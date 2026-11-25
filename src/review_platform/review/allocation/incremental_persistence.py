"""Bounded ORM persistence for incremental-allocation audit rows."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from review_platform.review.allocation.plan_persistence import ASSIGNMENT_PLAN_BATCH_SIZE
from review_platform.review.models import IncrementalMovementPlan

INCREMENTAL_MOVEMENT_BATCH_SIZE = ASSIGNMENT_PLAN_BATCH_SIZE


def persist_incremental_movement_plans(
    session: Session,
    movements: Iterable[IncrementalMovementPlan],
    *,
    batch_size: int = INCREMENTAL_MOVEMENT_BATCH_SIZE,
) -> int:
    """Flush movement-audit rows in bounded batches inside the caller's transaction."""

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    batch: list[IncrementalMovementPlan] = []
    persisted_count = 0
    for movement in movements:
        batch.append(movement)
        if len(batch) == batch_size:
            _flush_movement_batch(session, batch)
            persisted_count += len(batch)
            batch.clear()
    if batch:
        _flush_movement_batch(session, batch)
        persisted_count += len(batch)
    return persisted_count


def _flush_movement_batch(session: Session, batch: list[IncrementalMovementPlan]) -> None:
    session.add_all(tuple(batch))
    session.flush()
    for movement in batch:
        session.expunge(movement)
