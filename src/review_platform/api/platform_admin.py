"""Platform administration routes: reviewer roster and privileged role/status management."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy.orm import Session

from review_platform.api.dependencies import enforce_session_csrf, get_principal, get_session
from review_platform.api.params import DEFAULT_LIMIT, PageCursor, PageLimit
from review_platform.auth.service import Principal
from review_platform.common.errors import APIError
from review_platform.common.schemas import StatusResponse, StrictModel
from review_platform.context import AppContext
from review_platform.email.message import EmailDeliveryError
from review_platform.email.templates import build_password_reset_link, build_reviewer_invitation


class TenantReviewerRosterItem(StrictModel):
    user_id: uuid.UUID
    membership_id: uuid.UUID
    display_name: str
    user_status: Literal["pending", "active", "suspended"]
    membership_status: Literal["pending", "active", "suspended"]
    roles: list[str]
    # Allocation-facing truth: active user + active membership. ``roster_status`` is the
    # admin-facing lifecycle label (pending/active/disabled/ineligible).
    eligible: bool
    roster_status: Literal["pending", "active", "disabled", "ineligible"]
    # Activity + workload enrichment. first_seen = first verified login (activation); last_seen =
    # latest session activity; both null for an invited reviewer who has never logged in.
    # claimed_count is the reviewer's current (in-progress) workload; submitted is terminal.
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    total_assignments: int = 0
    submitted_count: int = 0
    claimed_count: int = 0
    released_count: int = 0


class TenantReviewerRosterPage(StrictModel):
    items: list[TenantReviewerRosterItem]
    next_cursor: str | None = None
    has_more: bool = False


class ReviewerInviteRequest(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)


class ReviewerInviteResponse(StrictModel):
    user_id: uuid.UUID
    membership_id: uuid.UUID
    user_status: Literal["pending", "active", "suspended"]
    membership_status: Literal["pending", "active", "suspended"]
    # "sent": a new invitation email was accepted by the configured sender; "resent": the same
    # still-pending reviewer was re-invited and got a reminder; "not_sent_already_active": the
    # reviewer was already active, so no email is sent (never re-notify an active reviewer).
    invitation_email: Literal["sent", "resent", "not_sent_already_active"]


class ReauthenticatedRequest(StrictModel):
    password: str = Field(min_length=1, max_length=1_024)


class AdminPasswordResetResponse(StrictModel):
    # The one-time reset token is returned only outside production (local/dev testing); in
    # production the reviewer receives it exclusively by email and the field is null.
    reset_token: str | None = None
    email_sent: bool


class TenantRoleRequest(ReauthenticatedRequest):
    role: str = Field(min_length=1, max_length=40)
    active: bool


class UserStatusRequest(ReauthenticatedRequest):
    status: Literal["active", "suspended"]
    reason: str = Field(min_length=1, max_length=500)


class GlobalRoleRequest(ReauthenticatedRequest):
    active: bool
    reason: str = Field(min_length=1, max_length=500)
    expires_at: datetime | None = None


def create_platform_admin_router(context: AppContext) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["Administration"])

    @router.get(
        "/tenants/{tenant_id}/reviewers",
        response_model=TenantReviewerRosterPage,
        operation_id="listTenantReviewers",
    )
    def list_reviewers(
        tenant_id: uuid.UUID,
        principal: Annotated[Principal, Depends(get_principal)],
        session: Annotated[Session, Depends(get_session)],
        limit: PageLimit = DEFAULT_LIMIT,
        cursor: PageCursor = None,
    ) -> TenantReviewerRosterPage:
        return TenantReviewerRosterPage.model_validate(
            context.auth.list_tenant_reviewers(
                session,
                actor=principal,
                tenant_id=tenant_id,
                limit=limit,
                cursor=cursor,
            )
        )

    @router.post(
        "/tenants/{tenant_id}/reviewers",
        response_model=ReviewerInviteResponse,
        status_code=201,
        operation_id="inviteReviewerToRoster",
    )
    def invite_reviewer(
        tenant_id: uuid.UUID,
        body: ReviewerInviteRequest,
        request: Request,
        principal: Annotated[Principal, Depends(enforce_session_csrf)],
        session: Annotated[Session, Depends(get_session)],
    ) -> ReviewerInviteResponse:
        outcome = context.auth.invite_reviewer_to_roster(
            session,
            actor=principal,
            tenant_id=tenant_id,
            email=body.email,
            display_name=body.display_name,
            request_id=request.state.request_id,
        )
        invitation_outcome = outcome["invitation_outcome"]
        invitation_email: Literal["sent", "resent", "not_sent_already_active"]
        if invitation_outcome == "already_active":
            invitation_email = "not_sent_already_active"
        else:
            settings = context.settings
            activation_token = context.auth.issue_activation(session, outcome["user_id"])
            activation_url = (
                f"{settings.app_base_url.rstrip('/')}/activate"
                f"?token={quote(activation_token, safe='')}"
            )
            message = build_reviewer_invitation(
                to_address=outcome["reviewer_email"],
                display_name=outcome["reviewer_display_name"],
                tenant_name=outcome["tenant_name"],
                app_url=activation_url,
                support_contact=settings.support_contact,
                reminder=invitation_outcome == "reinvited",
            )
            try:
                context.email.send(message)
            except EmailDeliveryError as exc:
                raise APIError(
                    502,
                    "invitation_email_delivery_failed",
                    "Invitation email failed",
                    "The invitation email could not be delivered, so the reviewer was not added.",
                ) from exc
            invitation_email = "resent" if invitation_outcome == "reinvited" else "sent"
        return ReviewerInviteResponse.model_validate(
            {
                "user_id": outcome["user_id"],
                "membership_id": outcome["membership_id"],
                "user_status": outcome["user_status"],
                "membership_status": outcome["membership_status"],
                "invitation_email": invitation_email,
            }
        )

    @router.post(
        "/tenants/{tenant_id}/users/{user_id}/password-reset",
        response_model=AdminPasswordResetResponse,
        operation_id="triggerUserPasswordReset",
    )
    def trigger_password_reset(
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        body: ReauthenticatedRequest,
        request: Request,
        principal: Annotated[Principal, Depends(enforce_session_csrf)],
        session: Annotated[Session, Depends(get_session)],
    ) -> AdminPasswordResetResponse:
        settings = context.settings
        context.auth.verify_reauthentication(principal, body.password)
        outcome = context.auth.admin_trigger_password_reset(
            session,
            actor=principal,
            tenant_id=tenant_id,
            target_user_id=user_id,
            request_id=request.state.request_id,
        )
        # Send before the request transaction commits: a delivery failure raises and rolls back
        # the reset challenge, so no unreachable reset token is persisted.
        context.email.send(
            build_password_reset_link(
                to_address=outcome.reviewer_email,
                reset_url=settings.password_reset_link(outcome.reset_token),
                expiry_hours=max(1, settings.password_reset_ttl_seconds // 3600),
                support_contact=settings.support_contact,
            )
        )
        return AdminPasswordResetResponse(
            reset_token=outcome.reset_token if settings.expose_raw_account_tokens else None,
            email_sent=True,
        )

    @router.put(
        "/memberships/{membership_id}/role",
        response_model=StatusResponse,
        operation_id="setTenantRole",
    )
    def set_tenant_role(
        membership_id: uuid.UUID,
        body: TenantRoleRequest,
        request: Request,
        principal: Annotated[Principal, Depends(enforce_session_csrf)],
        session: Annotated[Session, Depends(get_session)],
    ) -> StatusResponse:
        context.auth.verify_reauthentication(principal, body.password)
        context.auth.set_tenant_role(
            session,
            actor=principal,
            membership_id=membership_id,
            role_code=body.role,
            active=body.active,
            request_id=request.state.request_id,
        )
        return StatusResponse(status="updated")

    @router.put(
        "/users/{user_id}/status",
        response_model=StatusResponse,
        operation_id="setUserStatus",
    )
    def set_user_status(
        user_id: uuid.UUID,
        body: UserStatusRequest,
        request: Request,
        principal: Annotated[Principal, Depends(enforce_session_csrf)],
        session: Annotated[Session, Depends(get_session)],
    ) -> StatusResponse:
        context.auth.verify_reauthentication(principal, body.password)
        context.auth.set_user_status(
            session,
            actor=principal,
            target_user_id=user_id,
            status=body.status,
            reason=body.reason,
            request_id=request.state.request_id,
        )
        return StatusResponse(status="updated")

    @router.put(
        "/users/{user_id}/global-role",
        response_model=StatusResponse,
        operation_id="setGlobalRole",
    )
    def set_global_role(
        user_id: uuid.UUID,
        body: GlobalRoleRequest,
        request: Request,
        principal: Annotated[Principal, Depends(enforce_session_csrf)],
        session: Annotated[Session, Depends(get_session)],
    ) -> StatusResponse:
        context.auth.verify_reauthentication(principal, body.password)
        context.auth.set_global_super_admin(
            session,
            actor=principal,
            target_user_id=user_id,
            active=body.active,
            reason=body.reason,
            expires_at=body.expires_at,
            request_id=request.state.request_id,
        )
        return StatusResponse(status="updated")

    return router
