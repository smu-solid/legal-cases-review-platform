"""Central API router registration.

Wires every router factory to the shared request-scoped dependencies and
includes them on the application in a stable order.
"""

from __future__ import annotations

from fastapi import FastAPI

from review_platform.api.allocation import create_allocation_router
from review_platform.api.auth import create_auth_router
from review_platform.api.dependencies import (
    enforce_session_csrf,
    get_principal,
    get_session,
)
from review_platform.api.health import create_health_router
from review_platform.api.platform_admin import create_platform_admin_router
from review_platform.api.review import create_review_router
from review_platform.context import AppContext


def register_routers(application: FastAPI, context: AppContext) -> None:
    application.include_router(create_health_router(context))
    application.include_router(create_auth_router(context))
    application.include_router(create_platform_admin_router(context))
    application.include_router(
        create_review_router(
            context,
            session_dependency=get_session,
            principal_dependency=get_principal,
            csrf_dependency=enforce_session_csrf,
        )
    )
    application.include_router(
        create_allocation_router(
            context,
            session_dependency=get_session,
            principal_dependency=get_principal,
            csrf_dependency=enforce_session_csrf,
        )
    )
