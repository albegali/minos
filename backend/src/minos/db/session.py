"""Async engine and session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(url: str, **kwargs: object) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True, **kwargs)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def asyncpg_dsn(url: str) -> str:
    """SQLAlchemy URL -> plain DSN for a raw asyncpg connection (LISTEN)."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)
