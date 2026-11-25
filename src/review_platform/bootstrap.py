"""Offline, one-time first-superuser bootstrap."""

from __future__ import annotations

import getpass
import uuid
from typing import cast

from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from review_platform.auth.service import FINAL_SUPERUSER_LOCK_ID, now_utc
from review_platform.common.audit import append_audit_event
from review_platform.db.models import (
    GlobalRoleGrant,
    RoleGrant,
    Tenant,
    TenantMembership,
    User,
)
from review_platform.db.session import Database, DatabaseUnavailableError
from review_platform.security import hash_password, normalize_email
from review_platform.settings import Settings


class BootstrapRefusedError(RuntimeError):
    pass


_MAX_GLOBAL_ADMINS_BY_ENVIRONMENT: dict[str, int] = {"production": 3}
_DEFAULT_MAX_GLOBAL_ADMINS = 1


def max_global_admins(settings: Settings) -> int:
    """The number of standing global administrators this environment permits.

    Resolution order: an explicit ``settings.max_global_admins`` (``REVIEW_MAX_GLOBAL_ADMINS``)
    always wins; otherwise falls back to the per-environment default below.
    """

    if settings.max_global_admins is not None:
        return settings.max_global_admins
    return _MAX_GLOBAL_ADMINS_BY_ENVIRONMENT.get(settings.environment, _DEFAULT_MAX_GLOBAL_ADMINS)


def existing_global_admins(session: Session) -> int:
    """Count the global role grants already seated (matches the bootstrap budget check)."""

    return session.scalar(select(func.count()).select_from(GlobalRoleGrant)) or 0


def seat_global_admin(
    session: Session,
    *,
    settings: Settings,
    email: str,
    display_name: str,
    password_hash: str | None,
    tenant_key: str,
    tenant_name: str,
    reason: str,
    actor_type: str,
    request_id: str,
) -> uuid.UUID:
    """Create one global administrator (user + tenant membership + non-expiring global grant)."""

    user = User(
        email_normalized=normalize_email(email),
        display_name=display_name,
        password_hash=password_hash,
        status="active",
        activated_at=now_utc(),
    )
    session.add(user)
    tenant = session.scalar(select(Tenant).where(Tenant.key == tenant_key))
    if tenant is None:
        tenant = Tenant(key=tenant_key, name=tenant_name)
        session.add(tenant)
    session.flush()
    membership = TenantMembership(tenant_id=tenant.id, user_id=user.id, status="active")
    session.add(membership)
    session.flush()
    session.add_all(
        [
            RoleGrant(
                membership_id=membership.id,
                role_code="user_admin",
                granted_by=user.id,
            ),
            GlobalRoleGrant(
                user_id=user.id,
                granted_by=None,
                reason=reason,
                expires_at=None,
            ),
        ]
    )
    append_audit_event(
        session,
        actor_user_id=user.id,
        actor_type=actor_type,
        event_type="admin.bootstrap_genesis",
        object_type="user",
        object_id=str(user.id),
        request_id=request_id,
        payload={"tenant_id": str(tenant.id)},
        key=cast(SecretStr, settings.audit_hmac_key).get_secret_value(),
    )
    return user.id


def bootstrap_first_superuser(
    session: Session,
    *,
    settings: Settings,
    email: str,
    display_name: str,
    password: str,
    tenant_key: str,
    tenant_name: str,
) -> uuid.UUID:
    """Create the genesis administrator under a PostgreSQL advisory lock."""

    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": FINAL_SUPERUSER_LOCK_ID},
    )
    existing = existing_global_admins(session)
    max_admins = max_global_admins(settings)
    if existing >= max_admins:
        raise BootstrapRefusedError(
            f"{existing} global role grant(s) already exist; max {max_admins} for "
            f"environment {settings.environment!r}"
        )
    return seat_global_admin(
        session,
        settings=settings,
        email=email,
        display_name=display_name,
        password_hash=hash_password(password, settings),
        tenant_key=tenant_key,
        tenant_name=tenant_name,
        reason="first-superuser bootstrap",
        actor_type="bootstrap",
        request_id="offline-bootstrap",
    )


def main() -> None:
    settings = Settings()
    if settings.database_url is None:
        raise DatabaseUnavailableError("REVIEW_DATABASE_URL is required")
    email = input("Super administrator email: ").strip()
    display_name = input("Display name: ").strip()
    tenant_key = (
        input(f"Initial tenant key [{settings.default_tenant_key}]: ").strip()
        or settings.default_tenant_key
    )
    tenant_name = (
        input(f"Initial tenant name [{settings.default_tenant_name}]: ").strip()
        or settings.default_tenant_name
    )
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise BootstrapRefusedError("password confirmation does not match")
    database = Database(settings.database_url)
    with database.session() as session, session.begin():
        user_id = bootstrap_first_superuser(
            session,
            settings=settings,
            email=email,
            display_name=display_name,
            password=password,
            tenant_key=tenant_key,
            tenant_name=tenant_name,
        )
        tenant = session.scalar(select(Tenant).where(Tenant.key == tenant_key))
        assert tenant is not None  # nosec B101 -- created/reused above in the same transaction
        tenant_id = tenant.id
    print(f"Created first super administrator {user_id}")
    print(f"  tenant key  {tenant_key}")
    print(f"  tenant id   {tenant_id}")
    print(
        "  The dataset importer resolves the same tenant by default (REVIEW_DEFAULT_TENANT_KEY, "
        f"currently {settings.default_tenant_key!r}) -- keep it unset or matching this key so "
        "seeded cases land in the tenant this admin can see."
    )


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    main()
