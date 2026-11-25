"""Incremental allocation route registration."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from review_platform.api.allocation.runs import BASE
from review_platform.api.allocation.support import AllocationContext
from review_platform.api.params import IdempotencyKey
from review_platform.auth.service import Principal
from review_platform.review.allocation.schemas import (
    IncrementalPolicyInput,
    IncrementalPreviewResponse,
    IncrementalPublishResponse,
    IncrementalRunResponse,
)


def register_routes(
    router: APIRouter,
    context: AllocationContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> None:
    del principal_dependency

    @router.post(
        f"{BASE}/incremental-preview",
        response_model=IncrementalPreviewResponse,
        operation_id="previewIncrementalAllocationRun",
    )
    def preview_incremental_run(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        body: IncrementalPolicyInput,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> IncrementalPreviewResponse:
        return context.allocation.preview_incremental_run(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            principal=principal,
            body=body,
        )

    @router.post(
        f"{BASE}/incremental",
        response_model=IncrementalRunResponse,
        operation_id="persistIncrementalAllocationRun",
        status_code=201,
    )
    def persist_incremental_run(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        body: IncrementalPolicyInput,
        request: Request,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> IncrementalRunResponse:
        return context.allocation.persist_incremental_run(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            principal=principal,
            body=body,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )

    @router.post(
        f"{BASE}/{{run_id}}/publish-incremental",
        response_model=IncrementalPublishResponse,
        operation_id="publishIncrementalAllocationRun",
        status_code=201,
    )
    def publish_incremental_run(
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        request: Request,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> IncrementalPublishResponse:
        return context.allocation.publish_incremental_run(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            run_id=run_id,
            principal=principal,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
