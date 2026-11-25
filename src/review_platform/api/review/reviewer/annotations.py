"""Reviewer annotation route registration."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from review_platform.api.params import (
    LOCK_VERSION_RESPONSE_HEADERS,
    IdempotencyKey,
    IfMatch,
    expected_version,
    set_lock_version_etag,
)
from review_platform.api.review.support import (
    ReviewContext,
)
from review_platform.auth.service import Principal
from review_platform.review.schemas import AnnotationInput, AnnotationRevisionResponse


def register_routes(
    router: APIRouter,
    context: ReviewContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> None:
    del principal_dependency

    def persist_annotation(
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        body: AnnotationInput,
        request: Request,
        response: Response,
        if_match: str,
        idempotency_key: str,
        principal: Principal,
        session: Session,
        state: str,
    ) -> AnnotationRevisionResponse:
        result = context.review.save_annotation(
            session,
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            principal=principal,
            annotation=body,
            state=cast(Literal["draft", "submitted"], state),
            expected_version=expected_version(if_match),
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
        set_lock_version_etag(response, result.lock_version)
        return result

    @router.put(
        "/tenants/{tenant_id}/review/assignments/{assignment_id}/draft",
        response_model=AnnotationRevisionResponse,
        operation_id="saveAnnotationDraft",
        responses={200: {"headers": LOCK_VERSION_RESPONSE_HEADERS}},
    )
    def save_draft(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        body: AnnotationInput,
        request: Request,
        response: Response,
        idempotency_key: IdempotencyKey,
        if_match: IfMatch,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AnnotationRevisionResponse:
        return persist_annotation(
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            body=body,
            request=request,
            response=response,
            if_match=if_match,
            idempotency_key=idempotency_key,
            principal=principal,
            session=session,
            state="draft",
        )

    @router.post(
        "/tenants/{tenant_id}/review/assignments/{assignment_id}/submit",
        response_model=AnnotationRevisionResponse,
        operation_id="submitAnnotation",
        status_code=201,
        responses={201: {"headers": LOCK_VERSION_RESPONSE_HEADERS}},
    )
    def submit(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        body: AnnotationInput,
        request: Request,
        response: Response,
        idempotency_key: IdempotencyKey,
        if_match: IfMatch,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AnnotationRevisionResponse:
        return persist_annotation(
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            body=body,
            request=request,
            response=response,
            if_match=if_match,
            idempotency_key=idempotency_key,
            principal=principal,
            session=session,
            state="submitted",
        )
