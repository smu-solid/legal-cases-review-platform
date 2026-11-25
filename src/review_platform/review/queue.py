"""Reviewer queue listing, campaign-grouped queue summary, and the reviewer's own assignment
list.

The flat queue surfaces three disjoint sets: the reviewer's own currently-claimed
assignments, the reviewer's own submitted (completed) assignments, and the pool of available
unclaimed units. Claimed and completed assignments are bounded (a reviewer holds/finishes
few at once) and are pinned to the first page; the available pool is keyset-paginated by
``(created_at, id)`` so large queues never require loading every row. The opaque cursor
encodes only that ordering key.

Every bucket is scoped to campaigns the reviewer is actually assigned to
(:meth:`ReviewQueueMixin._reviewer_campaign_ids`): explicitly selected on the campaign
roster, or already holding an assignment there (covers a campaign whose allocation run
assigned units directly rather than through the open pool). A campaign outside that set
never appears, and an explicit ``campaign_id`` filter for a campaign the reviewer is not
assigned to yields an empty page rather than an error (no oracle for campaign existence)."""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.pagination import (
    MAX_PAGE_SIZE,
    decode_cursor,
)
from review_platform.review.grouping import display_field_label
from review_platform.review.models import (
    Assignment,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.projections import assignment_summary
from review_platform.review.queue_identity import _case_id
from review_platform.review.reviewer_available_queue import ReviewerAvailableQueueMixin
from review_platform.review.schemas import (
    AssignmentSummary,
    ReviewQueueItem,
    ReviewQueuePage,
)


class ReviewQueueMixin(ReviewerAvailableQueueMixin):
    def queue(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        subject_kind: str | None,
        review_kind: str | None,
        campaign_id: uuid.UUID | None,
        assignment_status: str | None,
        limit: int,
        cursor: str | None,
    ) -> ReviewQueuePage:
        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        allowed_campaign_ids = self._reviewer_campaign_ids(
            session, tenant_id=tenant_id, reviewer_id=principal.user.id
        )
        if not allowed_campaign_ids or (
            campaign_id is not None and campaign_id not in allowed_campaign_ids
        ):
            return ReviewQueuePage(items=[], next_cursor=None, has_more=False)
        after = decode_cursor(cursor)
        items: list[ReviewQueueItem] = []
        # Pinned, bounded claimed/completed work appears only on the first page (no cursor).
        if assignment_status in (None, "assigned", "completed") and after is None:
            items.extend(
                self._owned_queue_items(
                    session,
                    tenant_id=tenant_id,
                    principal=principal,
                    subject_kind=subject_kind,
                    review_kind=review_kind,
                    campaign_id=campaign_id,
                    allowed_campaign_ids=allowed_campaign_ids,
                    completed=assignment_status == "completed",
                )
            )
        next_cursor: str | None = None
        has_more = False
        if assignment_status in (None, "available"):
            available, next_cursor, has_more = self._available_queue_page(
                session,
                tenant_id=tenant_id,
                principal=principal,
                subject_kind=subject_kind,
                review_kind=review_kind,
                campaign_id=campaign_id,
                allowed_campaign_ids=allowed_campaign_ids,
                limit=limit,
                after=after,
            )
            items.extend(available)
        return ReviewQueuePage(items=items, next_cursor=next_cursor, has_more=has_more)

    def _owned_queue_items(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        subject_kind: str | None,
        review_kind: str | None,
        campaign_id: uuid.UUID | None,
        allowed_campaign_ids: set[uuid.UUID],
        completed: bool,
    ) -> list[ReviewQueueItem]:
        status: Literal["assigned", "completed"] = "completed" if completed else "assigned"
        statement = (
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
                Assignment.status == ("submitted" if completed else "claimed"),
                ReviewUnit.campaign_id.in_(allowed_campaign_ids),
            )
            .order_by(
                Assignment.submitted_at.desc() if completed else Assignment.claimed_at,
                Assignment.id,
            )
            .limit(MAX_PAGE_SIZE)
        )
        if subject_kind is not None:
            statement = statement.where(ReviewSubject.subject_kind == subject_kind)
        if review_kind is not None:
            statement = statement.where(ReviewUnit.review_kind == review_kind)
        if campaign_id is not None:
            statement = statement.where(ReviewUnit.campaign_id == campaign_id)
        return [
            ReviewQueueItem(
                review_unit_id=unit.id,
                assignment_id=assignment.id,
                assignment_status=status,
                campaign_id=unit.campaign_id,
                case_id=_case_id(subject),
                subject_kind=subject.subject_kind,
                review_kind=unit.review_kind,
                display_title=subject.display_title,
                display_subtitle=subject.display_subtitle,
                safe_field_label=display_field_label(unit.field_name, unit.safe_field_label),
            )
            for assignment, unit, subject in session.execute(statement).all()
        ]

    def list_assignments(
        self, session: Session, *, tenant_id: uuid.UUID, principal: Principal
    ) -> list[AssignmentSummary]:
        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        assignments = session.scalars(
            select(Assignment)
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.reviewer_id == principal.user.id,
            )
            .order_by(Assignment.claimed_at, Assignment.id)
        )
        return [assignment_summary(assignment) for assignment in assignments]
