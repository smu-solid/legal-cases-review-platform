"""Grant policy."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from review_platform.auth.principal import now_utc
from review_platform.db.models import GlobalRoleGrant


def has_global_admin(session: Session, user_id: uuid.UUID) -> bool:
    current = now_utc()
    return (
        session.scalar(
            select(func.count())
            .select_from(GlobalRoleGrant)
            .where(
                GlobalRoleGrant.user_id == user_id,
                GlobalRoleGrant.role_code == "super_admin",
                GlobalRoleGrant.revoked_at.is_(None),
                or_(
                    GlobalRoleGrant.expires_at.is_(None),
                    GlobalRoleGrant.expires_at > current,
                ),
            )
        )
        or 0
    ) > 0
