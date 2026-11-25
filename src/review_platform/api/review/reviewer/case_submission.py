"""Case submission."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from review_platform.api.params import IdempotencyKey
from review_platform.api.review.support import ReviewContext
from review_platform.auth.service import Principal
from review_platform.review.schemas import CaseSubmissionResponse


def register_routes(
    router: APIRouter,
    context: ReviewContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> None:
    del principal_dependency

    @router.post(
        "/tenants/{tenant_id}/review/assignments/{assignment_id}/case-submit",
        response_model=CaseSubmissionResponse,
        operation_id="submitReviewerCase",
        status_code=201,
    )
    def submit_case(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        request: Request,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CaseSubmissionResponse:
        return context.review.submit_case(
            session,
            tenant_id=tenant_id,
            principal=principal,
            assignment_id=assignment_id,
            idempotency_key=idempotency_key,
            artifact_store=context.artifact_store,
            request_id=request.state.request_id,
        )
