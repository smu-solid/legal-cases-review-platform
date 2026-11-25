"""Reviewer-facing review route registration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from review_platform.api.review.reviewer.annotations import register_routes as register_annotations
from review_platform.api.review.reviewer.assignments import register_routes as register_assignments
from review_platform.api.review.reviewer.bundles import register_routes as register_bundles
from review_platform.api.review.reviewer.case_submission import (
    register_routes as register_case_submission,
)
from review_platform.api.review.reviewer.item_answers import (
    register_routes as register_item_answers,
)
from review_platform.api.review.reviewer.lifecycle import register_routes as register_lifecycle
from review_platform.api.review.reviewer.proposals import register_routes as register_proposals
from review_platform.api.review.reviewer.queue import register_routes as register_queue
from review_platform.api.review.reviewer.source_render import (
    register_routes as register_source_render,
)
from review_platform.api.review.support import ReviewContext


def register_routes(
    router: APIRouter,
    context: ReviewContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> None:
    deps: dict[str, Callable[..., Any]] = {
        "session_dependency": session_dependency,
        "principal_dependency": principal_dependency,
        "csrf_dependency": csrf_dependency,
    }
    register_queue(router, context, **deps)
    register_lifecycle(router, context, **deps)
    register_assignments(router, context, **deps)
    register_bundles(router, context, **deps)
    register_source_render(router, context, **deps)
    register_annotations(router, context, **deps)
    register_item_answers(router, context, **deps)
    register_case_submission(router, context, **deps)
    register_proposals(router, context, **deps)
