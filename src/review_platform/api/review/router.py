"""HTTP routes for the review vertical slice.

Routes are grouped by audience across sibling modules and registered onto one ``/api/v1`` router so
the published contract is unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from review_platform.api.review.adjudication import register_routes as register_adjudication_routes
from review_platform.api.review.adjudication_source_render import (
    register_routes as register_adjudication_source_render_routes,
)
from review_platform.api.review.campaign_admin import (
    register_routes as register_campaign_admin_routes,
)
from review_platform.api.review.campaign_lifecycle import (
    register_routes as register_campaign_lifecycle_routes,
)
from review_platform.api.review.proposal_adjudication import (
    register_routes as register_proposal_routes,
)
from review_platform.api.review.reviewer.routes import register_routes as register_reviewer_routes
from review_platform.api.review.support import ReviewContext


def create_review_router(
    context: ReviewContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Review"])
    deps: dict[str, Callable[..., Any]] = {
        "session_dependency": session_dependency,
        "principal_dependency": principal_dependency,
        "csrf_dependency": csrf_dependency,
    }
    register_campaign_admin_routes(router, context, **deps)
    register_campaign_lifecycle_routes(router, context, **deps)
    register_reviewer_routes(router, context, **deps)
    register_adjudication_routes(router, context, **deps)
    register_proposal_routes(router, context, **deps)
    register_adjudication_source_render_routes(router, context, **deps)
    return router
