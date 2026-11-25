"""Reviewer lease lifecycle: renew an active claim's lease or release the claim back to the pool.

Both actions are idempotent (replay keyed on the assignment) and operate only on the caller's own
assignment under a row lock. Renew extends only the lease deadline and deliberately leaves
``lock_version`` untouched so a background lease refresh never invalidates an in-flight draft's
optimistic-concurrency token; it also restores an already-lapsed lease while the unit still has
capacity for the holder (see ``_expired_lease_slot_available``), refusing only once another
reviewer has taken the freed slot. Release is a terminal transition and bumps ``lock_version``;
when it empties a unit it returns the unit to ``pending`` so the freed capacity is discoverable
again.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal, now_utc
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.review.base import LEASE_SECONDS, ReviewServiceBase
from review_platform.review.models import Assignment, ReviewUnit
from review_platform.review.projections import assignment_lease_response
from review_platform.review.schemas import AssignmentLeaseResponse


class ReviewLifecycleMixin(ReviewServiceBase):
    def renew(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal,
        idempotency_key: str,
        request_id: str,
    ) -> AssignmentLeaseResponse:
        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        operation = f"review.renew.{assignment_id}"
        request_digest = self._request_digest({"assignment_id": str(assignment_id)})
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
        )
        if record is not None:
            replayed = AssignmentLeaseResponse.model_validate(record.response_json)
            return replayed.model_copy(update={"replayed": True})
        assignment = self._own_assignment_for_update(session, tenant_id, assignment_id, principal)
        if assignment.status != "claimed":
            raise APIError(
                409,
                "assignment_not_editable",
                "Assignment not editable",
                "The assignment can no longer be changed.",
            )
        current = now_utc()
        # A lapsed lease is renewable while the unit still has a slot for its holder; it is
        # refused only once another reviewer has claimed the freed capacity. Unconditional
        # refusal here dead-ended allocation-published assignments (whose fixed publish lease
        # nothing renews) the moment that horizon passed.
        if assignment.lease_expires_at <= current and not self._expired_lease_slot_available(
            session, assignment, current
        ):
            raise APIError(
                409,
                "assignment_lease_expired",
                "Assignment lease expired",
                "The assignment lease has expired and cannot be renewed.",
            )
        # Lease-only update: lock_version is intentionally not bumped so an in-flight draft's
        # If-Match token survives a lease renewal.
        assignment.lease_expires_at = current + timedelta(seconds=LEASE_SECONDS)
        session.flush()
        response = assignment_lease_response(assignment)
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="review.assignment_renewed",
            object_type="assignment",
            object_id=str(assignment.id),
            request_id=request_id,
            payload={"lease_expires_at": assignment.lease_expires_at.isoformat()},
            key=self.audit_key,
        )
        self._store_idempotency(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
            response=response.model_dump(mode="json"),
            etag=str(assignment.lock_version),
        )
        return response

    def release(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal,
        idempotency_key: str,
        request_id: str,
    ) -> AssignmentLeaseResponse:
        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        operation = f"review.release.{assignment_id}"
        request_digest = self._request_digest({"assignment_id": str(assignment_id)})
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
        )
        if record is not None:
            replayed = AssignmentLeaseResponse.model_validate(record.response_json)
            return replayed.model_copy(update={"replayed": True})
        assignment = self._own_assignment_for_update(session, tenant_id, assignment_id, principal)
        if assignment.status == "submitted":
            raise APIError(
                409,
                "assignment_not_releasable",
                "Assignment not releasable",
                "A submitted assignment cannot be released.",
            )
        if assignment.status == "claimed":
            assignment.status = "released"
            assignment.lock_version += 1
            session.flush()
            self._free_review_unit(session, assignment)
            append_audit_event(
                session,
                actor_user_id=principal.user.id,
                actor_type="user",
                event_type="review.assignment_released",
                object_type="assignment",
                object_id=str(assignment.id),
                request_id=request_id,
                payload={"review_unit_id": str(assignment.review_unit_id)},
                key=self.audit_key,
            )
        # Releasing an already-released assignment is a safe no-op and returns its current state.
        response = assignment_lease_response(assignment)
        self._store_idempotency(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
            response=response.model_dump(mode="json"),
            etag=str(assignment.lock_version),
        )
        return response

    def _free_review_unit(self, session: Session, assignment: Assignment) -> None:
        """Return a unit to ``pending`` once a release leaves it with no live, slot-holding
        work."""

        unit = session.scalar(
            select(ReviewUnit)
            .where(
                ReviewUnit.tenant_id == assignment.tenant_id,
                ReviewUnit.id == assignment.review_unit_id,
            )
            .with_for_update()
        )
        if unit is None or unit.status != "in_review":  # pragma: no cover - composite FK invariant
            return
        active = (
            session.scalar(
                select(func.count())
                .select_from(Assignment)
                .where(
                    Assignment.tenant_id == assignment.tenant_id,
                    Assignment.review_unit_id == assignment.review_unit_id,
                    self._slot_active_clause(now_utc()),
                )
            )
            or 0
        )
        if active == 0:
            unit.status = "pending"
            unit.lock_version += 1
