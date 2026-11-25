from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from review_platform.common.audit import append_audit_event
from review_platform.db.models import AuthRateLimit
from review_platform.rate_limit import enforce_rate_limit
from review_platform.security import (
    InvalidPasswordError,
    constant_time_equal,
    hash_password,
    normalize_email,
    password_needs_rehash,
    token_digest,
    verify_password,
)
from review_platform.settings import Settings
from tests.support.identities import TEST_PASSWORD


def test_settings_and_password_primitives(settings: Settings) -> None:
    assert normalize_email("  Tést@Example.TEST ") == "tést@example.test"
    encoded = hash_password(TEST_PASSWORD, settings)
    assert verify_password(encoded, TEST_PASSWORD)
    assert not password_needs_rehash(encoded)
    assert not verify_password(encoded, "wrong")
    assert not verify_password(None, "wrong")
    assert not verify_password("malformed", TEST_PASSWORD)
    assert token_digest("token", "k" * 32) == token_digest("token", "k" * 32)
    assert constant_time_equal("same", "same")
    assert not constant_time_equal(None, "same")
    with pytest.raises(InvalidPasswordError):
        hash_password("short", settings)
    with pytest.raises(InvalidPasswordError):
        hash_password("é" * 600, settings)


def test_production_settings_fail_closed() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            database_url=None,
            session_hmac_key=None,
            activation_hmac_key=None,
        )
    with pytest.raises(ValidationError):
        Settings(session_idle_seconds=600, session_absolute_seconds=300)
    with pytest.raises(ValidationError):
        Settings(session_hmac_key="short", activation_hmac_key="also-short")
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://example",
            cookie_secure=False,
            session_hmac_key="s" * 32,
            activation_hmac_key="a" * 32,
        )
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://example",
            session_hmac_key=None,
            activation_hmac_key=None,
        )
    complete = {
        # Isolate the local dotenv so a dev `.env` (e.g. filesystem source-render storage) cannot
        # leak into these production-settings assertions; the app still reads `.env` at runtime.
        "_env_file": None,
        "environment": "production",
        "database_url": "postgresql+psycopg://runtime@example/review",
        "migration_database_url": "postgresql+psycopg://migrator@example/review",
        "session_hmac_key": "s" * 32,
        "activation_hmac_key": "a" * 32,
        "rate_limit_hmac_key": "r" * 32,
        "audit_hmac_key": "u" * 32,
    }
    for overrides in (
        # A migration DSN equal to the runtime DSN still breaks the strict separation...
        {"migration_database_url": complete["database_url"]},
        {"allowed_origins": ("http://example.test",)},
        {"app_base_url": "http://example.test"},
        {"activation_hmac_key": complete["session_hmac_key"]},
    ):
        with pytest.raises(ValidationError):
            Settings(**(complete | overrides))  # type: ignore[arg-type]
    # ...but the API runtime no longer requires the migration DSN at all: production is valid with
    # only the least-privilege runtime DSN, so the API service is never given the migration
    # credential (Alembic runs as a separate migration job/role).
    runtime_only = Settings(**(complete | {"migration_database_url": None}))  # type: ignore[arg-type]
    assert runtime_only.migration_database_url is None
    assert runtime_only.environment == "production"
    valid_production = Settings(
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg://runtime@example/review",
        migration_database_url="postgresql+psycopg://migrator@example/review",
        session_hmac_key="s" * 32,
        activation_hmac_key="a" * 32,
        rate_limit_hmac_key="r" * 32,
        audit_hmac_key="u" * 32,
    )
    assert valid_production.environment == "production"
    generated = Settings(
        _env_file=None,
        session_hmac_key=None,
        activation_hmac_key=None,
        rate_limit_hmac_key=None,
        audit_hmac_key=None,
    )
    assert generated.session_hmac_key is not None
    assert generated.activation_hmac_key is not None
    assert generated.rate_limit_hmac_key is not None
    assert generated.audit_hmac_key is not None


def test_security_guard_failure_branches(db_session: Session, settings: Settings) -> None:
    fake = MagicMock()
    fake.scalar.return_value = None
    with pytest.raises(RuntimeError, match="audit sequence"):
        append_audit_event(
            fake,
            actor_user_id=None,
            actor_type="test",
            event_type="test",
            object_type="test",
            object_id="test",
            request_id="test",
            payload={},
            key="k" * 32,
        )

    fake.scalar.return_value = None
    with pytest.raises(RuntimeError, match="bucket creation"):
        enforce_rate_limit(
            fake,
            scope="test",
            identity="peer",
            key="k" * 32,
            limit=1,
            window_seconds=10,
        )

    bucket = AuthRateLimit(
        scope="expired",
        key_digest=token_digest("peer", "k" * 32),
        window_started_at=datetime.now(UTC) - timedelta(minutes=5),
        attempts=99,
    )
    db_session.add(bucket)
    db_session.flush()
    enforce_rate_limit(
        db_session,
        scope="expired",
        identity="peer",
        key="k" * 32,
        limit=1,
        window_seconds=10,
    )
    assert bucket.attempts == 1
