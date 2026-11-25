"""Reviewer queue route registration."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from review_platform.api.params import DEFAULT_LIMIT, PageCursor, PageLimit
from review_platform.api.review.support import (
    QueueStatusFilter,
    ReviewContext,
)
from review_platform.auth.service import Principal
from review_platform.review.schemas import (
    ReviewerCampaignQueuePage,
    ReviewerCaseQueuePage,
    ReviewQueuePage,
)


def register_routes(
    router: APIRouter,
    context: ReviewContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> None:
    del csrf_dependency

    @router.get(
        "/tenants/{tenant_id}/review/queue",
        response_model=ReviewQueuePage,
        operation_id="listReviewQueue",
    )
    def queue(
        tenant_id: uuid.UUID,
        subject_kind: Annotated[str | None, Query(max_length=40)] = None,
        review_kind: Annotated[str | None, Query(max_length=60)] = None,
        campaign_id: uuid.UUID | None = None,
        assignment_status: QueueStatusFilter = None,
        limit: PageLimit = DEFAULT_LIMIT,
        cursor: PageCursor = None,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> ReviewQueuePage:
        return context.review.queue(
            session,
            tenant_id=tenant_id,
            principal=principal,
            subject_kind=subject_kind,
            review_kind=review_kind,
            campaign_id=campaign_id,
            assignment_status=assignment_status,
            limit=limit,
            cursor=cursor,
        )

    @router.get(
        "/tenants/{tenant_id}/review/campaigns",
        response_model=ReviewerCampaignQueuePage,
        operation_id="listReviewerCampaignQueue",
    )
    def campaign_queue(
        tenant_id: uuid.UUID,
        limit: PageLimit = DEFAULT_LIMIT,
        cursor: PageCursor = None,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> ReviewerCampaignQueuePage:
        return context.review.campaign_queue(
            session, tenant_id=tenant_id, principal=principal, limit=limit, cursor=cursor
        )

    @router.get(
        "/tenants/{tenant_id}/review/campaigns/{campaign_id}/cases",
        response_model=ReviewerCaseQueuePage,
        operation_id="listReviewerCaseQueue",
    )
    def case_queue(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        limit: PageLimit = DEFAULT_LIMIT,
        cursor: PageCursor = None,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> ReviewerCaseQueuePage:
        return context.review.case_queue(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
            limit=limit,
            cursor=cursor,
        )
