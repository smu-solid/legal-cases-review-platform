"""FastAPI application factory for the independent review platform."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from review_platform import __version__
from review_platform.api.router import register_routers
from review_platform.common.errors import (
    APIError,
    api_error_handler,
    http_error_handler,
    safe_error_context,
    unhandled_error_handler,
    validation_error_handler,
)
from review_platform.context import AppContext
from review_platform.settings import Settings

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$")
logger = logging.getLogger("review_platform")


def configure_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def emit_log(level: int, event: str, **fields: object) -> None:
    """Emit one JSON object with stable fields and no implicit request data."""

    level_name = logging.getLevelName(level)
    logger.log(
        level,
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "severity": level_name,
                "level": level_name.lower(),
                "event": event,
                **fields,
            },
            sort_keys=True,
        ),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    resolved = settings or Settings()
    context = AppContext(resolved)
    application = FastAPI(
        title="Review Platform API",
        version=__version__,
        description="Independent review-owned authentication and administration API.",
    )
    application.state.context = context
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.origin_strings),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-CSRF-Token",
            "X-Request-ID",
            "X-Correlation-ID",
            "Idempotency-Key",
            "If-Match",
        ],
        expose_headers=["X-Request-ID", "X-Correlation-ID", "ETag"],
    )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=list(resolved.allowed_hosts))
    application.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(StarletteHTTPException, http_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(Exception, unhandled_error_handler)

    @application.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.monotonic()
        incoming = request.headers.get("X-Request-ID")
        request_id = (
            incoming if incoming and REQUEST_ID_PATTERN.fullmatch(incoming) else uuid.uuid4().hex
        )
        incoming_correlation = request.headers.get("X-Correlation-ID")
        correlation_id = (
            incoming_correlation
            if incoming_correlation and REQUEST_ID_PATTERN.fullmatch(incoming_correlation)
            else request_id
        )
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        except Exception as exc:
            emit_log(
                logging.ERROR,
                "request.unhandled",
                request_id=request_id,
                correlation_id=correlation_id,
                **safe_error_context(exc),
            )
            raise
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if resolved.environment == "development" and request.url.path == "/docs":
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; "
                "script-src https://cdn.jsdelivr.net 'unsafe-inline'; "
                "style-src https://cdn.jsdelivr.net 'unsafe-inline'; "
                "img-src https://fastapi.tiangolo.com data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'"
            )
        if request.url.path.endswith("/source-render/body"):
            # The sanitized source artifact is delivered for a same-origin sandboxed iframe: allow
            # inline styles from the review-owned wrapper, block every other resource, disable
            # scripts via the sandbox directive, and permit only same-origin framing.
            response.headers["Content-Security-Policy"] = (
                "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; "
                "frame-ancestors 'self'"
            )
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/v1"):
            response.headers["Cache-Control"] = "no-store"
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        emit_log(
            logging.INFO,
            "request.completed",
            request_id=request_id,
            correlation_id=correlation_id,
            method=request.method,
            route=route_path,
            route_name=getattr(route, "name", "unmatched"),
            status_code=response.status_code,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            user_id=getattr(request.state, "user_id", None),
        )
        return response

    register_routers(application, context)
    return application
