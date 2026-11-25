"""PostgreSQL-backed authentication abuse controls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.db.models import AuthRateLimit
from review_platform.security import token_digest


def enforce_rate_limit(
    session: Session,
    *,
    scope: str,
    identity: str,
    key: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Atomically consume one fixed-window attempt from a shared database bucket."""

    current = datetime.now(UTC)
    digest = token_digest(identity, key)
    session.execute(
        insert(AuthRateLimit)
        .values(
            scope=scope,
            key_digest=digest,
            window_started_at=current,
            attempts=0,
        )
        .on_conflict_do_nothing(constraint="uq_auth_rate_limit_scope_key")
    )
    bucket = session.scalar(
        select(AuthRateLimit)
        .where(AuthRateLimit.scope == scope, AuthRateLimit.key_digest == digest)
        .with_for_update()
    )
    if bucket is None:
        raise RuntimeError("rate-limit bucket creation failed")
    window_end = bucket.window_started_at + timedelta(seconds=window_seconds)
    if window_end <= current:
        bucket.window_started_at = current
        bucket.attempts = 0
        window_end = current + timedelta(seconds=window_seconds)
    if bucket.attempts >= limit:
        retry_after = max(1, int((window_end - current).total_seconds()))
        raise APIError(
            429,
            "rate_limited",
            "Too many requests",
            "Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    bucket.attempts += 1
