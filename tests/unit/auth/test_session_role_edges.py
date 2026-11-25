from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import AuthService, Principal
from review_platform.db.models import (
    GlobalRoleGrant,
    RoleGrant,
    TenantMembership,
    User,
)
from review_platform.settings import Settings
from tests.support.auth_service import add_active_user, admin_principal, assert_api_error
from tests.support.identities import AdminIdentity


def test_session_and_tenant_role_edge_cases(
    db_session: Session, settings: Settings, admin: AdminIdentity
) -> None:
    service = AuthService(settings)
    principal = admin_principal(db_session, settings, admin)
    assert_api_error(
        "authentication_required", lambda: service.resolve_principal(db_session, "unknown-session")
    )
    assert_api_error(
        "not_found",
        lambda: service.set_tenant_role(
            db_session,
            actor=principal,
            membership_id=uuid.uuid4(),
            role_code="reviewer",
            active=True,
            request_id="edge",
        ),
    )
    assert_api_error(
        "self_elevation_forbidden",
        lambda: service.set_tenant_role(
            db_session,
            actor=principal,
            membership_id=admin.membership_id,
            role_code="user_admin",
            active=True,
            request_id="edge",
        ),
    )
    user = add_active_user(db_session, settings, "roles@example.test")
    membership = TenantMembership(tenant_id=admin.tenant_id, user_id=user.id, status="active")
    db_session.add(membership)
    db_session.flush()
    for active in (True, False, True):
        service.set_tenant_role(
            db_session,
            actor=principal,
            membership_id=membership.id,
            role_code="reviewer",
            active=active,
            request_id="edge",
        )
    grant = db_session.scalar(
        select(RoleGrant).where(
            RoleGrant.membership_id == membership.id, RoleGrant.role_code == "reviewer"
        )
    )
    assert grant is not None and grant.revoked_at is None
    service.set_tenant_role(
        db_session,
        actor=principal,
        membership_id=membership.id,
        role_code="auditor",
        active=False,
        request_id="edge",
    )


def test_user_admin_non_global_tenant_permission(
    db_session: Session, settings: Settings, admin: AdminIdentity
) -> None:
    service = AuthService(settings)
    user = add_active_user(db_session, settings, "tenant-admin@example.test")
    membership = TenantMembership(tenant_id=admin.tenant_id, user_id=user.id, status="active")
    db_session.add(membership)
    db_session.flush()
    db_session.add(
        RoleGrant(
            membership_id=membership.id,
            role_code="user_admin",
            granted_by=admin.user_id,
        )
    )
    principal = Principal(user)
    roster_entry = service.invite_reviewer_to_roster(
        db_session,
        actor=principal,
        tenant_id=admin.tenant_id,
        email="allowed@example.test",
        display_name=None,
        request_id="edge",
    )
    assert roster_entry
    assert_api_error(
        "forbidden",
        lambda: service.invite_reviewer_to_roster(
            db_session,
            actor=principal,
            tenant_id=uuid.uuid4(),
            email="denied@example.test",
            display_name=None,
            request_id="edge",
        ),
    )
    assert_api_error("forbidden", lambda: service.require_super_admin(db_session, principal))


def test_global_role_and_user_status_edge_cases(
    db_session: Session, settings: Settings, admin: AdminIdentity
) -> None:
    service = AuthService(settings)
    principal = admin_principal(db_session, settings, admin)
    assert_api_error(
        "self_elevation_forbidden",
        lambda: service.set_global_super_admin(
            db_session,
            actor=principal,
            target_user_id=admin.user_id,
            active=True,
            reason="self",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            request_id="edge",
        ),
    )
    assert_api_error(
        "not_found",
        lambda: service.set_global_super_admin(
            db_session,
            actor=principal,
            target_user_id=uuid.uuid4(),
            active=True,
            reason="missing",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            request_id="edge",
        ),
    )
    target = add_active_user(db_session, settings, "global@example.test")
    unusable = User(email_normalized="unusable@example.test", display_name="Unusable")
    db_session.add(unusable)
    db_session.flush()
    assert_api_error(
        "user_unusable",
        lambda: service.set_global_super_admin(
            db_session,
            actor=principal,
            target_user_id=unusable.id,
            active=True,
            reason="invalid target",
            expires_at=None,
            request_id="edge",
        ),
    )
    service.set_global_super_admin(
        db_session,
        actor=principal,
        target_user_id=target.id,
        active=False,
        reason="already absent",
        expires_at=None,
        request_id="edge",
    )
    assert_api_error(
        "expiry_invalid",
        lambda: service.set_global_super_admin(
            db_session,
            actor=principal,
            target_user_id=target.id,
            active=True,
            reason="invalid",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            request_id="edge",
        ),
    )
    assert_api_error(
        "expiry_invalid",
        lambda: service.set_global_super_admin(
            db_session,
            actor=principal,
            target_user_id=target.id,
            active=True,
            reason="too long",
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.global_role_max_seconds + 1),
            request_id="edge",
        ),
    )
    future = datetime.now(UTC) + timedelta(hours=1)
    service.set_global_super_admin(
        db_session,
        actor=principal,
        target_user_id=target.id,
        active=True,
        reason="grant",
        expires_at=future,
        request_id="edge",
    )
    service.set_global_super_admin(
        db_session,
        actor=principal,
        target_user_id=target.id,
        active=False,
        reason="revoke",
        expires_at=None,
        request_id="edge",
    )
    service.set_global_super_admin(
        db_session,
        actor=principal,
        target_user_id=target.id,
        active=True,
        reason="reactivate",
        expires_at=future,
        request_id="edge",
    )
    assert_api_error(
        "status_invalid",
        lambda: service.set_user_status(
            db_session,
            actor=principal,
            target_user_id=target.id,
            status="unknown",
            reason="invalid",
            request_id="edge",
        ),
    )
    assert_api_error(
        "not_found",
        lambda: service.set_user_status(
            db_session,
            actor=principal,
            target_user_id=uuid.uuid4(),
            status="active",
            reason="missing",
            request_id="edge",
        ),
    )
    pending = User(email_normalized="not-activated@example.test", display_name="Pending")
    db_session.add(pending)
    db_session.flush()
    assert_api_error(
        "activation_required",
        lambda: service.set_user_status(
            db_session,
            actor=principal,
            target_user_id=pending.id,
            status="active",
            reason="reactivate",
            request_id="edge",
        ),
    )
    service._protect_final_superuser(db_session, pending.id)
    grant = db_session.scalar(select(GlobalRoleGrant).where(GlobalRoleGrant.user_id == target.id))
    assert grant is not None
    service.set_user_status(
        db_session,
        actor=principal,
        target_user_id=target.id,
        status="suspended",
        reason="temporary",
        request_id="edge",
    )
    service.set_user_status(
        db_session,
        actor=principal,
        target_user_id=target.id,
        status="active",
        reason="restored",
        request_id="edge",
    )
