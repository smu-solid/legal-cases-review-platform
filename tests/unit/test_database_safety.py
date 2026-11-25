from __future__ import annotations

from io import StringIO

import pytest
from alembic import command
from alembic.config import Config

from review_platform.settings import Settings
from tests import conftest

pytestmark = pytest.mark.no_db
TEST_URL = "postgresql+psycopg://user:password@127.0.0.1:57433/review_oss_test"


@pytest.mark.parametrize(
    "migration_url",
    [
        "postgresql+psycopg://user:password@127.0.0.1:57432/review_oss",
        "postgresql+psycopg://user:password@remote:5432/review_oss_test",
        "postgresql+psycopg://user:password@127.0.0.1:55433/review_oss_test",
    ],
)
def test_direct_pytest_rejects_unsafe_migration_database(monkeypatch, migration_url):
    monkeypatch.setenv("REVIEW_DATABASE_URL", TEST_URL)
    monkeypatch.setenv("REVIEW_TEST_DATABASE_URL", TEST_URL)
    monkeypatch.setenv("REVIEW_MIGRATION_DATABASE_URL", migration_url)
    with pytest.raises(ValueError):
        conftest.settings.__wrapped__()


def test_direct_pytest_defaults_migrations_to_validated_test_database(monkeypatch):
    monkeypatch.setenv("REVIEW_DATABASE_URL", TEST_URL)
    monkeypatch.setenv("REVIEW_TEST_DATABASE_URL", TEST_URL)
    monkeypatch.delenv("REVIEW_MIGRATION_DATABASE_URL", raising=False)
    settings = conftest.settings.__wrapped__()
    assert settings.database_url == settings.migration_database_url == TEST_URL


def test_test_fixture_passes_validated_settings_to_alembic(monkeypatch):
    monkeypatch.setenv("REVIEW_DATABASE_URL", TEST_URL)
    monkeypatch.setenv("REVIEW_TEST_DATABASE_URL", TEST_URL)
    monkeypatch.setenv("REVIEW_MIGRATION_DATABASE_URL", TEST_URL)
    settings = conftest.settings.__wrapped__()
    seen = []
    monkeypatch.setattr(conftest.command, "upgrade", lambda config, revision: seen.append(config))

    class DisposableDatabase:
        def __init__(self, url):
            assert url == TEST_URL

        def dispose(self):
            pass

    monkeypatch.setattr(conftest, "Database", DisposableDatabase)
    fixture = conftest.database.__wrapped__(settings)
    next(fixture)
    assert seen[0].attributes["review_platform_settings"] is settings
    fixture.close()


def test_alembic_uses_bound_test_settings_instead_of_dotenv_or_environment(monkeypatch):
    import sqlalchemy

    settings = Settings(
        _env_file=None, environment="test", database_url=TEST_URL, migration_database_url=TEST_URL
    )
    monkeypatch.setenv("REVIEW_DATABASE_URL", "postgresql://other/real")
    monkeypatch.setenv("REVIEW_MIGRATION_DATABASE_URL", "postgresql://other/real")

    def unexpected_connection(*args, **kwargs):
        pytest.fail("offline migration must never create a database connection")

    monkeypatch.setattr(sqlalchemy, "engine_from_config", unexpected_connection)
    from alembic import context

    configured_urls = []
    configure = context.configure

    def record_configuration(*args, **kwargs):
        configured_urls.append(kwargs.get("url"))
        return configure(*args, **kwargs)

    monkeypatch.setattr(context, "configure", record_configuration)
    output = StringIO()
    config = Config("alembic.ini", output_buffer=output)
    config.attributes["review_platform_settings"] = settings
    command.upgrade(config, "head", sql=True)
    assert configured_urls == [TEST_URL]
    assert "CREATE TABLE" in output.getvalue()
    assert "review_platform" in output.getvalue()
