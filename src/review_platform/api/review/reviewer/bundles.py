"""Reviewer bundle read route registration."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from review_platform.api.params import LOCK_VERSION_RESPONSE_HEADERS, set_lock_version_etag
from review_platform.api.review.support import ReviewContext
from review_platform.auth.service import Principal
from review_platform.review.schemas import AssignmentBundle, ReviewerGroupingBundle


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
        "/tenants/{tenant_id}/review/assignments/{assignment_id}/bundle",
        response_model=AssignmentBundle,
        operation_id="getOwnAssignmentBundle",
        responses={200: {"headers": LOCK_VERSION_RESPONSE_HEADERS}},
    )
    def bundle(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        response: Response,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> AssignmentBundle:
        result = context.review.bundle(
            session,
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            principal=principal,
        )
        set_lock_version_etag(response, result.assignment.lock_version)
        return result

    @router.get(
        "/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle",
        response_model=ReviewerGroupingBundle,
        operation_id="getGroupedReviewBundle",
        responses={200: {"headers": LOCK_VERSION_RESPONSE_HEADERS}},
    )
    def grouped_bundle(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        response: Response,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> ReviewerGroupingBundle:
        result = context.review.grouped_bundle(
            session,
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            principal=principal,
            artifact_store=context.artifact_store,
        )
        set_lock_version_etag(response, result.lock_version)
        return result
