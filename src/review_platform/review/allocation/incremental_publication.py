"""Bounded, set-prefetched publication of incremental assignment plans."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from review_platform.auth.service import now_utc
from review_platform.review.allocation.lifecycle import PUBLISHED_ASSIGNMENT_LEASE
from review_platform.review.allocation.plan_persistence import ASSIGNMENT_PLAN_BATCH_SIZE
from review_platform.review.assignment_status import RELEASED_STATUS
from review_platform.review.models import Assignment, AssignmentPlan, IncrementalMovementPlan

INCREMENTAL_PUBLISH_BATCH_SIZE = ASSIGNMENT_PLAN_BATCH_SIZE
AssignmentKey = tuple[uuid.UUID, uuid.UUID]


def publish_incremental_assignments(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    batch_size: int = INCREMENTAL_PUBLISH_BATCH_SIZE,
) -> tuple[list[AssignmentKey], list[AssignmentKey]]:
    """Publish one run with fixed prefetch queries and bounded ORM flushes."""

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    plans = _planned_entries(session, tenant_id=tenant_id, run_id=run_id)
    if not plans:
        return [], []

    sources_by_target = _movement_sources(session, tenant_id=tenant_id, run_id=run_id)
    source_assignments = _source_assignments(session, tenant_id=tenant_id, run_id=run_id)
    target_assignments = _target_assignments(session, tenant_id=tenant_id, run_id=run_id)
    lease_expires = now_utc() + PUBLISHED_ASSIGNMENT_LEASE
    new_pairs: list[AssignmentKey] = []
    moved_pairs: list[AssignmentKey] = []

    for start in range(0, len(plans), batch_size):
        _publish_batch(
            session,
            tenant_id=tenant_id,
            plans=plans[start : start + batch_size],
            lease_expires=lease_expires,
            sources_by_target=sources_by_target,
            source_assignments=source_assignments,
            target_assignments=target_assignments,
            new_pairs=new_pairs,
            moved_pairs=moved_pairs,
        )

    # The caller uses only returned UUID pairs. All writes are flushed, so these prefetched ORM
    # instances can leave the identity map before later publication queries run.
    for assignment in {*source_assignments.values(), *target_assignments.values()}:
        if object_session(assignment) is session:
            session.expunge(assignment)
    return new_pairs, moved_pairs


def _planned_entries(
    session: Session, *, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> list[AssignmentPlan]:
    return list(
        session.scalars(
            select(AssignmentPlan)
            .where(
                AssignmentPlan.tenant_id == tenant_id,
                AssignmentPlan.allocation_run_id == run_id,
                AssignmentPlan.status == "planned",
            )
            .order_by(AssignmentPlan.created_at, AssignmentPlan.id)
        )
    )


def _movement_sources(
    session: Session, *, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> dict[AssignmentKey, tuple[uuid.UUID, ...]]:
    rows = session.execute(
        select(
            IncrementalMovementPlan.subject_id,
            IncrementalMovementPlan.to_reviewer_id,
            IncrementalMovementPlan.from_reviewer_id,
        )
        .where(
            IncrementalMovementPlan.tenant_id == tenant_id,
            IncrementalMovementPlan.allocation_run_id == run_id,
            IncrementalMovementPlan.movement_kind == "moved",
            IncrementalMovementPlan.from_reviewer_id.is_not(None),
        )
        .order_by(IncrementalMovementPlan.created_at, IncrementalMovementPlan.id)
    ).all()
    by_target: dict[AssignmentKey, list[uuid.UUID]] = defaultdict(list)
    for unit_id, target_id, source_id in rows:
        if source_id is not None and source_id not in by_target[(unit_id, target_id)]:
            by_target[(unit_id, target_id)].append(source_id)
    return {key: tuple(source_ids) for key, source_ids in by_target.items()}


def _source_assignments(
    session: Session, *, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> dict[AssignmentKey, Assignment]:
    assignments = session.scalars(
        select(Assignment)
        .join(
            IncrementalMovementPlan,
            (IncrementalMovementPlan.tenant_id == Assignment.tenant_id)
            & (IncrementalMovementPlan.subject_id == Assignment.review_unit_id)
            & (IncrementalMovementPlan.from_reviewer_id == Assignment.reviewer_id),
        )
        .where(
            Assignment.tenant_id == tenant_id,
            IncrementalMovementPlan.tenant_id == tenant_id,
            IncrementalMovementPlan.allocation_run_id == run_id,
            IncrementalMovementPlan.movement_kind == "moved",
            IncrementalMovementPlan.from_reviewer_id.is_not(None),
        )
    ).unique()
    return {(row.review_unit_id, row.reviewer_id): row for row in assignments}


def _target_assignments(
    session: Session, *, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> dict[AssignmentKey, Assignment]:
    assignments = session.scalars(
        select(Assignment)
        .join(
            AssignmentPlan,
            (AssignmentPlan.tenant_id == Assignment.tenant_id)
            & (AssignmentPlan.review_unit_id == Assignment.review_unit_id)
            & (AssignmentPlan.reviewer_id == Assignment.reviewer_id),
        )
        .where(
            Assignment.tenant_id == tenant_id,
            AssignmentPlan.tenant_id == tenant_id,
            AssignmentPlan.allocation_run_id == run_id,
            AssignmentPlan.status == "planned",
        )
    ).unique()
    return {(row.review_unit_id, row.reviewer_id): row for row in assignments}


def _publish_batch(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    plans: Sequence[AssignmentPlan],
    lease_expires: datetime,
    sources_by_target: dict[AssignmentKey, tuple[uuid.UUID, ...]],
    source_assignments: dict[AssignmentKey, Assignment],
    target_assignments: dict[AssignmentKey, Assignment],
    new_pairs: list[AssignmentKey],
    moved_pairs: list[AssignmentKey],
) -> None:
    links: list[tuple[AssignmentPlan, Assignment]] = []
    created: list[Assignment] = []
    for plan in plans:
        target_key = (plan.review_unit_id, plan.reviewer_id)
        movement_kind = (plan.plan_metadata_json or {}).get("movement_kind", "new")
        if movement_kind == "moved":
            # Preserve the existing release-before-target-short-circuit rule. Sources are keyed by
            # this run's exact (unit, target) audit identity, never pooled across other targets.
            for source_id in sources_by_target.get(target_key, ()):
                if source_id == plan.reviewer_id:
                    continue
                source = source_assignments.get((plan.review_unit_id, source_id))
                if source is not None and source.status == "claimed":
                    source.status = RELEASED_STATUS
            moved_pairs.append((plan.reviewer_id, plan.review_unit_id))

        existing = target_assignments.get(target_key)
        if existing is not None:
            _attach_existing(existing, lease_expires)
            links.append((plan, existing))
            continue

        if movement_kind != "moved":
            new_pairs.append((plan.reviewer_id, plan.review_unit_id))
        assignment = Assignment(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            review_unit_id=plan.review_unit_id,
            reviewer_id=plan.reviewer_id,
            status="claimed",
            lease_expires_at=lease_expires,
        )
        created.append(assignment)
        target_assignments[target_key] = assignment
        links.append((plan, assignment))

    # The plan has a composite FK but no ORM relationship to Assignment. Flush assignment state
    # first, then link plans in a second flush: two flushes per bounded batch, never per plan.
    if created:
        session.add_all(created)
    session.flush()
    for plan, assignment in links:
        plan.assignment_id = assignment.id
        plan.status = "published"
    session.flush()
    for assignment in created:
        session.expunge(assignment)
    for plan in plans:
        session.expunge(plan)


def _attach_existing(existing: Assignment, lease_expires: datetime) -> None:
    """Revive a returning reviewer's released row in place without touching live work."""

    if existing.status == RELEASED_STATUS:
        existing.status = "claimed"
        existing.claimed_at = now_utc()
        existing.lease_expires_at = lease_expires
