"""Password authentication, revocable sessions, CSRF and reauthentication."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.base import AuthServiceBase
from review_platform.auth.principal import Principal, now_utc
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.db.models import ServerSession, User
from review_platform.security import new_token, normalize_email, token_digest, verify_password


class SessionMixin(AuthServiceBase):
    def login(
        self, session: Session, *, email: str, password: str, raw_csrf: str, request_id: str
    ) -> tuple[str, Principal]:
        normalized = normalize_email(email)
        user = session.scalar(
            select(User).where(User.email_normalized == normalized).with_for_update()
        )
        valid = verify_password(user.password_hash if user else None, password)
        if not valid or user is None or user.status != "active":
            raise APIError(
                401, "invalid_credentials", "Sign-in failed", "The email or password is incorrect."
            )
        current = now_utc()
        raw = new_token()
        row = ServerSession(
            user_id=user.id,
            token_digest=token_digest(raw, self.session_key),
            csrf_digest=token_digest(raw_csrf, self.session_key),
            authorization_epoch=user.authorization_epoch,
            created_at=current,
            last_seen_at=current,
            idle_expires_at=current + timedelta(seconds=self.settings.session_idle_seconds),
            absolute_expires_at=current + timedelta(seconds=self.settings.session_absolute_seconds),
            remember_me=False,
        )
        session.add(row)
        session.flush()
        append_audit_event(
            session,
            actor_user_id=user.id,
            actor_type="user",
            event_type="auth.login",
            object_type="session",
            object_id=str(row.id),
            request_id=request_id,
            payload={},
            key=self.audit_key,
        )
        return raw, Principal(user, row)

    def resolve_principal(self, session: Session, raw_token: str | None) -> Principal:
        if raw_token is None:
            raise self.authentication_required()
        row = session.scalar(
            select(ServerSession).where(
                ServerSession.token_digest == token_digest(raw_token, self.session_key)
            )
        )
        current = now_utc()
        if (
            row is None
            or row.revoked_at is not None
            or row.absolute_expires_at <= current
            or row.idle_expires_at <= current
        ):
            raise self.authentication_required()
        user = session.get(User, row.user_id)
        if (
            user is None
            or user.status != "active"
            or user.authorization_epoch != row.authorization_epoch
        ):
            raise self.authentication_required()
        row.last_seen_at = current
        row.idle_expires_at = min(
            row.absolute_expires_at, current + timedelta(seconds=self.settings.session_idle_seconds)
        )
        return Principal(user, row)

    def logout(self, session: Session, principal: Principal, *, request_id: str) -> None:
        if principal.server_session is not None:
            principal.server_session.revoked_at = now_utc()
            principal.server_session.revocation_reason = "logout"
            append_audit_event(
                session,
                actor_user_id=principal.user.id,
                actor_type="user",
                event_type="auth.logout",
                object_type="session",
                object_id=str(principal.server_session.id),
                request_id=request_id,
                payload={},
                key=self.audit_key,
            )

    def rotate_csrf(self, principal: Principal, raw_csrf: str) -> None:
        if principal.server_session is not None:
            principal.server_session.csrf_digest = token_digest(raw_csrf, self.session_key)

    def verify_session_csrf(self, principal: Principal, raw_csrf: str) -> bool:
        return (
            principal.server_session is not None
            and principal.server_session.csrf_digest == token_digest(raw_csrf, self.session_key)
        )

    def verify_reauthentication(self, actor: Principal, password: str) -> None:
        if not verify_password(actor.user.password_hash, password):
            raise APIError(
                403,
                "reauth_required",
                "Reauthentication required",
                "Recent credentials are required.",
            )
