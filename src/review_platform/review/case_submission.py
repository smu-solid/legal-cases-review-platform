"""Distinct from every review unit's own per-field submit: campaign-level progress must count a
case as complete only once the reviewer confirms from the case-submit preview, not merely
because every owned field happens to already be individually submitted (see
``models.CaseSubmission``'s docstring). This mixin owns that one write path; ``queue.py``
reads ``CaseSubmission`` existence to derive case-grouped progress."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.assignment_status import assignment_is_live
from review_platform.review.citation_submission import ReviewCitationSubmissionMixin
from review_platform.review.models import Assignment, CaseSubmission, ReviewSubject, ReviewUnit
from review_platform.review.proposal_scope import lock_reviewer_case, require_completed_proposals
from review_platform.review.schemas import CaseSubmissionResponse


class ReviewCaseSubmissionMixin(ReviewCitationSubmissionMixin):
    def submit_case(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        assignment_id: uuid.UUID,
        idempotency_key: str,
        request_id: str,
        artifact_store: ArtifactStore | None = None,
    ) -> CaseSubmissionResponse:
        """Reviewer confirmation that a case is done, anchored on any one of its own assignments.

        Requires every review unit the reviewer owns for that case+campaign to already be
        individually submitted (``correction_or_comment_required``-style per-field validation
        already happened at each field's own submit) -- this is the final, explicit "I'm done with
        this case" confirmation, not a shortcut around per-field answers. Idempotent: resubmitting
        an already-submitted case returns the original row (``replayed=True``) rather than erroring
        or creating a second one -- ``CaseSubmission`` is append-only and can never be undone.

        "Owns" means *live* assignments only. A ``released`` row is work a rebalance moved to
        another reviewer: it can never reach ``submitted`` in this reviewer's hands, so counting it
        made the case permanently unsubmittable (422 on every attempt) while the workspace showed
        every field she could actually see as done.
        """

        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        anchor_assignment = session.scalar(
            select(Assignment).where(
                Assignment.tenant_id == tenant_id,
                Assignment.id == assignment_id,
                Assignment.reviewer_id == principal.user.id,
                assignment_is_live(),
            )
        )
        if anchor_assignment is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        anchor_unit = session.scalar(
            select(ReviewUnit).where(
                ReviewUnit.tenant_id == tenant_id,
                ReviewUnit.id == anchor_assignment.review_unit_id,
            )
        )
        if anchor_unit is None:  # pragma: no cover - composite FK invariant
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        anchor_subject = session.scalar(
            select(ReviewSubject).where(
                ReviewSubject.tenant_id == tenant_id,
                ReviewSubject.id == anchor_unit.review_subject_id,
            )
        )
        if anchor_subject is None:  # pragma: no cover - composite FK invariant
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        case_id = anchor_subject.attributes_json.get("snapshot_local_case_external_id") or str(
            anchor_subject.id
        )
        campaign_id = anchor_unit.campaign_id

        lock_reviewer_case(session, tenant_id, campaign_id, str(case_id), principal.user.id)
        existing = session.scalar(
            select(CaseSubmission).where(
                CaseSubmission.tenant_id == tenant_id,
                CaseSubmission.campaign_id == campaign_id,
                CaseSubmission.case_id == case_id,
                CaseSubmission.reviewer_id == principal.user.id,
            )
        )
        if existing is not None:
            return CaseSubmissionResponse(
                case_id=existing.case_id,
                campaign_id=existing.campaign_id,
                submitted_at=existing.submitted_at,
                replayed=True,
            )

        request_digest = self._request_digest(
            {"assignment_id": str(assignment_id), "case_id": case_id}
        )
        operation = "review.case_submit"
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
        )
        if record is not None:
            response = CaseSubmissionResponse.model_validate(record.response_json)
            return response.model_copy(update={"replayed": True})

        owned_rows = session.execute(
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
                Assignment.reviewer_id == principal.user.id,
                ReviewUnit.campaign_id == campaign_id,
                ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext == case_id,
                assignment_is_live(),
            )
        ).all()
        if not owned_rows or any(
            assignment.status != "submitted" for assignment, _unit, _subject in owned_rows
        ):
            raise APIError(
                422,
                "case_not_fully_submitted",
                "Case not fully submitted",
                "Every field assigned to you for this case must be submitted before the case "
                "itself can be submitted.",
            )

        require_completed_proposals(
            session,
            tenant_id,
            campaign_id,
            str(case_id),
            principal.user.id,
        )
        self.check_case_citations(session, tenant_id, assignment_id, principal, artifact_store)
        submission = CaseSubmission(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            case_id=case_id,
            reviewer_id=principal.user.id,
        )
        session.add(submission)
        session.flush()
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="review.case_submitted",
            object_type="case_submission",
            object_id=str(submission.id),
            request_id=request_id,
            payload={"case_id": case_id, "campaign_id": str(campaign_id)},
            key=self.audit_key,
        )
        response = CaseSubmissionResponse(
            case_id=submission.case_id,
            campaign_id=submission.campaign_id,
            submitted_at=submission.submitted_at,
        )
        self._store_idempotency(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
            response=response.model_dump(mode="json"),
        )
        return response
