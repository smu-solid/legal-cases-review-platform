"""Review-owned SQLAlchemy persistence models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "review_platform"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('active','suspended','closed')", name="ck_tenant_status"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="active")
    lock_version: Mapped[int] = mapped_column(Integer, default=1)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('pending','active','suspended')", name="ck_user_status"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_normalized: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    authorization_epoch: Mapped[int] = mapped_column(Integer, default=1)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(String(500))
    lock_version: Mapped[int] = mapped_column(Integer, default=1)


class TenantMembership(Base, TimestampMixin):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_user"),
        CheckConstraint("status IN ('pending','active','suspended')", name="ck_membership_status"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenants.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")


class UserActivationChallenge(Base, TimestampMixin):
    __tablename__ = "user_activation_challenges"
    __table_args__ = (
        Index("ix_activation_token_digest", "token_digest", unique=True),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE")
    )
    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)


class PasswordResetChallenge(Base, TimestampMixin):
    __tablename__ = "password_reset_challenges"
    __table_args__ = (
        Index("ix_password_reset_token_digest", "token_digest", unique=True),
        CheckConstraint(
            "request_source IN ('self_service','admin')", name="ck_password_reset_request_source"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE")
    )
    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    request_source: Mapped[str] = mapped_column(String(20))
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )


class RoleGrant(Base):
    __tablename__ = "role_grants"
    __table_args__ = (
        UniqueConstraint("membership_id", "role_code", name="uq_membership_role"),
        CheckConstraint(
            "role_code IN ('reviewer','adjudicator','campaign_manager','user_admin','auditor')",
            name="ck_tenant_role",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    membership_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenant_memberships.id", ondelete="CASCADE")
    )
    role_code: Mapped[str] = mapped_column(String(40))
    granted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GlobalRoleGrant(Base):
    __tablename__ = "global_role_grants"
    __table_args__ = (
        UniqueConstraint("user_id", "role_code", name="uq_user_global_role"),
        CheckConstraint("role_code = 'super_admin'", name="ck_global_role"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE")
    )
    role_code: Mapped[str] = mapped_column(String(40), default="super_admin")
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    reason: Mapped[str] = mapped_column(String(500))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ServerSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_session_token_digest", "token_digest", unique=True),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE")
    )
    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32))
    csrf_digest: Mapped[bytes] = mapped_column(LargeBinary(32))
    authorization_epoch: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Opt-in longer-lived ("remember me") session; drives which idle/absolute timeout is applied.
    remember_me: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(120))


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"
    __table_args__ = (
        UniqueConstraint("scope", "key_digest", name="uq_auth_rate_limit_scope_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(40))
    key_digest: Mapped[bytes] = mapped_column(LargeBinary(32))
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_actor_occurred", "actor_user_id", "occurred_at"),
        Index("ix_audit_object_occurred", "object_type", "object_id", "occurred_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sequence: Mapped[int] = mapped_column(BigInteger, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_type: Mapped[str] = mapped_column(String(40))
    event_type: Mapped[str] = mapped_column(String(100))
    object_type: Mapped[str] = mapped_column(String(80))
    object_id: Mapped[str] = mapped_column(String(100))
    request_id: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_schema_version: Mapped[int] = mapped_column(Integer, default=1)
    prev_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)
