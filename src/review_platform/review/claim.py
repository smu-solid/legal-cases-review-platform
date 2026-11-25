"""Reviewer claim of a review unit (targeted or next-available), lease, and idempotent replay."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal, now_utc
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.review.assignment_status import RELEASED_STATUS, assignment_is_live
from review_platform.review.base import LEASE_SECONDS, ReviewServiceBase
from review_platform.review.models import AllocationRun, Assignment, ReviewSubject, ReviewUnit
from review_platform.review.projections import assignment_claim_response
from review_platform.review.schemas import ClaimRequest, ClaimResponse


class ReviewClaimMixin(ReviewServiceBase):
    def claim(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        body: ClaimRequest,
        idempotency_key: str,
        request_id: str,
    ) -> ClaimResponse:
        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        request_digest = self._request_digest(body.model_dump(mode="json"))
        operation = "review.claim"
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
        )
        if record is not None:
            response = ClaimResponse.model_validate(record.response_json)
            return response.model_copy(update={"replayed": True})
        if body.review_unit_id is not None:
            existing_assignment_row = session.execute(
                select(Assignment, ReviewUnit, ReviewSubject)
                .join(
                    ReviewUnit,
                    (ReviewUnit.tenant_id == Assignment.tenant_id)
                    & (ReviewUnit.id == Assignment.review_unit_id),
                )
                .join(
                    ReviewSubject,
                    (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
                    & (ReviewSubject.id == ReviewUnit.review_subject_id),
                )
                .where(
                    Assignment.tenant_id == tenant_id,
                    Assignment.review_unit_id == body.review_unit_id,
                    Assignment.reviewer_id == principal.user.id,
                )
                .with_for_update()
            ).first()
            # A ``released`` row is not an assignment the reviewer holds -- it is the trace of one
            # that was taken away. Short-circuiting on it made release terminal: the reviewer could
            # never take the unit again even once its capacity was free again, and the pool query
            # hid it from them too (``~own_assignment`` below). Skipping this block sends a
            # re-claim through the ordinary eligibility rules (unit still open, capacity free,
            # campaign not allocation-published), which then revives the row in place -- only one
            # row per (unit, reviewer) may exist (``uq_assignment_reviewer``).
            if (
                existing_assignment_row is not None
                and existing_assignment_row[0].status != RELEASED_STATUS
            ):
                existing_assignment, existing_unit, existing_subject = existing_assignment_row
                if existing_assignment.status != "claimed":
                    raise APIError(
                        409,
                        "assignment_not_claimable",
                        "Assignment not claimable",
                        "The reviewer already has a non-claimable assignment for this review unit.",
                    )
                if (
                    body.subject_kind is not None
                    and existing_subject.subject_kind != body.subject_kind
                ):
                    raise APIError(
                        409,
                        "no_review_work_available",
                        "No review work available",
                        "No eligible review unit is available.",
                    )
                if body.review_kind is not None and existing_unit.review_kind != body.review_kind:
                    raise APIError(
                        409,
                        "no_review_work_available",
                        "No review work available",
                        "No eligible review unit is available.",
                    )
                if body.campaign_id is not None and existing_unit.campaign_id != body.campaign_id:
                    raise APIError(
                        409,
                        "no_review_work_available",
                        "No review work available",
                        "No eligible review unit is available.",
                    )
                response = assignment_claim_response(existing_assignment)
                self._store_idempotency(
                    session,
                    tenant_id=tenant_id,
                    user_id=principal.user.id,
                    operation=operation,
                    key=idempotency_key,
                    request_digest=request_digest,
                    response=response.model_dump(mode="json"),
                    etag=str(existing_assignment.lock_version),
                )
                return response
        current = now_utc()
        claimed_count = (
            select(func.count())
            .select_from(Assignment)
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.review_unit_id == ReviewUnit.id,
                self._slot_active_clause(current),
            )
            .correlate(ReviewUnit)
            .scalar_subquery()
        )
        own_assignment = (
            select(Assignment.id)
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.review_unit_id == ReviewUnit.id,
                Assignment.reviewer_id == principal.user.id,
                assignment_is_live(),
            )
            .correlate(ReviewUnit)
            .exists()
        )
        published_allocation_campaign = (
            select(AllocationRun.id)
            .where(
                AllocationRun.tenant_id == tenant_id,
                AllocationRun.campaign_id == ReviewUnit.campaign_id,
                AllocationRun.status == "published",
            )
            .correlate(ReviewUnit)
            .exists()
        )
        statement = (
            select(ReviewUnit)
            .join(
                ReviewSubject,
                (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
                & (ReviewSubject.id == ReviewUnit.review_subject_id),
            )
            .where(
                ReviewUnit.tenant_id == tenant_id,
                ReviewUnit.status.in_(("pending", "in_review")),
                claimed_count < ReviewUnit.required_reviews,
                ~own_assignment,
                ~published_allocation_campaign,
            )
            .order_by(ReviewUnit.created_at, ReviewUnit.id)
            .limit(1)
        )
        if body.review_unit_id is not None:
            statement = statement.where(ReviewUnit.id == body.review_unit_id)
        if body.subject_kind is not None:
            statement = statement.where(ReviewSubject.subject_kind == body.subject_kind)
        if body.review_kind is not None:
            statement = statement.where(ReviewUnit.review_kind == body.review_kind)
        if body.campaign_id is not None:
            statement = statement.where(ReviewUnit.campaign_id == body.campaign_id)
        statement = statement.with_for_update(skip_locked=body.review_unit_id is None)
        unit = session.scalar(statement)
        if unit is None:
            raise APIError(
                409,
                "no_review_work_available",
                "No review work available",
                "No eligible review unit is available.",
            )
        existing = session.scalar(
            select(Assignment).where(
                Assignment.tenant_id == tenant_id,
                Assignment.review_unit_id == unit.id,
                Assignment.reviewer_id == principal.user.id,
            )
        )
        # Not a released row (which the block below revives): a genuine duplicate is the
        # locked-query race fallback this has always been.
        if existing is not None and existing.status != RELEASED_STATUS:  # pragma: no cover
            raise APIError(
                409,
                "assignment_exists",
                "Assignment already exists",
                "The reviewer already has an assignment for this review unit.",
            )
        active_count = (
            session.scalar(
                select(func.count())
                .select_from(Assignment)
                .where(
                    Assignment.tenant_id == tenant_id,
                    Assignment.review_unit_id == unit.id,
                    self._slot_active_clause(current),
                )
            )
            or 0
        )
        if active_count >= unit.required_reviews:  # pragma: no cover - locked-query race fallback
            raise APIError(
                409,
                "no_review_work_available",
                "No review work available",
                "No eligible review unit is available.",
            )
        lease_expires_at = now_utc() + timedelta(seconds=LEASE_SECONDS)
        if existing is not None:
            # Reviving the reviewer's own released row: one row per (unit, reviewer) is all the
            # schema allows, and reusing it keeps the assignment id (and any audit trail hanging
            # off it) stable across the release and the re-claim.
            assignment = existing
            assignment.status = "claimed"
            assignment.claimed_at = now_utc()
            assignment.lease_expires_at = lease_expires_at
        else:
            assignment = Assignment(
                tenant_id=tenant_id,
                review_unit_id=unit.id,
                reviewer_id=principal.user.id,
                lease_expires_at=lease_expires_at,
            )
            session.add(assignment)
        unit.status = "in_review"
        unit.lock_version += 1
        session.flush()
        response = assignment_claim_response(assignment)
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="review.assignment_claimed",
            object_type="assignment",
            object_id=str(assignment.id),
            request_id=request_id,
            payload={"review_unit_id": str(unit.id)},
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
