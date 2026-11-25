"""Reviewer assignment bundle: candidates, evidence, and the reviewer's prior self-draft."""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal, now_utc
from review_platform.common.errors import APIError
from review_platform.review.base import ReviewServiceBase
from review_platform.review.models import (
    AnnotationRevision,
    Assignment,
    Candidate,
    EvidenceWindow,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.projections import (
    assignment_summary,
    candidate_response,
    evidence_response,
    revision_response,
    subject_response,
)
from review_platform.review.schemas import (
    AssignmentBundle,
    CommentRequirements,
    RenderHints,
)
from review_platform.review.state_machine import COMMENT_REQUIRED_OUTCOMES

BundleAction = Literal["save_draft", "submit", "renew", "release"]


def _bundle_actions(assignment: Assignment) -> list[BundleAction]:
    """Actions the reviewer may take on their assignment now.

    Only a claimed assignment with a live lease is actionable; once the lease has expired the
    reviewer must re-claim, so no action (including renew, which an expired lease forbids) is
    offered.
    """

    if assignment.status != "claimed" or assignment.lease_expires_at <= now_utc():
        return []
    return ["save_draft", "submit", "renew", "release"]


class ReviewBundleMixin(ReviewServiceBase):
    def bundle(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal,
    ) -> AssignmentBundle:
        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        assignment = session.scalar(
            select(Assignment).where(
                Assignment.tenant_id == tenant_id,
                Assignment.id == assignment_id,
                Assignment.reviewer_id == principal.user.id,
            )
        )
        if assignment is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        unit = session.scalar(
            select(ReviewUnit).where(
                ReviewUnit.tenant_id == tenant_id,
                ReviewUnit.id == assignment.review_unit_id,
            )
        )
        if unit is None:  # pragma: no cover - composite FK invariant
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        subject = session.scalar(
            select(ReviewSubject).where(
                ReviewSubject.tenant_id == tenant_id,
                ReviewSubject.id == unit.review_subject_id,
            )
        )
        if subject is None:  # pragma: no cover - composite FK invariant
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        candidates = list(
            session.scalars(
                select(Candidate)
                .where(
                    Candidate.tenant_id == tenant_id,
                    Candidate.review_unit_id == unit.id,
                )
                .order_by(Candidate.label)
            )
        )
        evidence = list(
            session.scalars(
                select(EvidenceWindow)
                .where(
                    EvidenceWindow.tenant_id == tenant_id,
                    EvidenceWindow.review_unit_id == unit.id,
                )
                .order_by(EvidenceWindow.ordinal)
            )
        )
        prior_draft = session.scalar(
            select(AnnotationRevision)
            .where(
                AnnotationRevision.tenant_id == tenant_id,
                AnnotationRevision.assignment_id == assignment.id,
                AnnotationRevision.state == "draft",
            )
            .order_by(AnnotationRevision.revision_no.desc())
            .limit(1)
        )
        return AssignmentBundle(
            assignment=assignment_summary(assignment),
            review_subject=subject_response(subject),
            review_kind=unit.review_kind,
            question=unit.question,
            candidates=[candidate_response(candidate) for candidate in candidates],
            evidence_windows=[
                evidence_response(item, subject.attributes_json) for item in evidence
            ],
            prior_self_draft=(
                revision_response(prior_draft, assignment.lock_version)
                if prior_draft is not None
                else None
            ),
            allowed_actions=_bundle_actions(assignment),
            comment_requirements=CommentRequirements(
                required_for_outcomes=sorted(COMMENT_REQUIRED_OUTCOMES)
            ),
            render_hints=RenderHints(),
        )
