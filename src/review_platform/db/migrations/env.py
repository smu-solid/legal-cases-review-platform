"""Review-owned Alembic environment."""

from __future__ import annotations

from logging.config import fileConfig
from typing import cast

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from review_platform.db.models import SCHEMA, Base
from review_platform.review import models as review_models  # noqa: F401
from review_platform.settings import Settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def database_url() -> str:
    settings = cast(Settings, config.attributes.get("review_platform_settings")) or Settings()
    url = settings.migration_database_url or settings.database_url
    if url is None:
        raise RuntimeError("REVIEW_MIGRATION_DATABASE_URL is required for migrations")
    return url


def migration_options() -> dict[str, object]:
    return {
        "target_metadata": target_metadata,
        "version_table": "review_platform_alembic_version",
        "version_table_schema": SCHEMA,
        "include_schemas": True,
        "compare_type": True,
    }


def run_migrations_offline() -> None:
    context.configure(url=database_url(), literal_binds=True, **migration_options())
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = database_url().replace("%", "%%")
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        connection.commit()
        context.configure(connection=connection, **migration_options())
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
