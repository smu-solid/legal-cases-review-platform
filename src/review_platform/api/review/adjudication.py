"""Adjudication routes: queue, claim, adjudication bundle, and final decision."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from review_platform.api.params import DEFAULT_LIMIT, IdempotencyKey, PageCursor, PageLimit
from review_platform.api.review.support import ReviewContext
from review_platform.auth.service import Principal
from review_platform.review.schemas import (
    AdjudicationBundle,
    AdjudicationCampaignCaseQueuePage,
    AdjudicationCampaignQueuePage,
    AdjudicationCaseNeighbors,
    AdjudicationCaseWorkspace,
    AdjudicationClaimResponse,
    AdjudicationDecisionInput,
    AdjudicationDecisionResponse,
    AdjudicationDraftInput,
    AdjudicationDraftResponse,
    AdjudicationGroupedBundle,
    AdjudicationSummary,
)

AdjudicationStatusFilter = Annotated[
    Literal["all", "waiting", "in_progress", "finished", "not_required"] | None,
    Query(),
]


def register_routes(
    router: APIRouter,
    context: ReviewContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> None:
    @router.get(
        "/tenants/{tenant_id}/review/adjudication-campaigns",
        response_model=AdjudicationCampaignQueuePage,
        operation_id="listAdjudicationCampaigns",
    )
    def adjudication_campaigns(
        tenant_id: uuid.UUID,
        request: Request,
        limit: PageLimit = DEFAULT_LIMIT,
        cursor: PageCursor = None,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AdjudicationCampaignQueuePage:
        return context.review.adjudication_campaign_queue(
            session,
            tenant_id=tenant_id,
            principal=principal,
            limit=limit,
            cursor=cursor,
            request_id=request.state.request_id,
        )

    @router.get(
        "/tenants/{tenant_id}/review/adjudication-campaigns/{campaign_id}/cases",
        response_model=AdjudicationCampaignCaseQueuePage,
        operation_id="listAdjudicationCampaignCases",
    )
    def adjudication_campaign_cases(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        request: Request,
        status: AdjudicationStatusFilter = None,
        limit: PageLimit = DEFAULT_LIMIT,
        cursor: PageCursor = None,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AdjudicationCampaignCaseQueuePage:
        return context.review.adjudication_campaign_cases(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            principal=principal,
            status=status,
            limit=limit,
            cursor=cursor,
            request_id=request.state.request_id,
        )

    @router.get(
        "/tenants/{tenant_id}/review/adjudication-campaigns/{campaign_id}/cases/neighbors",
        response_model=AdjudicationCaseNeighbors,
        operation_id="getAdjudicationCaseNeighbors",
    )
    def adjudication_case_neighbors(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        anchor_adjudication_id: uuid.UUID,
        request: Request,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AdjudicationCaseNeighbors:
        return context.review.adjudication_case_neighbors(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            anchor_adjudication_id=anchor_adjudication_id,
            principal=principal,
            request_id=request.state.request_id,
        )

    @router.get(
        "/tenants/{tenant_id}/review/adjudications/{adjudication_id}/case-workspace",
        response_model=AdjudicationCaseWorkspace,
        operation_id="getAdjudicationCaseWorkspace",
    )
    def adjudication_case_workspace(
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        request: Request,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AdjudicationCaseWorkspace:
        return context.review.adjudication_case_workspace(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
            artifact_store=context.artifact_store,
            request_id=request.state.request_id,
        )

    @router.get(
        "/tenants/{tenant_id}/review/adjudications",
        response_model=list[AdjudicationSummary],
        operation_id="listAdjudications",
    )
    def adjudications(
        tenant_id: uuid.UUID,
        request: Request,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> list[AdjudicationSummary]:
        return context.review.list_adjudications(
            session,
            tenant_id=tenant_id,
            principal=principal,
            request_id=request.state.request_id,
        )

    @router.post(
        "/tenants/{tenant_id}/review/adjudications/claim",
        response_model=AdjudicationClaimResponse,
        operation_id="claimAdjudication",
        status_code=201,
        deprecated=True,
    )
    def claim_adjudication(
        tenant_id: uuid.UUID,
        request: Request,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AdjudicationClaimResponse:
        return context.review.claim_adjudication(
            session,
            tenant_id=tenant_id,
            principal=principal,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )

    @router.get(
        "/tenants/{tenant_id}/review/adjudications/{adjudication_id}/bundle",
        response_model=AdjudicationBundle,
        operation_id="getAdjudicationBundle",
    )
    def adjudication_bundle(
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AdjudicationBundle:
        return context.review.adjudication_bundle(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
        )

    @router.get(
        "/tenants/{tenant_id}/review/adjudications/{adjudication_id}/grouped-bundle",
        response_model=AdjudicationGroupedBundle,
        operation_id="getAdjudicationGroupedBundle",
    )
    def adjudication_grouped_bundle(
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AdjudicationGroupedBundle:
        return context.review.adjudication_grouped_bundle(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
            artifact_store=context.artifact_store,
        )

    @router.post(
        "/tenants/{tenant_id}/review/adjudications/{adjudication_id}/submit",
        response_model=AdjudicationDecisionResponse,
        operation_id="submitAdjudicationDecision",
        status_code=201,
    )
    def submit_adjudication(
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        body: AdjudicationDecisionInput,
        request: Request,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AdjudicationDecisionResponse:
        return context.review.submit_adjudication(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
            decision=body,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
            artifact_store=context.artifact_store,
        )

    @router.put(
        "/tenants/{tenant_id}/review/adjudications/{adjudication_id}/draft",
        response_model=AdjudicationDraftResponse,
        operation_id="saveAdjudicationDraft",
    )
    def save_adjudication_draft(
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        body: AdjudicationDraftInput,
        request: Request,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AdjudicationDraftResponse:
        return context.review.save_adjudication_draft(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
            decision=body,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
            artifact_store=context.artifact_store,
        )
