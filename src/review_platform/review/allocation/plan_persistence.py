"""Bounded ORM persistence for allocation assignment plans."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from review_platform.review.models import AssignmentPlan

ASSIGNMENT_PLAN_BATCH_SIZE = 5_000


def persist_assignment_plans(
    session: Session,
    plans: Iterable[AssignmentPlan],
    *,
    batch_size: int = ASSIGNMENT_PLAN_BATCH_SIZE,
) -> int:
    """Flush new plans in bounded ORM batches without ending the outer transaction.

    Callers do not retain or reuse the plan instances: publication and inspection reload them by
    allocation-run ID. Expunging each completed batch therefore keeps the session identity map
    bounded without changing any durable state or transaction boundary.
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    batch: list[AssignmentPlan] = []
    persisted_count = 0
    for plan in plans:
        batch.append(plan)
        if len(batch) == batch_size:
            _flush_plan_batch(session, batch)
            persisted_count += len(batch)
            batch.clear()

    if batch:
        _flush_plan_batch(session, batch)
        persisted_count += len(batch)
    elif persisted_count == 0:
        # Preserve the writers' previous final-flush guarantee even for a no-op plan. Other ORM
        # rows belonging to the run (pool members or movement audit rows) may still be pending.
        session.flush()
    return persisted_count


def _flush_plan_batch(session: Session, batch: list[AssignmentPlan]) -> None:
    session.add_all(tuple(batch))
    session.flush()
    for plan in batch:
        session.expunge(plan)
