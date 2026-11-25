"""Reviewer claim and lease lifecycle route registration."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from review_platform.api.params import (
    LOCK_VERSION_RESPONSE_HEADERS,
    IdempotencyKey,
    IfMatch,
    expected_version,
    set_lock_version_etag,
)
from review_platform.api.review.support import ReviewContext
from review_platform.auth.service import Principal
from review_platform.review.schemas import (
    AssignmentLeaseResponse,
    ClaimRequest,
    ClaimResponse,
)


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
        "/tenants/{tenant_id}/review/claim",
        response_model=ClaimResponse,
        operation_id="claimReviewUnit",
        status_code=201,
        responses={201: {"headers": LOCK_VERSION_RESPONSE_HEADERS}},
    )
    def claim(
        tenant_id: uuid.UUID,
        body: ClaimRequest,
        request: Request,
        response: Response,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> ClaimResponse:
        result = context.review.claim(
            session,
            tenant_id=tenant_id,
            principal=principal,
            body=body,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
        set_lock_version_etag(response, result.lock_version)
        return result

    @router.post(
        "/tenants/{tenant_id}/review/assignments/{assignment_id}/renew",
        response_model=AssignmentLeaseResponse,
        operation_id="renewAssignmentLease",
        responses={200: {"headers": LOCK_VERSION_RESPONSE_HEADERS}},
    )
    def renew(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        request: Request,
        response: Response,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AssignmentLeaseResponse:
        result = context.review.renew(
            session,
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            principal=principal,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
        set_lock_version_etag(response, result.lock_version)
        return result

    @router.post(
        "/tenants/{tenant_id}/review/assignments/{assignment_id}/reopen",
        response_model=AssignmentLeaseResponse,
        operation_id="reopenAssignment",
        responses={200: {"headers": LOCK_VERSION_RESPONSE_HEADERS}},
    )
    def reopen(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        request: Request,
        response: Response,
        idempotency_key: IdempotencyKey,
        if_match: IfMatch,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AssignmentLeaseResponse:
        result = context.review.reopen(
            session,
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            principal=principal,
            expected_version=expected_version(if_match),
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
        set_lock_version_etag(response, result.lock_version)
        return result

    @router.post(
        "/tenants/{tenant_id}/review/assignments/{assignment_id}/release",
        response_model=AssignmentLeaseResponse,
        operation_id="releaseAssignment",
        responses={200: {"headers": LOCK_VERSION_RESPONSE_HEADERS}},
    )
    def release(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        request: Request,
        response: Response,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AssignmentLeaseResponse:
        result = context.review.release(
            session,
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            principal=principal,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
        set_lock_version_etag(response, result.lock_version)
        return result
