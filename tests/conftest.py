from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from review_platform.bootstrap import bootstrap_first_superuser
from review_platform.db.session import Database
from review_platform.main import create_app
from review_platform.settings import Settings
from tests.support.identities import TEST_PASSWORD, AdminIdentity


@pytest.fixture(scope="session")
def settings() -> Settings:
    database_url = os.environ.get("REVIEW_DATABASE_URL")
    if not database_url:
        pytest.fail("REVIEW_DATABASE_URL must target the disposable review test database")
    from review_platform.db.test_safety import validate_test_database

    expected_url = os.environ.get("REVIEW_TEST_DATABASE_URL")
    migration_url = os.environ.get("REVIEW_MIGRATION_DATABASE_URL") or database_url
    validate_test_database(database_url, expected_url=expected_url)
    validate_test_database(migration_url, expected_url=expected_url)
    return Settings(
        _env_file=None,  # deterministic test settings, independent of a developer's local .env
        environment="test",
        database_url=database_url,
        migration_database_url=migration_url,
        session_hmac_key="test-session-key-000000000000000000000000",
        activation_hmac_key="test-activation-key-000000000000000000000",
        rate_limit_hmac_key="test-rate-limit-key-00000000000000000000",
        audit_hmac_key="test-audit-key-0000000000000000000000000",
        synthetic_import_enabled=True,
        allowed_origins=("https://testserver",),
        allowed_hosts=("testserver",),
    )


@pytest.fixture(scope="session")
def database(settings: Settings) -> Iterator[Database]:
    config = Config("alembic.ini")
    config.attributes["review_platform_settings"] = settings
    command.upgrade(config, "head")
    database = Database(settings.database_url)
    yield database
    database.dispose()


@pytest.fixture(autouse=True)
def clean_review_database(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("no_db") is not None:
        return
    database = request.getfixturevalue("database")
    with database.session() as session, session.begin():
        session.execute(
            text(
                "TRUNCATE TABLE review_platform.tenants, review_platform.users, "
                "review_platform.audit_events, review_platform.auth_rate_limits "
                "RESTART IDENTITY CASCADE"
            )
        )
        session.execute(text("ALTER SEQUENCE review_platform.audit_event_sequence RESTART WITH 1"))


@pytest.fixture
def db_session(database: Database) -> Iterator[Session]:
    with database.session() as session, session.begin():
        yield session


@pytest.fixture
def admin(database: Database, settings: Settings) -> AdminIdentity:
    with database.session() as session, session.begin():
        user_id = bootstrap_first_superuser(
            session,
            settings=settings,
            email="admin@example.test",
            display_name="Initial Admin",
            password=TEST_PASSWORD,
            tenant_key="tenant-synthetic-alpha",
            tenant_name="Synthetic Alpha",
        )
        row = session.execute(
            text(
                "SELECT tm.tenant_id, tm.id FROM review_platform.tenant_memberships tm "
                "WHERE tm.user_id = :user_id"
            ),
            {"user_id": user_id},
        ).one()
    return AdminIdentity(
        user_id=user_id,
        tenant_id=row.tenant_id,
        membership_id=row.id,
        email="admin@example.test",
        password=TEST_PASSWORD,
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://testserver"
        ) as test_client:
            yield test_client
    finally:
        app.state.context.database.dispose()
