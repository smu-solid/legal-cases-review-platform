"""One-time invitation activation and administrator-requested password resets."""

from __future__ import annotations

from datetime import timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from review_platform.auth.base import AuthServiceBase
from review_platform.auth.principal import now_utc
from review_platform.common.errors import APIError
from review_platform.db.models import (
    PasswordResetChallenge,
    ServerSession,
    TenantMembership,
    User,
    UserActivationChallenge,
)
from review_platform.security import InvalidPasswordError, hash_password, new_token, token_digest


class AccountAccessMixin(AuthServiceBase):
    def issue_activation(self, session: Session, user_id: UUID) -> str:
        token = new_token()
        session.add(
            UserActivationChallenge(
                user_id=user_id,
                token_digest=token_digest(token, self.activation_key),
                expires_at=now_utc() + timedelta(seconds=self.settings.password_reset_ttl_seconds),
            )
        )
        return token

    def set_account_password(
        self, session: Session, *, raw_token: str, password: str, activation: bool
    ) -> None:
        model = UserActivationChallenge if activation else PasswordResetChallenge
        challenge = cast(
            UserActivationChallenge | PasswordResetChallenge | None,
            session.scalar(
                select(model)
                .where(model.token_digest == token_digest(raw_token, self.activation_key))
                .with_for_update()
            ),
        )
        current = now_utc()
        if (
            challenge is None
            or challenge.consumed_at is not None
            or challenge.expires_at <= current
        ):
            raise APIError(
                400,
                "account_link_invalid",
                "Link unavailable",
                "The account link is invalid or expired.",
            )
        user = session.get(User, challenge.user_id, with_for_update=True)
        if user is None or user.status == "suspended" or (activation and user.status != "pending"):
            raise APIError(
                400,
                "account_link_invalid",
                "Link unavailable",
                "The account link is invalid or expired.",
            )
        try:
            user.password_hash = hash_password(password, self.settings)
        except InvalidPasswordError as exc:
            raise APIError(
                422,
                "password_invalid",
                "Invalid password",
                "The password does not meet the configured requirements.",
            ) from exc
        user.authorization_epoch += 1
        challenge.consumed_at = current
        for challenge_model in (UserActivationChallenge, PasswordResetChallenge):
            session.execute(
                update(challenge_model)
                .where(challenge_model.user_id == user.id, challenge_model.consumed_at.is_(None))
                .values(consumed_at=current)
            )
        if activation:
            user.status = "active"
            user.activated_at = current
            session.execute(
                update(TenantMembership)
                .where(TenantMembership.user_id == user.id, TenantMembership.status == "pending")
                .values(status="active")
            )
        session.execute(
            update(ServerSession)
            .where(ServerSession.user_id == user.id, ServerSession.revoked_at.is_(None))
            .values(revoked_at=current, revocation_reason="password_changed")
        )
