"""Authentication value types shared across the auth service surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from review_platform.db.models import ServerSession, User


def now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Principal:
    user: User
    server_session: ServerSession | None = None
