"""Admin/campaign-manager review views: submission listing and campaign/reviewer progress
summaries.

Campaign authoring (including pool-drawn creation) lives in
``review_platform.review.campaign_pool_admin`` (``ReviewCampaignPoolMixin``); draft
edit/delete, reviewer selection, and simple allocation math live in
``review_platform.review.campaign_lifecycle`` (``ReviewCampaignLifecycleMixin``); reviewer
agreement metrics live in ``review_platform.review.campaign_agreement``
(``ReviewCampaignAgreementMixin``) -- all split out to keep this file focused on
unit/assignment-status reporting."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import String, case, func, select, tuple_
from sqlalchemy import cast as sa_cast
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.errors import APIError
from review_platform.common.pagination import decode_cursor, encode_cursor
from review_platform.db.models import AuditEvent
from review_platform.review.assignment_status import count_live, count_released
from review_platform.review.base import ReviewServiceBase
from review_platform.review.campaign_allocation_math import resolve_minimum_reviews_per_case
from review_platform.review.campaign_queries import CAMPAIGN_MARKED_COMPLETED_EVENT
from review_platform.review.campaign_reviewers import campaign_reviewer_work_exists
from review_platform.review.models import (
    AnnotationRevision,
    Assignment,
    Campaign,
    CaseSubmission,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.schemas import (
    AdminReviewSubmission,
    AdminReviewSubmissionPage,
    CampaignAssignmentStatusCounts,
    CampaignProgressItem,
    CampaignProgressResponse,
    CampaignUnitStatusCounts,
    CandidateAssessmentInput,
    ReviewerWorkloadItem,
    ReviewerWorkloadResponse,
)


class ReviewAdminMixin(ReviewServiceBase):
    def list_admin_submissions(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID | None,
        review_unit_id: uuid.UUID | None,
        review_kind: str | None,
        limit: int,
        cursor: str | None,
    ) -> AdminReviewSubmissionPage:
        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        statement = (
            select(AnnotationRevision, Assignment, ReviewUnit, ReviewSubject)
            .join(
                Assignment,
                (Assignment.tenant_id == AnnotationRevision.tenant_id)
                & (Assignment.id == AnnotationRevision.assignment_id),
            )
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
                AnnotationRevision.tenant_id == tenant_id,
                AnnotationRevision.state == "submitted",
                Assignment.status == "submitted",
            )
            .order_by(AnnotationRevision.created_at.desc(), AnnotationRevision.id.desc())
            .limit(limit + 1)
        )
        if campaign_id is not None:
            statement = statement.where(ReviewUnit.campaign_id == campaign_id)
        if review_unit_id is not None:
            statement = statement.where(ReviewUnit.id == review_unit_id)
        if review_kind is not None:
            statement = statement.where(ReviewUnit.review_kind == review_kind)
        after = decode_cursor(cursor)
        if after is not None:
            statement = statement.where(
                tuple_(AnnotationRevision.created_at, AnnotationRevision.id)
                < _submission_keyset(after)
            )
        rows = session.execute(statement).all()
        has_more = len(rows) > limit
        page = rows[:limit]
        items = [
            AdminReviewSubmission(
                submission_id=revision.id,
                assignment_id=assignment.id,
                review_unit_id=unit.id,
                reviewer_id=assignment.reviewer_id,
                subject_kind=cast(Any, subject.subject_kind),
                review_kind=cast(Any, unit.review_kind),
                display_title=subject.display_title,
                outcome=revision.outcome,
                corrected_value=revision.corrected_value_json,
                corrected_value_display=revision.corrected_value_display,
                comment=revision.comment,
                assessments=[
                    CandidateAssessmentInput.model_validate(item)
                    for item in revision.assessments_json
                ],
                evidence_ids=[uuid.UUID(value) for value in revision.evidence_ids_json],
                submitted_at=revision.created_at,
            )
            for revision, assignment, unit, subject in page
        ]
        next_cursor: str | None = None
        if has_more:
            last_revision = page[-1][0]
            next_cursor = encode_cursor(
                {
                    "created_at": last_revision.created_at.isoformat(),
                    "id": str(last_revision.id),
                }
            )
        return AdminReviewSubmissionPage(items=items, next_cursor=next_cursor, has_more=has_more)

    _MAX_CAMPAIGNS = 50
    _MAX_REVIEWERS = 200

    def campaign_progress(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID | None,
    ) -> CampaignProgressResponse:
        """Aggregate case/unit/assignment status counts per campaign — campaign_manager only."""
        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        stmt = (
            select(
                Campaign.id,
                Campaign.name,
                Campaign.key,
                Campaign.status,
                Campaign.policy_json,
                func.count(
                    func.distinct(
                        ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
                    )
                ).label("cases_total"),
                func.count(ReviewUnit.id.distinct()).label("total_units"),
                func.count(case((ReviewUnit.status == "pending", ReviewUnit.id)).distinct()).label(
                    "pending"
                ),
                func.count(
                    case((ReviewUnit.status == "in_review", ReviewUnit.id)).distinct()
                ).label("in_review"),
                func.count(
                    case((ReviewUnit.status == "in_adjudication", ReviewUnit.id)).distinct()
                ).label("in_adjudication"),
                func.count(case((ReviewUnit.status == "resolved", ReviewUnit.id)).distinct()).label(
                    "resolved"
                ),
                count_live(Assignment.id).label("total_assignments"),
                func.count(case((Assignment.status == "submitted", Assignment.id))).label(
                    "submitted_assignments"
                ),
                func.count(case((Assignment.status == "claimed", Assignment.id))).label(
                    "claimed_assignments"
                ),
                count_released(Assignment.id).label("released_assignments"),
                func.coalesce(
                    select(func.count(CaseSubmission.id))
                    .where(
                        CaseSubmission.tenant_id == tenant_id,
                        CaseSubmission.campaign_id == Campaign.id,
                    )
                    .correlate(Campaign)
                    .scalar_subquery(),
                    0,
                ).label("case_reviewer_completions"),
                func.coalesce(_cases_fully_complete_subquery(tenant_id), 0).label(
                    "cases_fully_complete_count"
                ),
                _campaign_completed_subquery().label("completed"),
            )
            .select_from(Campaign)
            .outerjoin(
                ReviewUnit,
                (ReviewUnit.tenant_id == Campaign.tenant_id)
                & (ReviewUnit.campaign_id == Campaign.id),
            )
            .outerjoin(
                ReviewSubject,
                (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
                & (ReviewSubject.id == ReviewUnit.review_subject_id),
            )
            .outerjoin(
                Assignment,
                (Assignment.tenant_id == ReviewUnit.tenant_id)
                & (Assignment.review_unit_id == ReviewUnit.id),
            )
            # The reserved case-pool campaign is never a reviewable campaign and must never appear
            # in the admin dashboard's campaign list.
            .where(Campaign.tenant_id == tenant_id, Campaign.status != "pool")
            .group_by(
                Campaign.id, Campaign.name, Campaign.key, Campaign.status, Campaign.policy_json
            )
            .order_by(Campaign.created_at.desc(), Campaign.id.desc())
            .limit(self._MAX_CAMPAIGNS)
        )
        if campaign_id is not None:
            stmt = stmt.where(Campaign.id == campaign_id)
        items = []
        for row in session.execute(stmt).all():
            reviewers_total = len((row.policy_json or {}).get("selected_reviewer_ids", []))
            reviews_per_case = resolve_minimum_reviews_per_case(
                (row.policy_json or {}).get("minimum_reviews_per_case")
            )
            items.append(
                CampaignProgressItem(
                    campaign_id=row.id,
                    campaign_name=row.name,
                    campaign_key=row.key,
                    campaign_status=row.status,
                    cases_total=row.cases_total,
                    total_units=row.total_units,
                    unit_status_counts=CampaignUnitStatusCounts(
                        pending=row.pending,
                        in_review=row.in_review,
                        in_adjudication=row.in_adjudication,
                        resolved=row.resolved,
                    ),
                    total_assignments=row.total_assignments,
                    assignment_status_counts=CampaignAssignmentStatusCounts(
                        claimed=row.claimed_assignments,
                        submitted=row.submitted_assignments,
                        released=row.released_assignments,
                    ),
                    reviewers_total=reviewers_total,
                    case_reviewer_slots_total=row.cases_total * reviews_per_case,
                    case_reviewer_completions=row.case_reviewer_completions,
                    cases_fully_complete_count=row.cases_fully_complete_count,
                    completed=bool(row.completed),
                )
            )
        return CampaignProgressResponse(tenant_id=tenant_id, items=items)

    def reviewer_workload(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID,
    ) -> ReviewerWorkloadResponse:
        """Per-reviewer assignment status counts for a campaign — campaign_manager only."""
        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        stmt = (
            select(
                Assignment.reviewer_id,
                # ``released_count`` reports the moved-away rows separately, so nothing is hidden.
                count_live(Assignment.id).label("total_assignments"),
                func.count(case((Assignment.status == "submitted", Assignment.id))).label(
                    "submitted_count"
                ),
                func.count(case((Assignment.status == "claimed", Assignment.id))).label(
                    "claimed_count"
                ),
                count_released(Assignment.id).label("released_count"),
            )
            .select_from(Assignment)
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == Assignment.tenant_id)
                & (ReviewUnit.id == Assignment.review_unit_id),
            )
            .where(
                Assignment.tenant_id == tenant_id,
                ReviewUnit.campaign_id == campaign_id,
            )
            .group_by(Assignment.reviewer_id)
            .order_by(Assignment.reviewer_id)
            .limit(self._MAX_REVIEWERS)
        )
        items = [
            ReviewerWorkloadItem(
                reviewer_id=row.reviewer_id,
                total_assignments=row.total_assignments,
                submitted_count=row.submitted_count,
                claimed_count=row.claimed_count,
                released_count=row.released_count,
                # Same definition the remove-reviewer guard enforces server-side
                # (``campaign_reviewer_work_exists``) -- the UI can freeze the remove control
                # ahead of a click without duplicating or guessing at that logic.
                has_work=campaign_reviewer_work_exists(
                    session,
                    tenant_id=tenant_id,
                    campaign_id=campaign_id,
                    reviewer_id=row.reviewer_id,
                ),
            )
            for row in session.execute(stmt).all()
        ]
        return ReviewerWorkloadResponse(tenant_id=tenant_id, campaign_id=campaign_id, items=items)


_CASE_ID_COL = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext


def _campaign_completed_subquery() -> Any:
    """True iff a ``campaign.marked_completed`` audit event exists for the correlated ``Campaign``
    row -- see ``review_platform.review.campaign_lifecycle._campaign_completed`` for the same
    check used by the single-campaign detail response. ``AuditEvent`` has no ``tenant_id`` column
    (global, hash-chained table); ``object_id`` is a campaign UUID, already globally unique.
    """

    return (
        select(func.count(AuditEvent.id))
        .where(
            AuditEvent.object_type == "campaign",
            AuditEvent.object_id == sa_cast(Campaign.id, String),
            AuditEvent.event_type == CAMPAIGN_MARKED_COMPLETED_EVENT,
        )
        .correlate(Campaign)
        .scalar_subquery()
    ) > 0


def _cases_fully_complete_subquery(tenant_id: uuid.UUID) -> Any:
    """Count of distinct cases in the correlated ``Campaign`` row where every reviewer actually
    assigned to the case (not necessarily every one of the campaign's selected reviewers -- same
    simplification as ``CampaignCaseProgressItem.reviewers_completed_count``) has an explicit
    ``CaseSubmission`` for it.
    """

    # Live holders only, matching ``CampaignCaseProgressItem.reviewers_assigned_count``. Counting a
    # released row here would raise the bar a case must clear to be "fully complete" above the
    # number of reviewers who can actually submit it -- such a case would never be complete at all.
    assigned_count = count_live(Assignment.reviewer_id, distinct=True)
    completed_count = func.max(
        select(func.count(CaseSubmission.id))
        .where(
            CaseSubmission.tenant_id == tenant_id,
            CaseSubmission.campaign_id == Campaign.id,
            CaseSubmission.case_id == _CASE_ID_COL,
        )
        .correlate(ReviewSubject, Campaign)
        .scalar_subquery()
    )
    per_case_fully_complete = (
        select(_CASE_ID_COL)
        .select_from(ReviewSubject)
        .join(
            ReviewUnit,
            (ReviewUnit.tenant_id == ReviewSubject.tenant_id)
            & (ReviewUnit.review_subject_id == ReviewSubject.id),
        )
        .outerjoin(
            Assignment,
            (Assignment.tenant_id == ReviewUnit.tenant_id)
            & (Assignment.review_unit_id == ReviewUnit.id),
        )
        .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id == Campaign.id)
        .group_by(_CASE_ID_COL)
        .having(assigned_count > 0)
        .having(completed_count >= assigned_count)
        .correlate(Campaign)
        .subquery()
    )
    return (
        select(func.count())
        .select_from(per_case_fully_complete)
        .correlate(Campaign)
        .scalar_subquery()
    )


def _submission_keyset(after: dict[str, object]) -> tuple[datetime, uuid.UUID]:
    """Decode the admin-submission keyset payload, failing closed on a malformed cursor."""

    try:
        created_at = datetime.fromisoformat(str(after["created_at"]))
        revision_id = uuid.UUID(str(after["id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise APIError(422, "cursor_invalid", "Invalid cursor", "The cursor is invalid.") from exc
    return created_at, revision_id
