"""Hermetic tests for bounded SQLAlchemy engine construction (no database connection)."""

from __future__ import annotations

import pytest

from review_platform.common.engine import EnginePoolSettings, create_pooled_engine

pytestmark = pytest.mark.no_db

# A well-formed DSN is enough: create_engine builds the pool lazily and never connects here.
_URL = "postgresql+psycopg://user:pass@localhost:5432/db"


def test_default_pool_settings_are_conservative() -> None:
    pool = EnginePoolSettings()
    assert pool.pool_size == 5
    # Smaller than SQLAlchemy's default max_overflow (10) to cap per-instance fan-out, and
    # connection recycling is enabled by default.
    assert pool.max_overflow == 5
    assert pool.pool_timeout == 30.0
    assert pool.pool_recycle == 1800


def test_explicit_pool_bounds_are_applied() -> None:
    engine = create_pooled_engine(_URL, EnginePoolSettings(2, 3, 15.0, 900))
    pool = engine.pool
    assert pool.size() == 2
    assert pool._max_overflow == 3
    assert pool._timeout == 15.0
    assert pool._recycle == 900
    # pre-ping stays on so a recycled/stale connection is detected before use.
    assert pool._pre_ping is True


def test_no_pool_preserves_library_defaults() -> None:
    # Callers that do not opt in (short-lived CLI/batch/seed engines) keep SQLAlchemy's defaults,
    # so their behaviour is unchanged.
    engine = create_pooled_engine(_URL)
    pool = engine.pool
    assert pool.size() == 5
    assert pool._max_overflow == 10
    assert pool._recycle == -1
    assert pool._pre_ping is True
