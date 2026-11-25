"""Allocation run route registration."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from review_platform.api.allocation.support import AllocationContext
from review_platform.api.params import DEFAULT_LIMIT, IdempotencyKey, PageCursor, PageLimit
from review_platform.auth.service import Principal
from review_platform.review.allocation.schemas import (
    AllocationDiscardResponse,
    AllocationMatrixResponse,
    AllocationPolicyInput,
    AllocationPreviewResponse,
    AllocationPublishResponse,
    AllocationRunPage,
    AllocationRunResponse,
    ReviewerWorkloadsResponse,
    SubjectCoverageResponse,
    SubjectPoolPreviewRequest,
    SubjectPoolPreviewResponse,
)

BASE = "/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs"


def register_routes(
    router: APIRouter,
    context: AllocationContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> None:
    @router.post(
        "/tenants/{tenant_id}/campaigns/{campaign_id}/subjects/preview",
        response_model=SubjectPoolPreviewResponse,
        operation_id="previewAllocationSubjects",
    )
    def preview_subjects(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        body: SubjectPoolPreviewRequest,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> SubjectPoolPreviewResponse:
        return context.allocation.preview_subjects(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            principal=principal,
            body=body,
        )

    @router.post(
        f"{BASE}/preview",
        response_model=AllocationPreviewResponse,
        operation_id="previewAllocationRun",
    )
    def preview_run(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        body: AllocationPolicyInput,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AllocationPreviewResponse:
        return context.allocation.preview_run(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            principal=principal,
            body=body,
        )

    @router.post(
        BASE,
        response_model=AllocationRunResponse,
        operation_id="persistAllocationRun",
        status_code=201,
    )
    def persist_run(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        body: AllocationPolicyInput,
        request: Request,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AllocationRunResponse:
        return context.allocation.persist_run(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            principal=principal,
            body=body,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )

    @router.post(
        f"{BASE}/publish",
        response_model=AllocationPublishResponse,
        operation_id="publishAllocationPlan",
        status_code=201,
    )
    def publish_from_policy(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        body: AllocationPolicyInput,
        request: Request,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AllocationPublishResponse:
        return context.allocation.publish_from_policy(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            principal=principal,
            body=body,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )

    @router.get(
        BASE,
        response_model=AllocationRunPage,
        operation_id="listAllocationRuns",
    )
    def list_runs(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        limit: PageLimit = DEFAULT_LIMIT,
        cursor: PageCursor = None,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AllocationRunPage:
        return context.allocation.list_runs(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            principal=principal,
            limit=limit,
            cursor=cursor,
        )

    @router.get(
        f"{BASE}/{{run_id}}",
        response_model=AllocationRunResponse,
        operation_id="getAllocationRun",
    )
    def get_run(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AllocationRunResponse:
        return context.allocation.get_run(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            run_id=run_id,
            principal=principal,
        )

    @router.get(
        f"{BASE}/{{run_id}}/matrix",
        response_model=AllocationMatrixResponse,
        operation_id="getAllocationMatrix",
    )
    def matrix(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        request: Request,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AllocationMatrixResponse:
        return context.allocation.matrix(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            run_id=run_id,
            principal=principal,
            request_id=request.state.request_id,
        )

    @router.get(
        f"{BASE}/{{run_id}}/reviewer-workloads",
        response_model=ReviewerWorkloadsResponse,
        operation_id="getAllocationReviewerWorkloads",
    )
    def reviewer_workloads(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> ReviewerWorkloadsResponse:
        return context.allocation.reviewer_workloads(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            run_id=run_id,
            principal=principal,
        )

    @router.get(
        f"{BASE}/{{run_id}}/subject-coverage",
        response_model=SubjectCoverageResponse,
        operation_id="getAllocationSubjectCoverage",
    )
    def subject_coverage(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> SubjectCoverageResponse:
        return context.allocation.subject_coverage(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            run_id=run_id,
            principal=principal,
        )

    @router.post(
        f"{BASE}/{{run_id}}/publish",
        response_model=AllocationPublishResponse,
        operation_id="publishAllocationRun",
        status_code=201,
    )
    def publish_run(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        request: Request,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AllocationPublishResponse:
        return context.allocation.publish_run(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            run_id=run_id,
            principal=principal,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )

    @router.post(
        f"{BASE}/{{run_id}}/discard",
        response_model=AllocationDiscardResponse,
        operation_id="discardAllocationRun",
        status_code=201,
    )
    def discard_run(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        request: Request,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AllocationDiscardResponse:
        return context.allocation.discard_run(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            run_id=run_id,
            principal=principal,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
