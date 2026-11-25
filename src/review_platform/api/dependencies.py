"""Request-scoped FastAPI dependencies shared across routers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Cookie, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.errors import APIError
from review_platform.context import AppContext
from review_platform.db.session import DatabaseUnavailableError
from review_platform.security import constant_time_equal
from review_platform.settings import CSRF_COOKIE, SESSION_COOKIE, Settings


def get_context(request: Request) -> AppContext:
    return cast(AppContext, request.app.state.context)


def get_session(context: Annotated[AppContext, Depends(get_context)]) -> Iterator[Session]:
    try:
        with context.database.session() as session, session.begin():
            yield session
    except DatabaseUnavailableError as exc:
        raise APIError(
            503,
            "service_unavailable",
            "Service unavailable",
            "The review database is unavailable.",
        ) from exc


def get_principal(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    context: Annotated[AppContext, Depends(get_context)],
) -> Principal:
    principal = context.auth.resolve_principal(session, request.cookies.get(SESSION_COOKIE))
    request.state.principal = principal
    request.state.user_id = str(principal.user.id)
    return principal


def _has_request_body(request: Request) -> bool:
    """True when the request declares a non-empty body via Content-Length or chunked encoding."""

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            return int(content_length) > 0
        except ValueError:
            return True
    # No Content-Length: treat a chunked/streamed body as present, otherwise body-less.
    return request.headers.get("transfer-encoding") is not None


def enforce_browser_mutation(
    request: Request,
    context: Annotated[AppContext, Depends(get_context)],
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
    origin: Annotated[str | None, Header(alias="Origin")] = None,
    content_type: Annotated[str | None, Header(alias="Content-Type")] = None,
) -> str:
    if origin not in context.settings.origin_strings:
        raise APIError(403, "csrf_failed", "CSRF validation failed", "The request was rejected.")
    # Require a JSON media type only when the request actually carries a body. Body-less browser
    # mutations (logout, claim/lease renew/reopen/release) legitimately send no Content-Type, and
    # rejecting them with 415 broke the real SPA logout. CSRF is still enforced below: the custom
    # X-CSRF-Token header forces a CORS preflight cross-origin, and the header must match the cookie
    # (double submit) and the server-session token, so dropping the media-type gate for empty bodies
    # does not weaken CSRF protection. A body without a JSON content type is still rejected.
    if _has_request_body(request) and (
        content_type is None or not content_type.lower().startswith("application/json")
    ):
        raise APIError(
            415,
            "unsupported_media_type",
            "Unsupported media type",
            "JSON content is required.",
        )
    if not constant_time_equal(csrf_header, csrf_cookie):
        raise APIError(403, "csrf_failed", "CSRF validation failed", "The request was rejected.")
    return cast(str, csrf_header)


def enforce_session_csrf(
    raw_csrf: Annotated[str, Depends(enforce_browser_mutation)],
    principal: Annotated[Principal, Depends(get_principal)],
    context: Annotated[AppContext, Depends(get_context)],
) -> Principal:
    if not context.auth.verify_session_csrf(principal, raw_csrf):
        raise APIError(403, "csrf_failed", "CSRF validation failed", "The request was rejected.")
    return principal


def set_csrf_cookie(
    response: Response, settings: Settings, token: str, max_age: int | None = None
) -> None:
    response.set_cookie(
        CSRF_COOKIE,
        token,
        max_age=max_age if max_age is not None else settings.session_absolute_seconds,
        secure=settings.cookie_secure,
        httponly=False,
        samesite="lax",
        path="/",
    )
