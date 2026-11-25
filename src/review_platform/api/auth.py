"""Password sign-in, account activation, session and CSRF routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy.orm import Session

from review_platform.api.dependencies import (
    enforce_browser_mutation,
    enforce_session_csrf,
    get_principal,
    get_session,
    set_csrf_cookie,
)
from review_platform.auth.base import capability_flags, default_landing
from review_platform.auth.service import Principal
from review_platform.common.schemas import StatusResponse, StrictModel
from review_platform.context import AppContext
from review_platform.security import new_token
from review_platform.settings import CSRF_COOKIE, SESSION_COOKIE


class CsrfResponse(StrictModel):
    csrf_token: str


class MembershipResponse(StrictModel):
    membership_id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_key: str
    roles: list[str]
    capabilities: list[str]


class CapabilityFlags(StrictModel):
    can_administer: bool
    can_review: bool
    can_adjudicate: bool
    can_invite_reviewers: bool
    can_allocate: bool
    can_manage_campaigns: bool


class MeResponse(StrictModel):
    id: uuid.UUID
    email: str
    subject: str | None = None
    display_name: str
    status: str
    global_roles: list[str]
    global_capabilities: list[str]
    memberships: list[MembershipResponse]
    active_tenant: uuid.UUID | None
    default_landing: str | None
    capabilities: CapabilityFlags
    session_expires_at: datetime | None


class LoginRequest(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class AccountPasswordRequest(StrictModel):
    token: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=1024)


def create_auth_router(context: AppContext) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
    settings = context.settings

    @router.post("/activate", response_model=StatusResponse, operation_id="activateAccount")
    def activate(
        body: AccountPasswordRequest,
        _csrf: Annotated[str, Depends(enforce_browser_mutation)],
        session: Annotated[Session, Depends(get_session)],
    ) -> StatusResponse:
        context.auth.set_account_password(
            session, raw_token=body.token, password=body.password, activation=True
        )
        return StatusResponse(status="activated")

    @router.post(
        "/reset-password", response_model=StatusResponse, operation_id="resetAccountPassword"
    )
    def reset_password(
        body: AccountPasswordRequest,
        _csrf: Annotated[str, Depends(enforce_browser_mutation)],
        session: Annotated[Session, Depends(get_session)],
    ) -> StatusResponse:
        context.auth.set_account_password(
            session, raw_token=body.token, password=body.password, activation=False
        )
        return StatusResponse(status="password_updated")

    @router.post("/login", response_model=StatusResponse, operation_id="login")
    def login(
        body: LoginRequest,
        request: Request,
        response: Response,
        raw_csrf: Annotated[str, Depends(enforce_browser_mutation)],
        session: Annotated[Session, Depends(get_session)],
    ) -> StatusResponse:
        from review_platform.rate_limit import enforce_rate_limit
        from review_platform.security import normalize_email

        with context.database.session() as rate_session, rate_session.begin():
            enforce_rate_limit(
                rate_session,
                scope="login",
                identity=normalize_email(body.email),
                key=context.auth.session_key,
                limit=20,
                window_seconds=settings.auth_rate_window_seconds,
            )
        raw_token, _principal = context.auth.login(
            session,
            email=body.email,
            password=body.password,
            raw_csrf=raw_csrf,
            request_id=request.state.request_id,
        )
        response.set_cookie(
            SESSION_COOKIE,
            raw_token,
            secure=settings.cookie_secure,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=settings.session_absolute_seconds,
        )
        return StatusResponse(status="authenticated")

    @router.get("/csrf", response_model=CsrfResponse, operation_id="getCsrfToken")
    def csrf(
        response: Response,
        # Unused in the body: the dependency itself fail-closes with 503 when the database is
        # unavailable, so CSRF issuance (an auth-adjacent route) degrades the same way as every
        # other auth route rather than silently succeeding while the app is otherwise down.
        request: Request,
        session: Annotated[Session, Depends(get_session)],
    ) -> CsrfResponse:
        raw_csrf = request.cookies.get(CSRF_COOKIE) or new_token()
        if request.cookies.get(SESSION_COOKIE):
            from review_platform.common.errors import APIError

            try:
                principal = context.auth.resolve_principal(
                    session, request.cookies.get(SESSION_COOKIE)
                )
                if not context.auth.verify_session_csrf(principal, raw_csrf):
                    raw_csrf = new_token()
                    context.auth.rotate_csrf(principal, raw_csrf)
            except APIError:
                raw_csrf = new_token()
        set_csrf_cookie(response, settings, raw_csrf)
        return CsrfResponse(csrf_token=raw_csrf)

    @router.post("/logout", response_model=StatusResponse, operation_id="logout")
    def logout(
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(enforce_session_csrf)],
        session: Annotated[Session, Depends(get_session)],
    ) -> StatusResponse:
        context.auth.logout(session, principal, request_id=request.state.request_id)
        response.delete_cookie(
            SESSION_COOKIE, path="/", secure=settings.cookie_secure, httponly=True
        )
        response.delete_cookie(CSRF_COOKIE, path="/", secure=settings.cookie_secure)
        return StatusResponse(status="logged_out")

    @router.get("/me", response_model=MeResponse, operation_id="getCurrentUser")
    def me(
        request: Request,
        principal: Annotated[Principal, Depends(get_principal)],
        session: Annotated[Session, Depends(get_session)],
    ) -> MeResponse:
        global_roles = context.auth.global_roles(session, principal.user.id)
        memberships = [
            MembershipResponse.model_validate(item)
            for item in context.auth.tenant_memberships(session, principal.user.id)
        ]
        all_roles = set(global_roles)
        for membership in memberships:
            all_roles.update(membership.roles)
        flags = capability_flags(all_roles)
        session_expires_at = (
            principal.server_session.absolute_expires_at
            if principal.server_session is not None
            else None
        )
        return MeResponse(
            id=principal.user.id,
            email=principal.user.email_normalized,
            subject=getattr(request.state, "identity_subject", None),
            display_name=principal.user.display_name,
            status=principal.user.status,
            global_roles=sorted(global_roles),
            global_capabilities=["global:admin"] if "super_admin" in global_roles else [],
            memberships=memberships,
            # First membership by query order; disambiguates the client's ``memberships[0]``
            # assumption. ``None`` for a rostered identity with no active tenant membership.
            active_tenant=memberships[0].tenant_id if memberships else None,
            default_landing=default_landing(flags),
            capabilities=CapabilityFlags(**flags),
            session_expires_at=session_expires_at,
        )

    return router
