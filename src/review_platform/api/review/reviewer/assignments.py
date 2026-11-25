"""Reviewer assignment list route registration."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from review_platform.api.review.support import ReviewContext
from review_platform.auth.service import Principal
from review_platform.review.schemas import AssignmentSummary


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
        "/tenants/{tenant_id}/review/assignments",
        response_model=list[AssignmentSummary],
        operation_id="listOwnReviewAssignments",
    )
    def assignments(
        tenant_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> list[AssignmentSummary]:
        return context.review.list_assignments(session, tenant_id=tenant_id, principal=principal)
