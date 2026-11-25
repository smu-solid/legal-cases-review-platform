"""Bounded SQLAlchemy connection pools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, create_engine


@dataclass(frozen=True)
class EnginePoolSettings:
    """Bounded QueuePool configuration for one engine.

    Defaults are conservative (smaller than SQLAlchemy's ``max_overflow=10``) and add
    connection recycling, which is safe for a single local process yet caps per-instance
    fan-out in production."""

    pool_size: int = 5
    max_overflow: int = 5
    pool_timeout: float = 30.0
    pool_recycle: int = 1800


def create_pooled_engine(url: str, pool: EnginePoolSettings | None = None, **kwargs: Any) -> Engine:
    """Create an engine with ``pool_pre_ping`` and, when ``pool`` is given, explicit bounds.

    When ``pool`` is ``None`` no pool sizing is passed, so the engine keeps SQLAlchemy's
    defaults -- identical to the previous behaviour for callers that do not opt in."""

    if pool is not None:
        kwargs.update(
            pool_size=pool.pool_size,
            max_overflow=pool.max_overflow,
            pool_timeout=pool.pool_timeout,
            pool_recycle=pool.pool_recycle,
        )
    return create_engine(url, pool_pre_ping=True, **kwargs)
