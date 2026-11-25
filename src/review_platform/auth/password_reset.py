"""Administrator-triggered password reset for the auth service.

An administrator-triggered reset mints a one-time reset link emailed to the reviewer — the
administrator never sees or sets the password. This is the only remaining password-reset flow:
the self-service ``forgot-password``/``reset-password`` pair was removed with the rest of the
legacy self-service password-credential auth surface (see ``api/auth_custom.py`` history); this
mixin now exists only in support of the admin step-up-reauth-gated actions in
``api/platform_admin.py``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.principal import Principal, now_utc
from review_platform.auth.roles import RoleAdminMixin
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.db.models import PasswordResetChallenge, Tenant, TenantMembership, User
from review_platform.security import new_token, token_digest


@dataclass(frozen=True)
class AdminResetOutcome:
    reset_token: str
    reviewer_email: str
    tenant_label: str


class PasswordResetMixin(RoleAdminMixin):
    def admin_trigger_password_reset(
        self,
        session: Session,
        *,
        actor: Principal,
        tenant_id: uuid.UUID,
        target_user_id: uuid.UUID,
        request_id: str,
    ) -> AdminResetOutcome:
        """Mint a one-time reset token for a tenant member; the admin never sees the password."""

        self.require_tenant_admin(session, actor, tenant_id)
        target = session.get(User, target_user_id, with_for_update=True)
        membership = session.scalar(
            select(TenantMembership).where(
                TenantMembership.user_id == target_user_id,
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.status == "active",
            )
        )
        if target is None or membership is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        if target.status != "active" or target.password_hash is None:
            raise APIError(
                409,
                "user_unusable",
                "User unavailable",
                "The account must complete activation before a password reset.",
            )
        raw_token = new_token()
        session.add(
            PasswordResetChallenge(
                user_id=target.id,
                token_digest=token_digest(raw_token, self.activation_key),
                expires_at=now_utc() + timedelta(seconds=self.settings.password_reset_ttl_seconds),
                request_source="admin",
                requested_by_user_id=actor.user.id,
            )
        )
        tenant = session.get(Tenant, tenant_id)
        append_audit_event(
            session,
            actor_user_id=actor.user.id,
            actor_type="user",
            event_type="admin.password_reset_triggered",
            object_type="user",
            object_id=str(target.id),
            request_id=request_id,
            payload={"tenant_id": str(tenant_id)},
            key=self.audit_key,
        )
        return AdminResetOutcome(
            reset_token=raw_token,
            reviewer_email=target.email_normalized,
            tenant_label=tenant.name if tenant is not None else "your review workspace",
        )
