"""Reviewer submission writes: candidate-comparison annotations and value/provenance answers."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal, now_utc
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.assignment_status import RELEASED_STATUS
from review_platform.review.base import LEASE_SECONDS
from review_platform.review.citation_submission import (
    ReviewCitationSubmissionMixin,
    lock_citation_case,
)
from review_platform.review.item_answer_projection import _item_answer_response
from review_platform.review.models import (
    AnnotationRevision,
    Assignment,
    Candidate,
    EvidenceWindow,
    ReviewItemAnswer,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.projections import revision_response
from review_platform.review.schemas import (
    AnnotationInput,
    AnnotationRevisionResponse,
    ReviewItemAnswerInput,
    ReviewItemAnswerResponse,
)
from review_platform.review.state_machine import validate_annotation, validate_item_answer


def _reject_if_released(assignment: Assignment) -> None:
    """Answer a write to a moved-away assignment with its own code, not the generic refusal.

    ``assignment_not_editable`` is how an *already submitted* field refuses a second write, and the
    workspace reads it as exactly that -- it marks the field done and moves on. A ``released`` row
    (a rebalance moved the unit to another reviewer) answering with the same code therefore painted
    fields the reviewer never answered as submitted, and left her retrying a case submit that could
    not succeed. A distinct code lets the UI say what actually happened.
    """

    if assignment.status == RELEASED_STATUS:
        raise APIError(
            409,
            "released_assignment",
            "Assignment reassigned",
            "This field was reassigned to another reviewer and is no longer yours to answer.",
        )


class ReviewSubmissionMixin(ReviewCitationSubmissionMixin):
    def _recover_or_reject_expired_lease(self, session: Session, assignment: Assignment) -> None:
        """Let a write on a lapsed lease re-extend it in place while the slot is still free.

        Allocation-published assignments carry a fixed publish lease that nothing renews (the
        workspace has no heartbeat), so a hard refusal here stranded whole campaigns once that
        horizon passed: every draft/submit answered 409 with no recovery path (renew refused an
        expired lease, re-claim returned the same expired row, release is terminal). The lease
        exists to free abandoned slots for other reviewers -- so the write is refused only when
        that actually happened, i.e. the unit's remaining capacity has been taken
        (``_expired_lease_slot_available``). Lease-only update: ``lock_version`` is untouched, so
        the optimistic-concurrency check below still guards the payload, and a failure later in
        the request rolls the extension back with the transaction.
        """

        current = now_utc()
        if assignment.lease_expires_at > current:
            return
        if not self._expired_lease_slot_available(session, assignment, current):
            raise APIError(
                409,
                "assignment_lease_expired",
                "Assignment lease expired",
                "The assignment lease has expired.",
            )
        assignment.lease_expires_at = current + timedelta(seconds=LEASE_SECONDS)

    def save_annotation(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal,
        annotation: AnnotationInput,
        state: Literal["draft", "submitted"],
        expected_version: int,
        idempotency_key: str,
        request_id: str,
    ) -> AnnotationRevisionResponse:
        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        request_payload = {"state": state, "annotation": annotation.model_dump(mode="json")}
        request_digest = self._request_digest(request_payload)
        operation = f"review.{state}.{assignment_id}"
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
        )
        if record is not None:
            response = AnnotationRevisionResponse.model_validate(record.response_json)
            return response.model_copy(update={"replayed": True})
        assignment = session.scalar(
            select(Assignment)
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.id == assignment_id,
                Assignment.reviewer_id == principal.user.id,
            )
            .with_for_update()
        )
        if assignment is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        _reject_if_released(assignment)
        if assignment.status != "claimed":
            raise APIError(
                409,
                "assignment_not_editable",
                "Assignment not editable",
                "The assignment can no longer be changed.",
            )
        self._recover_or_reject_expired_lease(session, assignment)
        if assignment.lock_version != expected_version:
            raise APIError(
                412,
                "precondition_failed",
                "Precondition failed",
                "The assignment version is stale.",
            )
        candidates = list(
            session.scalars(
                select(Candidate).where(
                    Candidate.tenant_id == tenant_id,
                    Candidate.review_unit_id == assignment.review_unit_id,
                )
            )
        )
        evidence_ids = set(
            session.scalars(
                select(EvidenceWindow.id).where(
                    EvidenceWindow.tenant_id == tenant_id,
                    EvidenceWindow.review_unit_id == assignment.review_unit_id,
                )
            )
        )
        validate_annotation(
            annotation,
            candidates_by_id={candidate.id: candidate.label for candidate in candidates},
            allowed_evidence_ids=evidence_ids,
        )
        revision_no = (
            session.scalar(
                select(func.coalesce(func.max(AnnotationRevision.revision_no), 0)).where(
                    AnnotationRevision.tenant_id == tenant_id,
                    AnnotationRevision.assignment_id == assignment.id,
                )
            )
            or 0
        ) + 1
        revision = AnnotationRevision(
            tenant_id=tenant_id,
            assignment_id=assignment.id,
            revision_no=revision_no,
            state=state,
            outcome=annotation.outcome,
            corrected_value_json=annotation.corrected_value,
            corrected_value_display=annotation.corrected_value_display,
            comment=annotation.comment,
            assessments_json=[item.model_dump(mode="json") for item in annotation.assessments],
            evidence_ids_json=[str(item) for item in annotation.evidence_ids],
            client_request_id=self._key_digest(idempotency_key),
            author_id=principal.user.id,
        )
        session.add(revision)
        assignment.lock_version += 1
        if state == "submitted":
            assignment.status = "submitted"
            assignment.submitted_at = now_utc()
        session.flush()
        if state == "submitted":
            self._advance_to_adjudication(session, assignment, request_id=request_id)
        response = revision_response(revision, assignment.lock_version)
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type=f"review.annotation_{state}",
            object_type="assignment",
            object_id=str(assignment.id),
            request_id=request_id,
            payload={"revision_id": str(revision.id), "revision_no": revision.revision_no},
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

    def save_item_answer(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal,
        answer: ReviewItemAnswerInput,
        state: Literal["draft", "submitted"],
        expected_version: int,
        idempotency_key: str,
        request_id: str,
        artifact_store: ArtifactStore | None = None,
    ) -> ReviewItemAnswerResponse:
        """Persist a value/provenance answer revision for the grouped reviewer workspace."""

        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        request_payload = {"state": state, "answer": answer.model_dump(mode="json")}
        request_digest = self._request_digest(request_payload)
        operation = f"review.item_answer.{state}.{assignment_id}"
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
        )
        if record is not None:
            replayed = ReviewItemAnswerResponse.model_validate(record.response_json)
            return replayed.model_copy(update={"replayed": True})
        assignment = session.scalar(
            select(Assignment)
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.id == assignment_id,
                Assignment.reviewer_id == principal.user.id,
            )
            .with_for_update()
        )
        if assignment is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        citation_case = lock_citation_case(session, assignment)
        # Idempotent re-submit: this reviewer already submitted this field (a double-click that
        # raced past the client's in-flight guard, a retry after a dropped response, or a resubmit
        # of a done field). Answers are reviewer-scoped, so this is the intended end state, not a
        # conflict -- return the latest submitted revision as success rather than a user-visible
        # 409/412. Checked before the lease/version guards so a stale token or lapsed lease on an
        # already-submitted field never surfaces an error either. A submitted assignment with no
        # value/provenance revision (e.g. an annotation-path submit) falls through to the guards.
        if assignment.status == "submitted":
            latest = session.scalar(
                select(ReviewItemAnswer)
                .where(
                    ReviewItemAnswer.tenant_id == tenant_id,
                    ReviewItemAnswer.assignment_id == assignment.id,
                )
                .order_by(ReviewItemAnswer.revision_no.desc())
                .limit(1)
            )
            if latest is not None and latest.state == "submitted":
                return _item_answer_response(
                    latest,
                    review_unit_id=assignment.review_unit_id,
                    lock_version=assignment.lock_version,
                    replayed=True,
                )
        _reject_if_released(assignment)
        if assignment.status != "claimed":
            raise APIError(
                409,
                "assignment_not_editable",
                "Assignment not editable",
                "The assignment can no longer be changed.",
            )
        self._recover_or_reject_expired_lease(session, assignment)
        if assignment.lock_version != expected_version:
            raise APIError(
                412,
                "precondition_failed",
                "Precondition failed",
                "The assignment version is stale.",
            )
        evidence_ids = set(
            session.scalars(
                select(EvidenceWindow.id).where(
                    EvidenceWindow.tenant_id == tenant_id,
                    EvidenceWindow.review_unit_id == assignment.review_unit_id,
                )
            )
        )
        extraction_state, review_kind, subject_attributes = session.execute(
            select(
                ReviewUnit.extraction_state, ReviewUnit.review_kind, ReviewSubject.attributes_json
            )
            .join(
                ReviewSubject,
                (ReviewSubject.id == ReviewUnit.review_subject_id)
                & (ReviewSubject.tenant_id == ReviewUnit.tenant_id),
            )
            .where(
                ReviewUnit.tenant_id == tenant_id,
                ReviewUnit.id == assignment.review_unit_id,
            )
        ).one()
        validate_item_answer(
            answer,
            state=state,
            allowed_evidence_ids=evidence_ids,
            extraction_state=extraction_state,
        )
        if state == "submitted" and citation_case:
            self.check_citation_answer(session, assignment, principal, answer, artifact_store)
        revision_no = (
            session.scalar(
                select(func.coalesce(func.max(ReviewItemAnswer.revision_no), 0)).where(
                    ReviewItemAnswer.tenant_id == tenant_id,
                    ReviewItemAnswer.assignment_id == assignment.id,
                )
            )
            or 0
        ) + 1
        revision = ReviewItemAnswer(
            tenant_id=tenant_id,
            assignment_id=assignment.id,
            revision_no=revision_no,
            state=state,
            value_correct=answer.value_correct,
            provenance_correct=answer.provenance_correct,
            corrected_value_json=answer.corrected_value,
            corrected_value_display=answer.corrected_value_display,
            comment=answer.comment,
            failure_reason=answer.failure_reason,
            evidence_ids_json=[str(item) for item in answer.evidence_ids],
            corrected_provenance_spans_json=[
                span.model_dump(mode="json") for span in answer.corrected_provenance_spans
            ],
            client_request_id=self._key_digest(idempotency_key),
            author_id=principal.user.id,
        )
        session.add(revision)
        assignment.lock_version += 1
        if state == "submitted":
            assignment.status = "submitted"
            assignment.submitted_at = now_utc()
        session.flush()
        if state == "submitted":
            self._advance_to_adjudication(session, assignment, request_id=request_id)
        response = _item_answer_response(
            revision,
            review_unit_id=assignment.review_unit_id,
            lock_version=assignment.lock_version,
        )
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type=f"review.item_answer_{state}",
            object_type="assignment",
            object_id=str(assignment.id),
            request_id=request_id,
            payload={"revision_id": str(revision.id), "revision_no": revision.revision_no},
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
