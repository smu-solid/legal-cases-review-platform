"""Review-owned PostgreSQL engine and transaction wiring."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, event, text
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session, sessionmaker

from review_platform.common.engine import EnginePoolSettings, create_pooled_engine

MIGRATION_HEAD = "0001"


def _set_utc_timezone(connection: DBAPIConnection, _record: object) -> None:
    """Keep timestamps stable when PostgreSQL reloads saved values."""
    original_autocommit = connection.autocommit
    connection.autocommit = True
    try:
        cursor = connection.cursor()
        try:
            cursor.execute("SET TIME ZONE 'UTC'")
        finally:
            cursor.close()
    finally:
        connection.autocommit = original_autocommit


class DatabaseUnavailableError(RuntimeError):
    pass


class Database:
    """Database."""

    def __init__(self, url: str | None, *, pool: EnginePoolSettings | None = None) -> None:
        self.engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None
        if url is not None:
            self.engine = create_pooled_engine(url, pool)
            event.listen(self.engine, "connect", _set_utc_timezone, insert=True)
            self._session_factory = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        if self._session_factory is None:
            raise DatabaseUnavailableError("review database is not configured")
        with self._session_factory() as session:
            yield session

    def check(self) -> bool:
        if self.engine is None:
            return False
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                revision = connection.scalar(
                    text("SELECT version_num FROM review_platform.review_platform_alembic_version")
                )
                if revision != MIGRATION_HEAD:
                    return False
        except Exception:
            return False
        return True

    def dispose(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
