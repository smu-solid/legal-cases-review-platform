"""Tenant-admin and super-admin role/status administration for the auth service."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.orm import Session

from review_platform.auth.base import (
    FINAL_SUPERUSER_LOCK_ID,
    ROLE_CAPABILITIES,
    TENANT_ROLES,
    AuthServiceBase,
)
from review_platform.auth.principal import Principal, now_utc
from review_platform.auth.roster import (
    list_tenant_reviewers_for_admin,
    provision_reviewer_roster_entry,
)
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.db.models import (
    GlobalRoleGrant,
    RoleGrant,
    ServerSession,
    Tenant,
    TenantMembership,
    User,
)


class RoleAdminMixin(AuthServiceBase):
    def invite_reviewer_to_roster(
        self,
        session: Session,
        *,
        actor: Principal,
        tenant_id: uuid.UUID,
        email: str,
        display_name: str | None,
        request_id: str,
    ) -> dict[str, Any]:
        return provision_reviewer_roster_entry(
            session,
            actor=actor,
            tenant_id=tenant_id,
            email=email,
            display_name=display_name,
            request_id=request_id,
            require_tenant_admin=self.require_tenant_admin,
            audit_key=self.audit_key,
            allowed_reviewer_domains=self.settings.allowed_reviewer_domains,
        )

    def tenant_memberships(self, session: Session, user_id: uuid.UUID) -> list[dict[str, Any]]:
        memberships = session.execute(
            select(TenantMembership, Tenant)
            .join(Tenant, Tenant.id == TenantMembership.tenant_id)
            .where(
                TenantMembership.user_id == user_id,
                TenantMembership.status == "active",
                Tenant.status == "active",
            )
        ).all()
        result: list[dict[str, Any]] = []
        for membership, tenant in memberships:
            roles = list(
                session.scalars(
                    select(RoleGrant.role_code).where(
                        RoleGrant.membership_id == membership.id,
                        RoleGrant.revoked_at.is_(None),
                    )
                )
            )
            capabilities = sorted(
                {capability for role in roles for capability in ROLE_CAPABILITIES[role]}
            )
            result.append(
                {
                    "membership_id": membership.id,
                    "tenant_id": tenant.id,
                    "tenant_key": tenant.key,
                    "roles": sorted(roles),
                    "capabilities": capabilities,
                }
            )
        return result

    def list_tenant_reviewers(
        self,
        session: Session,
        *,
        actor: Principal,
        tenant_id: uuid.UUID,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        return list_tenant_reviewers_for_admin(
            session,
            actor=actor,
            tenant_id=tenant_id,
            limit=limit,
            cursor=cursor,
            require_tenant_admin=self.require_tenant_admin,
        )

    def global_roles(self, session: Session, user_id: uuid.UUID) -> list[str]:
        current = now_utc()
        return list(
            session.scalars(
                select(GlobalRoleGrant.role_code).where(
                    GlobalRoleGrant.user_id == user_id,
                    GlobalRoleGrant.revoked_at.is_(None),
                    or_(
                        GlobalRoleGrant.expires_at.is_(None),
                        GlobalRoleGrant.expires_at > current,
                    ),
                )
            )
        )

    def require_super_admin(self, session: Session, principal: Principal) -> None:
        if "super_admin" not in self.global_roles(session, principal.user.id):
            raise APIError(403, "forbidden", "Forbidden", "The action is not permitted.")

    def require_tenant_admin(
        self, session: Session, principal: Principal, tenant_id: uuid.UUID
    ) -> None:
        if "super_admin" in self.global_roles(session, principal.user.id):
            return
        allowed = session.scalar(
            select(func.count())
            .select_from(TenantMembership)
            .join(RoleGrant, RoleGrant.membership_id == TenantMembership.id)
            .where(
                TenantMembership.user_id == principal.user.id,
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.status == "active",
                RoleGrant.role_code == "user_admin",
                RoleGrant.revoked_at.is_(None),
            )
        )
        if not allowed:
            raise APIError(403, "forbidden", "Forbidden", "The action is not permitted.")

    def set_tenant_role(
        self,
        session: Session,
        *,
        actor: Principal,
        membership_id: uuid.UUID,
        role_code: str,
        active: bool,
        request_id: str,
    ) -> None:
        if role_code not in TENANT_ROLES:
            raise APIError(422, "role_invalid", "Invalid role", "The role is not supported.")
        membership = session.get(TenantMembership, membership_id, with_for_update=True)
        if membership is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        self.require_tenant_admin(session, actor, membership.tenant_id)
        if actor.user.id == membership.user_id and role_code == "user_admin":
            raise APIError(
                403, "self_elevation_forbidden", "Forbidden", "Self-elevation is not permitted."
            )
        grant = session.scalar(
            select(RoleGrant).where(
                RoleGrant.membership_id == membership_id, RoleGrant.role_code == role_code
            )
        )
        if active:
            if grant is None:
                grant = RoleGrant(
                    membership_id=membership_id,
                    role_code=role_code,
                    granted_by=actor.user.id,
                )
                session.add(grant)
            else:
                grant.revoked_at = None
                grant.granted_by = actor.user.id
                grant.granted_at = now_utc()
        elif grant is not None:
            grant.revoked_at = now_utc()
        append_audit_event(
            session,
            actor_user_id=actor.user.id,
            actor_type="user",
            event_type="admin.tenant_role_changed",
            object_type="tenant_membership",
            object_id=str(membership_id),
            request_id=request_id,
            payload={"role": role_code, "active": active},
            key=self.audit_key,
        )

    def set_global_super_admin(
        self,
        session: Session,
        *,
        actor: Principal,
        target_user_id: uuid.UUID,
        active: bool,
        reason: str,
        expires_at: datetime | None,
        request_id: str,
    ) -> None:
        self.require_super_admin(session, actor)
        if actor.user.id == target_user_id and active:
            raise APIError(
                403, "self_elevation_forbidden", "Forbidden", "Self-elevation is not permitted."
            )
        target = session.get(User, target_user_id, with_for_update=True)
        if target is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": FINAL_SUPERUSER_LOCK_ID},
        )
        grant = session.scalar(
            select(GlobalRoleGrant).where(
                GlobalRoleGrant.user_id == target_user_id,
                GlobalRoleGrant.role_code == "super_admin",
            )
        )
        if active:
            current = now_utc()
            if target.status != "active" or target.password_hash is None:
                raise APIError(409, "user_unusable", "User unavailable", "The user must be active.")
            if expires_at is not None and (
                expires_at <= current
                or expires_at > current + timedelta(seconds=self.settings.global_role_max_seconds)
            ):
                raise APIError(
                    422,
                    "expiry_invalid",
                    "Invalid expiry",
                    "The expiry is outside the permitted window.",
                )
            if grant is None:
                grant = GlobalRoleGrant(
                    user_id=target_user_id,
                    granted_by=actor.user.id,
                    reason=reason,
                    expires_at=expires_at,
                )
                session.add(grant)
            else:
                grant.revoked_at = None
                grant.granted_by = actor.user.id
                grant.reason = reason
                grant.expires_at = expires_at
            target.authorization_epoch += 1
            self._revoke_user_sessions(session, target_user_id, "global_role_changed")
        elif grant is not None and grant.revoked_at is None:
            self._protect_final_superuser(session, target_user_id)
            grant.revoked_at = now_utc()
            target.authorization_epoch += 1
            self._revoke_user_sessions(session, target_user_id, "global_role_changed")
        append_audit_event(
            session,
            actor_user_id=actor.user.id,
            actor_type="user",
            event_type="admin.global_role_changed",
            object_type="user",
            object_id=str(target_user_id),
            request_id=request_id,
            payload={"role": "super_admin", "active": active, "reason": reason},
            key=self.audit_key,
        )

    def set_user_status(
        self,
        session: Session,
        *,
        actor: Principal,
        target_user_id: uuid.UUID,
        status: str,
        reason: str,
        request_id: str,
    ) -> None:
        self.require_super_admin(session, actor)
        if status not in {"active", "suspended"}:
            raise APIError(422, "status_invalid", "Invalid status", "The status is invalid.")
        target = session.get(User, target_user_id, with_for_update=True)
        if target is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        if status == "suspended":
            session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": FINAL_SUPERUSER_LOCK_ID},
            )
            self._protect_final_superuser(session, target_user_id)
            target.suspended_at = now_utc()
            target.suspension_reason = reason
        else:
            if target.password_hash is None:
                raise APIError(
                    409,
                    "activation_required",
                    "Activation required",
                    "The user must complete activation first.",
                )
            target.suspended_at = None
            target.suspension_reason = None
        target.status = status
        target.authorization_epoch += 1
        self._revoke_user_sessions(session, target_user_id, "user_status_changed")
        append_audit_event(
            session,
            actor_user_id=actor.user.id,
            actor_type="user",
            event_type="admin.user_status_changed",
            object_type="user",
            object_id=str(target_user_id),
            request_id=request_id,
            payload={"status": status, "reason": reason},
            key=self.audit_key,
        )

    def _protect_final_superuser(self, session: Session, target_user_id: uuid.UUID) -> None:
        target_is_super = session.scalar(
            select(func.count())
            .select_from(GlobalRoleGrant)
            .where(
                GlobalRoleGrant.user_id == target_user_id,
                GlobalRoleGrant.revoked_at.is_(None),
                GlobalRoleGrant.expires_at.is_(None),
            )
        )
        if not target_is_super:
            return
        usable = session.scalar(self._usable_superusers_query()) or 0
        if usable <= 1:
            raise APIError(
                409,
                "final_superuser_protected",
                "Final superuser protected",
                "At least one usable super administrator must remain.",
            )

    @staticmethod
    def _usable_superusers_query() -> Select[tuple[int]]:
        return (
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(GlobalRoleGrant, GlobalRoleGrant.user_id == User.id)
            .where(
                User.status == "active",
                GlobalRoleGrant.revoked_at.is_(None),
                GlobalRoleGrant.expires_at.is_(None),
            )
        )

    @staticmethod
    def _revoke_user_sessions(session: Session, user_id: uuid.UUID, reason: str) -> None:
        sessions = session.scalars(
            select(ServerSession).where(
                ServerSession.user_id == user_id, ServerSession.revoked_at.is_(None)
            )
        )
        for server_session in sessions:
            server_session.revoked_at = now_utc()
            server_session.revocation_reason = reason
