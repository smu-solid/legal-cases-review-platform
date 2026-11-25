"""Assignment-scoped source-render artifact resolution.

Authorizes a reviewer for one assignment through the same ownership chain the grouped bundle uses
(reviewer role + own assignment -> review unit -> subject -> source snapshot) and returns the
current render artifact metadata row. Every miss -- wrong tenant, wrong reviewer, missing
assignment, missing subject, or missing artifact -- collapses to one generic 404 (no oracle).
Artifact body/anchor bytes are read from the store by the route, not here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.errors import APIError
from review_platform.review.adjudication_cases import same_case_clause
from review_platform.review.base import ReviewServiceBase
from review_platform.review.models import (
    Adjudication,
    AdjudicationParticipation,
    Assignment,
    ReviewSubject,
    ReviewUnit,
    SourceRenderArtifact,
)


@dataclass(frozen=True)
class AdjudicationSourceRenderContext:
    artifact: SourceRenderArtifact


class ReviewSourceRenderMixin(ReviewServiceBase):
    def source_render_artifact(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal,
    ) -> SourceRenderArtifact:
        """Return the current render artifact for the reviewer's assignment, or raise 404."""

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
        artifact = session.scalar(
            select(SourceRenderArtifact).where(
                SourceRenderArtifact.tenant_id == tenant_id,
                SourceRenderArtifact.source_snapshot_id == subject.source_snapshot_id,
                SourceRenderArtifact.is_current.is_(True),
            )
        )
        if artifact is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        return artifact

    def adjudication_source_render_artifact(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal,
        review_unit_id: uuid.UUID | None = None,
    ) -> AdjudicationSourceRenderContext:
        """Resolve the same current artifact through caller-owned adjudication participation."""

        self._require_role(session, principal, tenant_id, "adjudicator", allow_global_admin=True)
        self._set_tenant_scope(session, tenant_id)
        anchor = session.execute(
            select(Adjudication, ReviewUnit, ReviewSubject)
            .join(
                AdjudicationParticipation,
                AdjudicationParticipation.adjudication_id == Adjudication.id,
            )
            .join(ReviewUnit, ReviewUnit.id == Adjudication.review_unit_id)
            .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
            .where(
                Adjudication.tenant_id == tenant_id,
                Adjudication.id == adjudication_id,
                AdjudicationParticipation.adjudicator_id == principal.user.id,
                AdjudicationParticipation.status.in_(("pending", "submitted")),
            )
        ).first()
        if anchor is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        _anchor_adjudication, anchor_unit, anchor_subject = anchor
        artifact = session.scalar(
            select(SourceRenderArtifact).where(
                SourceRenderArtifact.tenant_id == tenant_id,
                SourceRenderArtifact.source_snapshot_id == anchor_subject.source_snapshot_id,
                SourceRenderArtifact.is_current.is_(True),
            )
        )
        if artifact is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        if review_unit_id is None:
            return AdjudicationSourceRenderContext(artifact=artifact)
        target = session.scalar(
            select(ReviewUnit)
            .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
            .join(Adjudication, Adjudication.review_unit_id == ReviewUnit.id)
            .join(
                AdjudicationParticipation,
                AdjudicationParticipation.adjudication_id == Adjudication.id,
            )
            .where(
                ReviewUnit.tenant_id == tenant_id,
                ReviewUnit.id == review_unit_id,
                ReviewUnit.campaign_id == anchor_unit.campaign_id,
                same_case_clause(anchor_subject),
                AdjudicationParticipation.adjudicator_id == principal.user.id,
                AdjudicationParticipation.status.in_(("pending", "submitted")),
            )
        )
        if target is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        return AdjudicationSourceRenderContext(artifact=artifact)
