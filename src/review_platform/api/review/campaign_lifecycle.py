"""Campaign lifecycle."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from review_platform.api.params import DEFAULT_LIMIT, PageCursor, PageLimit
from review_platform.api.review.support import ReviewContext
from review_platform.auth.service import Principal
from review_platform.review.schemas import (
    CampaignAllocationSummaryResponse,
    CampaignCaseProgressPage,
    CampaignDeleteResponse,
    CampaignDetailResponse,
    CampaignEditRequest,
    CampaignReviewerAddRequest,
    CampaignReviewersResponse,
    LoadPoolCasesRequest,
    LoadPoolCasesResponse,
)


def register_routes(
    router: APIRouter,
    context: ReviewContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> None:
    @router.get(
        "/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}",
        response_model=CampaignDetailResponse,
        operation_id="getCampaign",
    )
    def get_campaign(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignDetailResponse:
        return context.review.get_campaign(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
        )

    @router.patch(
        "/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}",
        response_model=CampaignDetailResponse,
        operation_id="editCampaign",
    )
    def edit_campaign(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        body: CampaignEditRequest,
        request: Request,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignDetailResponse:
        return context.review.edit_campaign(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
            body=body,
            request_id=request.state.request_id,
        )

    @router.delete(
        "/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}",
        response_model=CampaignDeleteResponse,
        operation_id="deleteCampaign",
    )
    def delete_campaign(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        request: Request,
        confirm: bool = Query(default=False),
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignDeleteResponse:
        return context.review.delete_campaign(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
            confirm=confirm,
            request_id=request.state.request_id,
        )

    @router.post(
        "/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/complete",
        response_model=CampaignDetailResponse,
        operation_id="completeCampaign",
    )
    def complete_campaign(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        request: Request,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignDetailResponse:
        return context.review.mark_campaign_completed(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
            request_id=request.state.request_id,
        )

    @router.post(
        "/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/reviewers",
        response_model=CampaignReviewersResponse,
        operation_id="addCampaignReviewer",
    )
    def add_campaign_reviewer(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        body: CampaignReviewerAddRequest,
        request: Request,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignReviewersResponse:
        return context.review.add_campaign_reviewer(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
            reviewer_id=body.reviewer_id,
            request_id=request.state.request_id,
        )

    @router.delete(
        "/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/reviewers/{reviewer_id}",
        response_model=CampaignReviewersResponse,
        operation_id="removeCampaignReviewer",
    )
    def remove_campaign_reviewer(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        request: Request,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignReviewersResponse:
        return context.review.remove_campaign_reviewer(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
            reviewer_id=reviewer_id,
            request_id=request.state.request_id,
        )

    @router.get(
        "/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/allocation-summary",
        response_model=CampaignAllocationSummaryResponse,
        operation_id="getCampaignAllocationSummary",
    )
    def campaign_allocation_summary(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        include_plan: bool = Query(default=True),
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignAllocationSummaryResponse:
        return context.review.campaign_allocation_summary(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
            include_plan=include_plan,
        )

    @router.post(
        "/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/pool-cases",
        response_model=LoadPoolCasesResponse,
        operation_id="loadPoolCases",
    )
    def load_pool_cases(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        body: LoadPoolCasesRequest,
        request: Request,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> LoadPoolCasesResponse:
        return context.review.load_pool_cases(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
            body=body,
            request_id=request.state.request_id,
        )

    @router.get(
        "/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/cases",
        response_model=CampaignCaseProgressPage,
        operation_id="listCampaignCases",
    )
    def campaign_cases(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        limit: PageLimit = DEFAULT_LIMIT,
        cursor: PageCursor = None,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CampaignCaseProgressPage:
        return context.review.campaign_cases(
            session,
            tenant_id=tenant_id,
            principal=principal,
            campaign_id=campaign_id,
            limit=limit,
            cursor=cursor,
        )
