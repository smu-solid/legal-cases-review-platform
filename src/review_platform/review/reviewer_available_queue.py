"""Available reviewer work, with assignment eligibility and keyset pagination."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from review_platform.auth.service import Principal, now_utc
from review_platform.common.pagination import (
    encode_cursor,
)
from review_platform.review.grouping import display_field_label
from review_platform.review.models import (
    AllocationRun,
    Assignment,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.queue_identity import _case_id, _keyset
from review_platform.review.reviewer_campaign_queue import ReviewerCampaignQueueMixin
from review_platform.review.schemas import (
    ReviewQueueItem,
)


class ReviewerAvailableQueueMixin(ReviewerCampaignQueueMixin):
    def _available_queue_page(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        subject_kind: str | None,
        review_kind: str | None,
        campaign_id: uuid.UUID | None,
        allowed_campaign_ids: set[uuid.UUID],
        limit: int,
        after: dict[str, object] | None,
    ) -> tuple[list[ReviewQueueItem], str | None, bool]:
        # Every allowed campaign is a candidate when no explicit campaign_id filter narrows it.
        candidate_campaign_ids = {campaign_id} if campaign_id is not None else allowed_campaign_ids
        clauses: list[ColumnElement[bool]] = [
            ReviewUnit.tenant_id == tenant_id,
            ReviewUnit.campaign_id.in_(candidate_campaign_ids),
            ReviewUnit.status.in_(("pending", "in_review")),
            self._open_slot_clause(tenant_id=tenant_id, principal=principal, current=now_utc()),
        ]
        statement = (
            select(ReviewUnit, ReviewSubject)
            .join(
                ReviewSubject,
                (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
                & (ReviewSubject.id == ReviewUnit.review_subject_id),
            )
            .where(*clauses)
            .order_by(ReviewUnit.created_at, ReviewUnit.id)
            .limit(limit + 1)
        )
        if subject_kind is not None:
            statement = statement.where(ReviewSubject.subject_kind == subject_kind)
        if review_kind is not None:
            statement = statement.where(ReviewUnit.review_kind == review_kind)
        if after is not None:
            statement = statement.where(
                tuple_(ReviewUnit.created_at, ReviewUnit.id) > _keyset(after)
            )
        rows = session.execute(statement).all()
        has_more = len(rows) > limit
        page = rows[:limit]
        items = [
            ReviewQueueItem(
                review_unit_id=unit.id,
                campaign_id=unit.campaign_id,
                case_id=_case_id(subject),
                subject_kind=subject.subject_kind,
                review_kind=unit.review_kind,
                display_title=subject.display_title,
                display_subtitle=subject.display_subtitle,
                safe_field_label=display_field_label(unit.field_name, unit.safe_field_label),
            )
            for unit, subject in page
        ]
        next_cursor: str | None = None
        if has_more:
            last_unit, _last_subject = page[-1]
            next_cursor = encode_cursor(
                {"created_at": last_unit.created_at.isoformat(), "id": str(last_unit.id)}
            )
        return items, next_cursor, has_more

    def _open_slot_clause(
        self, *, tenant_id: uuid.UUID, principal: Principal, current: datetime
    ) -> ColumnElement[bool]:
        """Whether a ``ReviewUnit`` still has an open slot this reviewer may claim.

        Shared by the paginated available-queue page and the unpaginated per-campaign
        not-started count so both apply the identical eligibility rule.
        """

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
        return (
            (claimed_count < ReviewUnit.required_reviews)
            & ~own_assignment
            & ~published_allocation_campaign
        )
