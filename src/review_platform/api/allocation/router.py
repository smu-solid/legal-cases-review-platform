"""Allocation administration router composition."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from review_platform.api.allocation.incremental import (
    register_routes as register_incremental_routes,
)
from review_platform.api.allocation.runs import register_routes as register_run_routes
from review_platform.api.allocation.support import AllocationContext


def create_allocation_router(
    context: AllocationContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["Allocation"])
    deps: dict[str, Callable[..., Any]] = {
        "session_dependency": session_dependency,
        "principal_dependency": principal_dependency,
        "csrf_dependency": csrf_dependency,
    }
    register_run_routes(router, context, **deps)
    register_incremental_routes(router, context, **deps)
    return router
