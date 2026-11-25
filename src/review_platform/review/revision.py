"""Reviewer-correction (revision) window: manager return-for-revision and reviewer reopen.

A manager may return a submitted assignment to its reviewer for correction while the review unit is
still ``in_review`` (fewer than ``required_reviews`` submissions), keeping this correction window
separate from adjudication. The reviewer then reopens the returned assignment back to editable
``claimed`` state and resubmits through the existing draft/submit path. Both transitions are
optimistic-concurrency guarded (``If-Match``), idempotent, and audited; prior submitted revisions
are retained, so no reviewer work is lost.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal, now_utc
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.review.base import LEASE_SECONDS, ReviewServiceBase
from review_platform.review.models import Assignment, ReviewUnit
from review_platform.review.projections import (
    assignment_lease_response,
    assignment_revision_response,
)
from review_platform.review.schemas import (
    AssignmentLeaseResponse,
    AssignmentRevisionRequestInput,
    AssignmentRevisionRequestResponse,
)
from review_platform.review.state_machine import (
    validate_revision_reopen,
    validate_revision_request,
)


class ReviewRevisionMixin(ReviewServiceBase):
    def request_revision(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal,
        body: AssignmentRevisionRequestInput,
        expected_version: int,
        idempotency_key: str,
        request_id: str,
    ) -> AssignmentRevisionRequestResponse:
        """Return a submitted assignment to its reviewer for correction — campaign_manager only.

        Allowed only while the review unit is still ``in_review`` (fewer than ``required_reviews``
        submissions), so a unit that has advanced to adjudication or been resolved cannot have a
        submission pulled back.
        """

        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        operation = f"review.request_revision.{assignment_id}"
        request_digest = self._request_digest(
            {"reason": body.reason, "expected_version": expected_version}
        )
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
        )
        if record is not None:
            replayed = AssignmentRevisionRequestResponse.model_validate(record.response_json)
            return replayed.model_copy(update={"replayed": True})
        assignment = session.scalar(
            select(Assignment)
            .where(Assignment.tenant_id == tenant_id, Assignment.id == assignment_id)
            .with_for_update()
        )
        if assignment is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        reason = validate_revision_request(
            assignment.status,
            body.reason,
            expected_version_matches=assignment.lock_version == expected_version,
        )
        unit = session.scalar(
            select(ReviewUnit)
            .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.id == assignment.review_unit_id)
            .with_for_update()
        )
        if unit is None or unit.status != "in_review":
            raise APIError(
                409,
                "assignment_revision_not_requestable",
                "Revision not requestable",
                "The review unit has advanced beyond review and cannot be returned for revision.",
            )
        assignment.status = "revision_requested"
        assignment.revision_requested_at = now_utc()
        assignment.revision_requested_by = principal.user.id
        assignment.revision_reason = reason
        assignment.lock_version += 1
        session.flush()
        response = assignment_revision_response(assignment)
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="review.revision_requested",
            object_type="assignment",
            object_id=str(assignment.id),
            request_id=request_id,
            payload={
                "review_unit_id": str(assignment.review_unit_id),
                "reviewer_id": str(assignment.reviewer_id),
            },
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

    def reopen(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal,
        expected_version: int,
        idempotency_key: str,
        request_id: str,
    ) -> AssignmentLeaseResponse:
        """Reopen an assignment a manager returned for correction back to editable ``claimed``.

        A fresh lease is started and ``lock_version`` bumped so a stale ``If-Match`` fails
        safely.     The unit slot stayed reserved for this reviewer throughout, so
        reopening never     over-allocates the unit; the reviewer then resubmits through
        the existing draft/submit path."""

        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        operation = f"review.reopen.{assignment_id}"
        request_digest = self._request_digest(
            {"assignment_id": str(assignment_id), "expected_version": expected_version}
        )
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
        validate_revision_reopen(
            assignment.status,
            expected_version_matches=assignment.lock_version == expected_version,
        )
        assignment.status = "claimed"
        assignment.lease_expires_at = now_utc() + timedelta(seconds=LEASE_SECONDS)
        assignment.lock_version += 1
        session.flush()
        response = assignment_lease_response(assignment)
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="review.revision_reopened",
            object_type="assignment",
            object_id=str(assignment.id),
            request_id=request_id,
            payload={"review_unit_id": str(assignment.review_unit_id)},
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
