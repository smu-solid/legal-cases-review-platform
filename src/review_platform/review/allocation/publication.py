"""Batched publication of initial review-unit assignment plans."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.review.models import Assignment, AssignmentPlan

PUBLISH_BATCH_SIZE = 5_000


def publish_initial_assignments(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    lease_expires_at: datetime,
) -> int:
    """Publish one independent assignment per planned review-unit/reviewer pair.

    Conflict detection is set-based and writes are flushed in bounded batches. A flush is not a
    commit, so the caller's transaction remains atomic across the complete allocation run.
    """

    plans = list(
        session.scalars(
            select(AssignmentPlan).where(
                AssignmentPlan.tenant_id == tenant_id,
                AssignmentPlan.allocation_run_id == run_id,
                AssignmentPlan.status == "planned",
            )
        )
    )
    if not plans:
        return 0
    _reject_existing_assignments(session, tenant_id=tenant_id, run_id=run_id)
    for start in range(0, len(plans), PUBLISH_BATCH_SIZE):
        _publish_batch(
            session,
            tenant_id=tenant_id,
            plans=plans[start : start + PUBLISH_BATCH_SIZE],
            lease_expires_at=lease_expires_at,
        )
    return len(plans)


def _reject_existing_assignments(
    session: Session, *, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> None:
    conflict = session.scalar(
        select(Assignment.id)
        .select_from(AssignmentPlan)
        .join(
            Assignment,
            and_(
                Assignment.tenant_id == AssignmentPlan.tenant_id,
                Assignment.review_unit_id == AssignmentPlan.review_unit_id,
                Assignment.reviewer_id == AssignmentPlan.reviewer_id,
            ),
        )
        .where(
            AssignmentPlan.tenant_id == tenant_id,
            AssignmentPlan.allocation_run_id == run_id,
            AssignmentPlan.status == "planned",
        )
        .limit(1)
    )
    if conflict is not None:
        raise APIError(
            409,
            "allocation_assignment_conflict",
            "Allocation assignment conflict",
            "A reviewer already has an assignment for a planned review unit.",
        )


def _publish_batch(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    plans: Sequence[AssignmentPlan],
    lease_expires_at: datetime,
) -> None:
    assignments_by_plan: list[tuple[AssignmentPlan, Assignment]] = []
    for plan in plans:
        assignment_id = uuid.uuid4()
        assignment = Assignment(
            id=assignment_id,
            tenant_id=tenant_id,
            review_unit_id=plan.review_unit_id,
            reviewer_id=plan.reviewer_id,
            status="claimed",
            lease_expires_at=lease_expires_at,
        )
        assignments_by_plan.append((plan, assignment))
    assignments = [assignment for _, assignment in assignments_by_plan]
    session.add_all(assignments)
    # AssignmentPlan has a composite FK but no ORM relationship to Assignment, so flush the batched
    # inserts before setting that FK. This is two flushes per batch, never per assignment.
    session.flush()
    for plan, assignment in assignments_by_plan:
        plan.assignment_id = assignment.id
        plan.status = "published"
    session.flush()
    for assignment in assignments:
        session.expunge(assignment)
