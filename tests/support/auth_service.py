from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.errors import APIError
from review_platform.db.models import User
from review_platform.security import hash_password
from review_platform.settings import Settings
from tests.support.identities import TEST_PASSWORD, AdminIdentity


def admin_principal(session: Session, settings: Settings, admin: AdminIdentity) -> Principal:
    return Principal(session.get(User, admin.user_id))


def add_active_user(session: Session, settings: Settings, email: str) -> User:
    user = User(
        email_normalized=email,
        display_name="Edge User",
        password_hash=hash_password(TEST_PASSWORD, settings),
        status="active",
        activated_at=datetime.now(UTC),
    )
    session.add(user)
    session.flush()
    return user


def assert_api_error(code: str, callable_: object) -> None:
    with pytest.raises(APIError) as captured:
        callable_()  # type: ignore[operator]
    assert captured.value.code == code
